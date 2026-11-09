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

enum ShortcutQueueError: Error { case location, alreadyTaken, noUniqueTake }

/// Local to one app process. Invalidation and the entire sequence-allocating
/// transaction exclude each other. An old permit can never become valid again.
final class VehicleRecordingPermit: @unchecked Sendable {
    private let lock = NSLock()
    private var valid = true
    func invalidate() { lock.withLock { valid = false } }
    fileprivate func record<T>(_ body: () throws -> T) throws -> T {
        try lock.withLock {
            guard valid else { throw VehicleQueueError.contextUnavailable }
            return try body()
        }
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

    /// Server verification must reserve a durable fence BEFORE making any request.
    func beginVerification(_ context: VehicleQueueContext) throws -> UUID {
        try db.beginVerification(context)
    }
    func completeVerification(_ context: VehicleQueueContext, generation: UUID, vehicles: Set<UUID>, namespace: UUID? = nil) throws {
        try db.completeVerification(context, generation: generation, vehicles: vehicles, namespace: namespace)
    }
    func authorizedVehicles(_ context: VehicleQueueContext) throws -> Set<UUID> {
        try db.authorizedVehicles(context)
    }
    /// Synchronous independent connection for logout's synchronous session callback.
    nonisolated static func revokeAuthorization(directory: URL, context: VehicleQueueContext) throws {
        let db = try VehicleQueueDatabase(directory: directory)
        do {
            _ = try db.beginVerification(context)
            try db.transaction {
                try db.execute("UPDATE authorization_scopes SET state='revoked' WHERE context=?", [context.key])
                try db.execute("UPDATE vehicle_authorizations SET allowed=0 WHERE context=?", [context.key])
            }
        } catch {
            // Independent fallback inside the EXISTING database, no new persistence subsystem.
            // Report the original failure even if quarantine succeeds. Never delete the queue.
            try? db.transaction { try db.execute("UPDATE devices SET active=0 WHERE context=?", [context.key]) }
            throw error
        }
    }
    nonisolated static func durableVehicles(directory: URL, context: VehicleQueueContext, namespace: UUID) throws -> Set<UUID> {
        let db = try VehicleQueueDatabase(directory: directory)
        return try db.transaction {
            try db.requireNamespace(context, namespace)
            return try db.authorizedVehicles(context)
        }
    }

    /// Scheduling/restoration must also respect a frozen partition.
    func validateActiveContext(_ context: VehicleQueueContext) throws { try require(context) }

    /// Every allocated sequence has one retained row, including settled events.
    func validateSequence(_ context: VehicleQueueContext) throws {
        let rows = try db.rows("""
            SELECT d.last_sequence, COUNT(e.id), COALESCE(MAX(e.sequence),0)
            FROM devices d LEFT JOIN events e ON e.context=d.context
            WHERE d.context=? AND d.active=1 GROUP BY d.context
            """, [context.key])
        guard let row = rows.first, row[0] == row[1], row[0] == row[2]
        else { throw VehicleQueueError.contextUnavailable }
    }

    /// A lost registration journal must not disguise an existing installation as new.
    func hasDeviceHistory(environment: AppEnvironment, owner: UUID) throws -> Bool {
        let name = environment.backendURL.absoluteString + "|" + environment.supabaseURL.absoluteString
        let prefix = name + "|" + owner.uuidString + "|"
        return try db.rows("SELECT context FROM devices WHERE environment=?", [name])
            .contains { $0[0]?.hasPrefix(prefix) == true }
    }

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
            try db.execute("UPDATE authorization_scopes SET generation=?,state='revoked' WHERE context=?", [UUID().uuidString, context.key])
            try db.execute("UPDATE vehicle_authorizations SET allowed=0 WHERE context=?", [context.key])
        }
    }

    /// Explicitly authorized re-entry into the exact same account/family/device only.
    func reactivate(_ context: VehicleQueueContext) throws {
        try db.transaction {
            try require(context, active: false)
            // Invalidate outstanding verification tickets BEFORE lifting a quarantine.
            try db.execute("UPDATE authorization_scopes SET generation=?,state='verificationPending' WHERE context=?", [UUID().uuidString, context.key])
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

    func recordAuthorizedShortcut(_ context: VehicleQueueContext, vehicle: UUID, kind: QueuedVehicleEvent.Kind,
                                  time: Date, location: VehicleLocationEvidence?, namespace: UUID, permit: VehicleRecordingPermit) throws -> QueuedVehicleEvent {
        try permit.record {
            guard kind == .take || location != nil else { throw ShortcutQueueError.location }
            return try enqueue(context, id: UUID(), vehicle: vehicle, occurredAt: time, takeID: nil,
                               location: location, shortcut: kind, namespace: namespace)
        }
    }

    func recordShortcut(_ context: VehicleQueueContext, vehicle: UUID, kind: QueuedVehicleEvent.Kind,
                        time: Date, location: VehicleLocationEvidence?) throws -> QueuedVehicleEvent {
        guard kind == .take || location != nil else { throw ShortcutQueueError.location }
        return try enqueue(context, id: UUID(), vehicle: vehicle, occurredAt: time, takeID: nil,
                           location: location, shortcut: kind)
    }

    private func enqueue(_ context: VehicleQueueContext, id: UUID, vehicle: UUID, occurredAt: Date,
                         takeID: UUID?, location: VehicleLocationEvidence?, shortcut: QueuedVehicleEvent.Kind? = nil, namespace: UUID? = nil) throws -> QueuedVehicleEvent {
        guard id.uuidString.split(separator: "-")[2].first == "4",
              occurredAt.timeIntervalSince1970.isFinite,
              (0...253402300799).contains(occurredAt.timeIntervalSince1970)
        else { throw VehicleQueueError.invalidInput }
        try location?.validate(at: occurredAt)
        return try db.transaction {
            try require(context)
            guard try db.authorizedVehicles(context).contains(vehicle) else { throw VehicleQueueError.contextUnavailable }
            if let namespace { try db.requireNamespace(context, namespace) }
            var takeID = takeID
            if let shortcut {
                let rows = try records(context).filter { $0.event.vehicle == vehicle }
                let paired = Set(rows.compactMap { $0.event.takeID })
                let open = rows.filter { $0.event.kind == .take && $0.state != .terminal && !paired.contains($0.event.id) }
                if shortcut == .take {
                    guard open.isEmpty else { throw ShortcutQueueError.alreadyTaken }
                } else {
                    guard open.count == 1 else { throw ShortcutQueueError.noUniqueTake }
                    takeID = open[0].event.id
                }
            }
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
            guard try db.authorizedVehicles(context).contains(head.event.vehicle) else { throw VehicleQueueError.contextUnavailable }
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
            guard try db.authorizedVehicles(context).contains(row.event.vehicle) else { throw VehicleQueueError.contextUnavailable }
            guard row.state == .preparing, row.attempt == attempt else { throw VehicleQueueError.invalidTransition }
            try db.execute("UPDATE events SET state='registered',session=?,task=? WHERE id=?",
                           [sessionIdentifier, String(taskIdentifier), event.uuidString])
        }
    }

    /// Receipt identity/attempt, durable scope fence and rejected head commit together.
    /// This error does not identify whether the device or a particular binding was removed.
    func rejectAuthorization(_ context: VehicleQueueContext, event: UUID, attempt: UUID) throws {
        do {
            try db.transaction {
                try require(context, active: false)
                let row = try record(context, event)
                guard row.state == .registered, row.attempt == attempt else { throw VehicleQueueError.invalidTransition }
                try db.execute("UPDATE authorization_scopes SET generation=?,state='revoked' WHERE context=?", [UUID().uuidString, context.key])
                try db.execute("UPDATE vehicle_authorizations SET allowed=0 WHERE context=?", [context.key])
                try db.execute("UPDATE events SET state='blocked',reason='authorizationRejected' WHERE id=?", [event.uuidString])
            }
        } catch VehicleQueueError.invalidTransition { throw VehicleQueueError.invalidTransition }
        catch {
            // Same existing fallback as logout. Report failure even when quarantine succeeds.
            try? db.transaction { try db.execute("UPDATE devices SET active=0 WHERE context=?", [context.key]) }
            throw error
        }
    }

    enum AuthorizationStatus { case unknown, pending, authorized, removed, fenced }
    func authorizationStatus(_ context: VehicleQueueContext, vehicle: UUID, namespace: UUID?) throws -> AuthorizationStatus {
        try db.transaction {
            try require(context)
            guard let row = try db.rows("SELECT generation,state,namespace FROM authorization_scopes WHERE context=?", [context.key]).first else { return .unknown }
            guard row[0].flatMap(UUID.init(uuidString:)) != nil else { throw VehicleQueueError.storage }
            switch row[1] {
            case "verificationPending": return .pending
            case "revoked": return .fenced
            case "verified":
                guard let namespace, row[2] == namespace.uuidString else { return .unknown }
                return try db.authorizedVehicles(context).contains(vehicle) ? .authorized : .removed
            default: throw VehicleQueueError.storage
            }
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
            guard let version = try rows("PRAGMA user_version").first?[0], ["0", "1", "2"].contains(version) else {
                throw VehicleQueueError.unsupportedSchema
            }
            try execute("CREATE TABLE IF NOT EXISTS devices(context TEXT PRIMARY KEY,environment TEXT NOT NULL,device TEXT NOT NULL,last_sequence INTEGER NOT NULL CHECK(last_sequence>=0),active INTEGER NOT NULL CHECK(active IN(0,1)),UNIQUE(environment,device))")
            try execute("CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,context TEXT NOT NULL REFERENCES devices(context),sequence INTEGER NOT NULL CHECK(sequence>0),vehicle TEXT NOT NULL,cause TEXT REFERENCES events(id),payload TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('pending','preparing','registered','awaitingAuthentication','accepted','terminal','blocked')),attempt TEXT,session TEXT,task INTEGER,reason TEXT,UNIQUE(context,sequence),UNIQUE(context,cause))")
            try execute("CREATE TABLE IF NOT EXISTS authorization_scopes(context TEXT PRIMARY KEY REFERENCES devices(context),generation TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('verificationPending','verified','revoked')),namespace TEXT)")
            try execute("CREATE TABLE IF NOT EXISTS vehicle_authorizations(context TEXT NOT NULL REFERENCES authorization_scopes(context),vehicle TEXT NOT NULL,allowed INTEGER NOT NULL CHECK(allowed IN(0,1)),PRIMARY KEY(context,vehicle))")
            try execute("PRAGMA user_version=2")
        }
        #if os(iOS)
        try fm.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication], ofItemAtPath: path)
        #endif
    }

    func beginVerification(_ context: VehicleQueueContext) throws -> UUID {
        let generation = UUID()
        try transaction {
            guard try rows("SELECT context FROM devices WHERE context=?", [context.key]).count == 1 else { throw VehicleQueueError.contextUnavailable }
            try execute("INSERT INTO authorization_scopes(context,generation,state) VALUES(?,?,'verificationPending') ON CONFLICT(context) DO UPDATE SET generation=excluded.generation,state=excluded.state", [context.key, generation.uuidString])
        }
        return generation
    }
    func completeVerification(_ context: VehicleQueueContext, generation: UUID, vehicles: Set<UUID>, namespace: UUID? = nil) throws {
        try transaction {
            guard let row = try rows("SELECT generation,state FROM authorization_scopes WHERE context=?", [context.key]).first,
                  row[0] == generation.uuidString, row[1] == "verificationPending",
                  try rows("SELECT active FROM devices WHERE context=?", [context.key]).first?[0] == "1"
            else { throw VehicleQueueError.contextUnavailable }
            try execute("UPDATE vehicle_authorizations SET allowed=0 WHERE context=?", [context.key])
            for vehicle in vehicles {
                try execute("INSERT INTO vehicle_authorizations(context,vehicle,allowed) VALUES(?,?,1) ON CONFLICT(context,vehicle) DO UPDATE SET allowed=1", [context.key, vehicle.uuidString])
            }
            try execute("UPDATE authorization_scopes SET state='verified',namespace=? WHERE context=?", [namespace?.uuidString, context.key])
        }
    }
    func requireNamespace(_ context: VehicleQueueContext, _ namespace: UUID) throws {
        guard try rows("SELECT namespace FROM authorization_scopes WHERE context=? AND state='verified'", [context.key]).first?[0] == namespace.uuidString
        else { throw VehicleQueueError.contextUnavailable }
    }
    func authorizedVehicles(_ context: VehicleQueueContext) throws -> Set<UUID> {
        // One statement gives a consistent snapshot even across independent processes.
        let values = try rows("SELECT a.vehicle,a.allowed,s.generation FROM authorization_scopes s JOIN devices d ON d.context=s.context LEFT JOIN vehicle_authorizations a ON a.context=s.context WHERE s.context=? AND s.state='verified' AND d.active=1", [context.key])
        var result = Set<UUID>()
        for row in values {
            guard row[2].flatMap(UUID.init(uuidString:)) != nil else { throw VehicleQueueError.storage }
            guard let text = row[0] else { continue }
            guard let id = UUID(uuidString: text), row[1] == "0" || row[1] == "1" else { throw VehicleQueueError.storage }
            if row[1] == "1" { result.insert(id) }
        }
        return result
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
