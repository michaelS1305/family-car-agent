import Foundation
import SQLite3

/// A durable projection of the existing identity, not a second authentication system.
/// Session generations are intentionally not durable identity keys.
struct VehicleQueueContext: Equatable, Sendable {
    let environment: String
    let owner: UUID
    let user: Int64
    let family: Int64
    let device: UUID

    init(environment: AppEnvironment, identity: ChatIdentity, device: UUID) throws {
        guard identity.user > 0, identity.family > 0 else { throw VehicleQueueError.invalidInput }
        self.environment = environment.backendURL.absoluteString + "|" + environment.supabaseURL.absoluteString
        owner = identity.owner; user = identity.user; family = identity.family; self.device = device
    }

    fileprivate var key: String {
        "\(environment)|\(owner.uuidString)|\(user)|\(family)|\(device.uuidString)"
    }
}

enum VehicleQueueError: Error { case invalidInput, storage, unsupportedSchema, contextUnavailable, conflict, invalidTransition }
enum VehicleQueueState: String, Codable, Sendable {
    case pending, preparing, registered, awaitingAuthentication, accepted, terminal, blocked
}

struct VehicleLocationEvidence: Codable, Equatable, Sendable {
    let latitude: Double
    let longitude: Double
    let accuracy: Double
    let measuredAt: Date

    fileprivate func validate(at occurrence: Date) throws {
        let age = occurrence.timeIntervalSince(measuredAt)
        guard latitude.isFinite, longitude.isFinite, accuracy.isFinite,
              (-90...90).contains(latitude), (-180...180).contains(longitude),
              accuracy > 0, accuracy <= 100, age.isFinite, (0...30).contains(age)
        else { throw VehicleQueueError.invalidInput }
    }
}

struct QueuedVehicleEvent: Codable, Equatable, Sendable {
    enum Kind: String, Codable, Sendable { case take; case returning = "return" }
    let id: UUID
    let vehicle: UUID
    let occurredAt: Date
    let sequence: Int64
    let kind: Kind
    let takeID: UUID?
    let location: VehicleLocationEvidence?
}

struct VehicleQueueRecord: Sendable {
    let event: QueuedVehicleEvent
    let state: VehicleQueueState
    let attempt: UUID?
    let sessionIdentifier: String?
    let taskIdentifier: Int64?
    let reason: String?
}

/// Only a decoded, validated Backend AdmissionResult belongs here. HTTP status is insufficient.
struct VehicleAdmissionReceipt: Codable, Sendable {
    let kind: String
    let admission_outcome: String?
}

/// One connection per actor; BEGIN IMMEDIATE also serializes separate queue instances/processes.
actor VehicleEventQueue {
    private let db: VehicleQueueDatabase

    static func applicationDirectory() throws -> URL {
        try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                    appropriateFor: nil, create: true).appendingPathComponent("VehicleEventQueue", isDirectory: true)
    }

    init(directory: URL) throws { db = try VehicleQueueDatabase(directory: directory) }

    /// Call only for a newly registered device whose server cursor is known to be zero.
    /// Reopening an existing partition never resets its sequence or unfreezes it.
    func initializeFreshDevice(_ context: VehicleQueueContext) throws {
        try db.transaction {
            let existing = try db.rows("SELECT context FROM devices WHERE environment=? AND device=?",
                                       [context.environment, context.device.uuidString])
            if let row = existing.first {
                guard row[0] == context.key else { throw VehicleQueueError.conflict }
                return
            }
            try db.execute("INSERT INTO devices(context,environment,device,last_sequence,active) VALUES(?,?,?,0,1)",
                           [context.key, context.environment, context.device.uuidString])
        }
    }

    /// Logout/account/family changes freeze the old partition; no events are relabelled or deleted.
    /// A future coordinator must independently cancel/reconcile any system upload tasks.
    func suspend(_ context: VehicleQueueContext) throws {
        try db.transaction {
            try require(context, active: false)
            try db.execute("UPDATE devices SET active=0 WHERE context=?", [context.key])
        }
    }

    /// Explicitly authorized re-entry into the exact same account/family/device only.
    func reactivate(_ context: VehicleQueueContext) throws {
        try db.transaction {
            try require(context, active: false)
            try db.execute("UPDATE devices SET active=1 WHERE context=?", [context.key])
        }
    }

    func enqueueTake(_ context: VehicleQueueContext, id: UUID = UUID(), vehicle: UUID,
                     occurredAt: Date) throws -> QueuedVehicleEvent {
        try enqueue(context, id: id, vehicle: vehicle, occurredAt: occurredAt, takeID: nil, location: nil)
    }

    /// Explicit cause is mandatory: never infer from the last vehicle opened or latest TAKE.
    func enqueueReturn(_ context: VehicleQueueContext, id: UUID = UUID(), vehicle: UUID,
                       occurredAt: Date, takeID: UUID,
                       location: VehicleLocationEvidence?) throws -> QueuedVehicleEvent {
        try enqueue(context, id: id, vehicle: vehicle, occurredAt: occurredAt, takeID: takeID, location: location)
    }

    private func enqueue(_ context: VehicleQueueContext, id: UUID, vehicle: UUID, occurredAt: Date,
                         takeID: UUID?, location: VehicleLocationEvidence?) throws -> QueuedVehicleEvent {
        guard id.uuidString.split(separator: "-")[2].first == "4",
              occurredAt.timeIntervalSince1970.isFinite,
              (0...253402300799).contains(occurredAt.timeIntervalSince1970)
        else { throw VehicleQueueError.invalidInput }
        try location?.validate(at: occurredAt)
        return try db.transaction {
            try require(context)
            if let old = try records(context).first(where: { $0.event.id == id })?.event {
                guard old.vehicle == vehicle, old.occurredAt == occurredAt,
                      old.takeID == takeID, old.location == location else { throw VehicleQueueError.conflict }
                return old
            }
            if let takeID {
                guard let cause = try records(context).first(where: { $0.event.id == takeID }),
                      cause.event.kind == .take, cause.event.vehicle == vehicle,
                      cause.event.occurredAt <= occurredAt else { throw VehicleQueueError.invalidInput }
            }
            guard let text = try db.rows("SELECT last_sequence FROM devices WHERE context=?", [context.key]).first?[0],
                  let last = Int64(text), last < Int64.max else { throw VehicleQueueError.storage }
            let event = QueuedVehicleEvent(id: id, vehicle: vehicle, occurredAt: occurredAt, sequence: last + 1,
                                           kind: takeID == nil ? .take : .returning, takeID: takeID, location: location)
            let payload = String(decoding: try JSONEncoder().encode(event), as: UTF8.self)
            let missingLocation = takeID != nil && location == nil
            try db.execute("UPDATE devices SET last_sequence=? WHERE context=?", [String(event.sequence), context.key])
            try db.execute("INSERT INTO events(id,context,sequence,vehicle,cause,payload,state,reason) VALUES(?,?,?,?,?,?,?,?)",
                           [id.uuidString, context.key, String(event.sequence), vehicle.uuidString, takeID?.uuidString,
                            payload, missingLocation ? "blocked" : "pending", missingLocation ? "missing_location" : nil])
            return event
        }
    }

    /// Read-only recovery snapshot, including frozen and unresolved in-flight records.
    func records(_ context: VehicleQueueContext) throws -> [VehicleQueueRecord] {
        try require(context, active: false)
        return try db.rows("SELECT payload,state,attempt,session,task,reason FROM events WHERE context=? ORDER BY sequence",
                           [context.key]).map { row in
            guard let payload = row[0], let state = row[1].flatMap(VehicleQueueState.init(rawValue:)) else {
                throw VehicleQueueError.storage
            }
            let event = try JSONDecoder().decode(QueuedVehicleEvent.self, from: Data(payload.utf8))
            let attempt = row[2].flatMap(UUID.init(uuidString:))
            let task = row[4].flatMap(Int64.init)
            guard (row[2] == nil || attempt != nil), (row[4] == nil || task != nil) else { throw VehicleQueueError.storage }
            return VehicleQueueRecord(event: event, state: state, attempt: attempt,
                                      sessionIdentifier: row[3], taskIdentifier: task, reason: row[5])
        }
    }

    /// Atomically claims only the unresolved head. A blocked head is never skipped.
    func prepareNext(_ context: VehicleQueueContext) throws -> VehicleQueueRecord? {
        try db.transaction {
            try require(context)
            let all = try records(context)
            guard let head = all.first(where: { $0.state != .accepted && $0.state != .terminal }),
                  head.state == .pending else { return nil }
            if let cause = head.event.takeID, !all.contains(where: { $0.event.id == cause && $0.state == .accepted }) {
                try db.execute("UPDATE events SET state='blocked',reason='cause_not_accepted' WHERE id=?", [head.event.id.uuidString])
                return nil
            }
            try db.execute("UPDATE events SET state='preparing',attempt=?,reason=NULL WHERE id=?",
                           [UUID().uuidString, head.event.id.uuidString])
            return try record(context, head.event.id)
        }
    }

    func markRegistered(_ context: VehicleQueueContext, event: UUID, attempt: UUID,
                        sessionIdentifier: String, taskIdentifier: Int64) throws {
        guard !sessionIdentifier.isEmpty, sessionIdentifier.utf8.count <= 200,
              sessionIdentifier.utf8.allSatisfy({ (45...57).contains($0) || (65...90).contains($0) || (97...122).contains($0) || $0 == 95 }),
              taskIdentifier > 0 else { throw VehicleQueueError.invalidInput }
        try db.transaction {
            try require(context)
            let row = try record(context, event)
            guard row.state == .preparing, row.attempt == attempt else { throw VehicleQueueError.invalidTransition }
            try db.execute("UPDATE events SET state='registered',session=?,task=? WHERE id=?",
                           [sessionIdentifier, String(taskIdentifier), event.uuidString])
        }
    }

    enum Failure: String, Sendable { case authentication, deliveryUnknown, preAdmissionRejection }

    func recordFailure(_ context: VehicleQueueContext, event: UUID, attempt: UUID, failure: Failure) throws {
        try db.transaction {
            try require(context)
            let row = try record(context, event)
            guard [.preparing, .registered].contains(row.state), row.attempt == attempt else {
                throw VehicleQueueError.invalidTransition
            }
            try db.execute("UPDATE events SET state=?,reason=? WHERE id=?",
                           [failure == .authentication ? "awaitingAuthentication" : "blocked", failure.rawValue, event.uuidString])
        }
    }

    /// The caller must first reconcile getAllTasks and establish that no task can still send.
    /// No automatic reset on startup: absence of a task is not proof of server delivery.
    func retryAfterTaskReconciliation(_ context: VehicleQueueContext, event: UUID, attempt: UUID) throws {
        try db.transaction {
            try require(context)
            let row = try record(context, event)
            guard row.attempt == attempt,
                  [.preparing, .registered, .awaitingAuthentication, .blocked].contains(row.state),
                  row.state != .blocked || row.reason == Failure.deliveryUnknown.rawValue else {
                throw VehicleQueueError.invalidTransition
            }
            try db.execute("UPDATE events SET state='pending',attempt=NULL,session=NULL,task=NULL,reason=NULL WHERE id=?",
                           [event.uuidString])
        }
    }

    func applyAdmission(_ context: VehicleQueueContext, event: UUID, attempt: UUID,
                        receipt: VehicleAdmissionReceipt) throws {
        let terminals = ["before_finalized_boundary", "invalid_chronology", "vehicle_retired", "causal_conflict", "reconciliation_policy_exceeded"]
        let state: VehicleQueueState
        if ["accepted", "retry"].contains(receipt.kind), receipt.admission_outcome == "accepted" { state = .accepted }
        else if ["terminal", "retry"].contains(receipt.kind), let outcome = receipt.admission_outcome, terminals.contains(outcome) { state = .terminal }
        else if ["gap", "conflict", "unavailable", "malformed", "future_clock_skew"].contains(receipt.kind), receipt.admission_outcome == nil { state = .blocked }
        else { throw VehicleQueueError.invalidInput }
        try db.transaction {
            try require(context)
            let row = try record(context, event)
            guard row.attempt == attempt, [.preparing, .registered, .blocked, .awaitingAuthentication].contains(row.state) else {
                throw VehicleQueueError.invalidTransition
            }
            try db.execute("UPDATE events SET state=?,reason=? WHERE id=?",
                           [state.rawValue, receipt.admission_outcome ?? receipt.kind, event.uuidString])
        }
    }

    private func require(_ context: VehicleQueueContext, active: Bool = true) throws {
        guard let row = try db.rows("SELECT active FROM devices WHERE context=?", [context.key]).first,
              !active || row[0] == "1" else { throw VehicleQueueError.contextUnavailable }
    }

    private func record(_ context: VehicleQueueContext, _ id: UUID) throws -> VehicleQueueRecord {
        guard let row = try records(context).first(where: { $0.event.id == id }) else { throw VehicleQueueError.conflict }
        return row
    }
}

/// Never escapes its owning actor after initialization. Errors intentionally omit SQL/data.
private final class VehicleQueueDatabase: @unchecked Sendable {
    private let handle: OpaquePointer

    init(directory: URL) throws {
        guard directory.isFileURL else { throw VehicleQueueError.invalidInput }
        let fm = FileManager.default
        try fm.createDirectory(at: directory, withIntermediateDirectories: true)
        #if os(iOS)
        try fm.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication], ofItemAtPath: directory.path)
        var root = directory
        var values = URLResourceValues(); values.isExcludedFromBackup = true
        try root.setResourceValues(values)
        #endif
        var pointer: OpaquePointer?
        let path = directory.appendingPathComponent("vehicle-events.sqlite").path
        guard sqlite3_open_v2(path, &pointer, SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX, nil) == SQLITE_OK,
              let pointer else {
            if let pointer { sqlite3_close_v2(pointer) }
            throw VehicleQueueError.storage
        }
        handle = pointer
        // On an initializer failure Swift releases this object and closes the connection.
        sqlite3_busy_timeout(handle, 5000)
        try execute("PRAGMA foreign_keys=ON")
        // DELETE journal keeps recovery files in the protected, backup-excluded directory.
        try execute("PRAGMA journal_mode=DELETE")
        try execute("PRAGMA synchronous=FULL")
        try transaction {
            guard let version = try rows("PRAGMA user_version").first?[0], ["0", "1"].contains(version) else {
                throw VehicleQueueError.unsupportedSchema
            }
            try execute("CREATE TABLE IF NOT EXISTS devices(context TEXT PRIMARY KEY,environment TEXT NOT NULL,device TEXT NOT NULL,last_sequence INTEGER NOT NULL CHECK(last_sequence>=0),active INTEGER NOT NULL CHECK(active IN(0,1)),UNIQUE(environment,device))")
            try execute("CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,context TEXT NOT NULL REFERENCES devices(context),sequence INTEGER NOT NULL CHECK(sequence>0),vehicle TEXT NOT NULL,cause TEXT REFERENCES events(id),payload TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('pending','preparing','registered','awaitingAuthentication','accepted','terminal','blocked')),attempt TEXT,session TEXT,task INTEGER,reason TEXT,UNIQUE(context,sequence),UNIQUE(context,cause))")
            try execute("PRAGMA user_version=1")
        }
        #if os(iOS)
        try fm.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication], ofItemAtPath: path)
        #endif
    }

    deinit { sqlite3_close_v2(handle) }

    func transaction<T>(_ operation: () throws -> T) throws -> T {
        try execute("BEGIN IMMEDIATE")
        do {
            let value = try operation()
            try execute("COMMIT")
            return value
        } catch {
            try? execute("ROLLBACK")
            throw error
        }
    }

    func execute(_ sql: String, _ values: [String?] = []) throws { _ = try rows(sql, values) }

    func rows(_ sql: String, _ values: [String?] = []) throws -> [[String?]] {
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(handle, sql, -1, &statement, nil) == SQLITE_OK, let statement else { throw VehicleQueueError.storage }
        defer { sqlite3_finalize(statement) }
        for (index, value) in values.enumerated() {
            let result: Int32
            if let value {
                result = value.withCString { sqlite3_bind_text(statement, Int32(index + 1), $0, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self)) }
            } else { result = sqlite3_bind_null(statement, Int32(index + 1)) }
            guard result == SQLITE_OK else { throw VehicleQueueError.storage }
        }
        var result: [[String?]] = []
        while true {
            switch sqlite3_step(statement) {
            case SQLITE_ROW:
                result.append((0..<sqlite3_column_count(statement)).map { column in
                    sqlite3_column_text(statement, column).map { String(cString: $0) }
                })
            case SQLITE_DONE: return result
            default: throw VehicleQueueError.storage
            }
        }
    }
}
