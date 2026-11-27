import Foundation
import SQLite3
#if canImport(Darwin)
import Darwin
#elseif canImport(Glibc)
import Glibc
#endif
#if canImport(OSLog)
import OSLog
#endif

enum DeviceSetupDiagnostics {
    enum Stage: String { case setup, authorization, directory, protection, backup, sqlite, schema, partition, journal, context }
    enum Reason: String { case prepare, bind, step, storage, cancelled, epoch, generation, sessionMissing, owner, inactive, user, family, resolution, creation, attributes, exclusion, opening, initialization, unsupported, invalid, reading, decoding, mismatch, denyBindings, invalidation }
    enum Code: Int { case unspecified=0, missing=1, denied=2, diskFull=3, readOnly=4, io=5 }
    static func code(_ error: Error) -> Code {
        let value=error as NSError
        if value.domain == NSCocoaErrorDomain {
            switch value.code { case 4,260: return .missing; case 257,513: return .denied; case 640: return .diskFull; default: return .unspecified }
        }
        if value.domain == NSPOSIXErrorDomain {
            switch value.code { case 2: return .missing; case 1,13: return .denied; case 28: return .diskFull; case 30: return .readOnly; case 5: return .io; default: return .unspecified }
        }
        return .unspecified
    }
    static func emit(_ stage: Stage, _ reason: Reason, code: Code = .unspecified) {
        #if canImport(OSLog)
        Logger(subsystem: "com.familycaragent.device", category: "setup")
            .error("FCA_DEVICE_SETUP stage=\(stage.rawValue, privacy: .public) reason=\(reason.rawValue, privacy: .public) code=\(code.rawValue, privacy: .public)")
        #endif
    }
    #if FCA_SQLITE_CHECKS
    nonisolated(unsafe) static var sqliteObserver: ((Reason, Int32) -> Void)?
    #endif
    static func sqlite(_ reason: Reason, _ raw: Int32) {
        let primary=raw & 0xff
        let bounded: Int32 = (1...28).contains(primary) ? primary : 0
        #if FCA_SQLITE_CHECKS
        sqliteObserver?(reason,bounded)
        #endif
        #if canImport(OSLog)
        Logger(subsystem:"com.familycaragent.device",category:"setup")
            .error("FCA_DEVICE_SETUP stage=sqlite reason=\(reason.rawValue,privacy:.public) sqlite_code=\(bounded,privacy:.public)")
        #endif
    }
    static func check<T>(_ stage: Stage, _ reason: Reason, _ body: () throws -> T) throws -> T {
        do { return try body() } catch { emit(stage, reason, code:code(error)); throw error }
    }
}


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

enum ShortcutQueueError: Error { case contextChanged, location, alreadyTaken, noUniqueTake, legacyReturn, recoveryBlocked, locationExpired, retryStored }

enum ReturnRecoveryPolicy {
    static func shortcutFailure(_ task: VehicleRecoveryRecord) -> ShortcutQueueError? {
        if task.reason == "RETURN_RECOVERY_LEGACY_UNVERIFIED" { return .legacyReturn }
        if task.state == .blocked {
            if ["RETURN_RECOVERY_VERIFICATION_EXPIRED", "RETURN_RECONCILIATION_VERIFICATION_EXPIRED"].contains(task.reason) { return .locationExpired }
            return .recoveryBlocked
        }
        if task.reason == "deliveryUnknown" || task.state == .awaitingAuthentication { return .retryStored }
        return nil
    }
    static let homeCodes: Set<String> = ["RETURN_HOME_UNAVAILABLE", "RETURN_OUTSIDE_HOME"]
    static let renewable: Set<String> = homeCodes.union(["RETURN_RECOVERY_VERIFICATION_EXPIRED"])
}

struct VehicleRecoveryRecord: Sendable {
    let id: UUID
    let event: UUID
    let payload: Data
    let state: VehicleQueueState
    let session: String?
    let task: Int64?
    let reason: String?
    var reconciliation: Bool = false
}

struct TakeMetadataReference: Codable, Equatable, Sendable {
    let event_id: UUID
    let device_sequence: Int64
    let vehicle_ref: UUID
}
struct TakeMetadataRequest: Codable, Sendable {
    let request_id: UUID
    let takes: [TakeMetadataReference]
}
struct TakeMetadataBatch: Sendable {
    let request: TakeMetadataRequest
    let authorization: String
}
struct TakeSessionMetadata: Codable, Equatable, Sendable {
    let event_id: UUID
    let device_sequence: Int64
    let vehicle_ref: UUID
    let status: String
    let anchor_event_id: UUID?
    let session_ref: UUID?
    let session_state: String?
    let closed_at: String?
    let closure_kind: String?
    let reconciliation_operation_id: UUID?
    let finality: String?
}
struct TakeMetadataSnapshot: Codable, Sendable {
    let request_id: UUID
    let device_ref: UUID
    let projection_revision: Int64
    let last_processed_sequence: Int64
    let observed_at: String
    let items: [TakeSessionMetadata]
}

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

struct VehicleReturnPreparation: Sendable, Equatable {
    let context: VehicleQueueContext
    let vehicle: UUID
    let namespace: UUID
    fileprivate let snapshot: VehicleReturnIdentity
}

fileprivate struct VehicleReturnIdentity: Sendable, Equatable {
    let authorization: [String?]
    let take: QueuedVehicleEvent
    let anchor: UUID?
    let session: UUID?
    let rejectedReturn: QueuedVehicleEvent?
    let rejection: String?
    let recoveryEligibility: String

    func permits(_ current: Self) -> Bool {
        guard authorization == current.authorization, take == current.take,
              rejectedReturn == current.rejectedReturn, rejection == current.rejection,
              recoveryEligibility == current.recoveryEligibility else { return false }
        if let anchor {
            return current.anchor == anchor && current.session == session
        }
        // Newly resolved self-anchor proves the original TAKE remains the session's
        // cause. Mapping an unknown TAKE to some older session is not that proof.
        return current.anchor == nil || current.anchor == take.id
    }
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

/// Shared with normal uploads: recovery embeds exactly the same original wire evidence.
enum VehicleEventWire {
    static func encode(_ event: QueuedVehicleEvent) throws -> Data {
        var body: [String: Any] = ["event_id": event.id.uuidString, "vehicle_ref": event.vehicle.uuidString,
                                   "device_sequence": event.sequence, "occurred_at": timestamp(event.occurredAt)]
        if event.kind == .returning {
            guard let cause = event.takeID, let location = event.location else { throw VehicleQueueError.invalidInput }
            body["take_event_id"] = cause.uuidString; body["latitude"] = location.latitude
            body["longitude"] = location.longitude; body["accuracy_m"] = location.accuracy
            body["location_at"] = timestamp(location.measuredAt)
        }
        return try JSONSerialization.data(withJSONObject: body, options: [.sortedKeys])
    }
    static func recovery(_ event: QueuedVehicleEvent, id: UUID, at time: Date, location: VehicleLocationEvidence, reconciliation: Bool = false) throws -> Data {
        try location.validate(at: time)
        guard time >= event.occurredAt else { throw ShortcutQueueError.location }
        return try JSONSerialization.data(withJSONObject: [
            (reconciliation ? "reconciliation_id" : "recovery_id"): id.uuidString,
            "original_return": JSONSerialization.jsonObject(with: encode(event)),
            "verification": ["invoked_at": timestamp(time), "location_at": timestamp(location.measuredAt),
                             "latitude": location.latitude, "longitude": location.longitude, "accuracy_m": location.accuracy]
        ], options: [.sortedKeys])
    }
    private static func timestamp(_ date: Date) -> String {
        let value = date.timeIntervalSince1970, seconds = floor(value)
        let formatter = ISO8601DateFormatter()
        let base = formatter.string(from: Date(timeIntervalSince1970: seconds)).dropLast()
        return String(base) + String(format: ".%09dZ", Int((value - seconds) * 1_000_000_000))
    }
}

/// One connection per actor; BEGIN IMMEDIATE also serializes separate queue instances/processes.
actor VehicleEventQueue {
    nonisolated let directory: URL
    private let db: VehicleQueueDatabase

    #if FCA_DELETION_APPLE_CHECKS
    nonisolated(unsafe) static var testDirectory: URL?
    #endif
    static func applicationDirectory() throws -> URL {
        #if FCA_DELETION_APPLE_CHECKS
        guard let root=testDirectory else { throw VehicleQueueError.storage }
        return root
        #else
        try DeviceSetupDiagnostics.check(.directory, .resolution) {
            try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                    appropriateFor: nil, create: true).appendingPathComponent("VehicleEventQueue", isDirectory: true)
        }
        #endif
    }

    init(directory: URL) throws { self.directory=directory; db = try DeviceSetupDiagnostics.check(.sqlite, .initialization) { try VehicleQueueDatabase(directory: directory) } }

    nonisolated static func withAccount<T>(directory: URL, environment: String, owner: UUID, _ body: () throws -> T) throws -> T {
        let db = try VehicleQueueDatabase(directory: directory)
        return try db.transaction {
            guard try db.rows("SELECT 1 FROM deleted_accounts WHERE environment=? AND owner=?", [environment, owner.uuidString]).isEmpty else { throw VehicleQueueError.contextUnavailable }
            return try body()
        }
    }

    nonisolated static func fenceDeletionUploads(directory: URL, environment: String, owner: UUID, bundle: String) throws -> [String] {
        let db=try VehicleQueueDatabase(directory:directory)
        try db.transaction { try db.execute("INSERT OR IGNORE INTO deleted_accounts(environment,owner) VALUES(?,?)",[environment,owner.uuidString]) }
        let prefix=environment + "|" + owner.uuidString + "|"
        var identifiers=Set<String>()
        for row in try db.rows("SELECT context FROM devices WHERE environment=?",[environment]) {
            guard let key=row[0], key.hasPrefix(prefix) else { continue }
            let parts=String(key.dropFirst(environment.count+1)).split(separator:"|")
            guard parts.count==4, UUID(uuidString:String(parts[0]))==owner,
                  Int64(parts[1]) != nil, Int64(parts[2]) != nil, UUID(uuidString:String(parts[3])) != nil else { throw VehicleQueueError.storage }
            identifiers.insert(bundle + ".vehicle-sync.v1." + parts.joined(separator:"."))
        }
        let sessionPrefix=bundle + ".vehicle-sync.v1." + owner.uuidString + "."
        for url in try FileManager.default.contentsOfDirectory(at:directory,includingPropertiesForKeys:nil) where url.lastPathComponent.hasPrefix(sessionPrefix) {
            guard url.lastPathComponent.count<256 else { throw VehicleQueueError.storage }
            identifiers.insert(url.lastPathComponent)
        }
        return identifiers.sorted()
    }

    nonisolated static func synchronizeDirectory(_ directory: URL) throws {
        #if canImport(Darwin) || canImport(Glibc)
        let descriptor=open(directory.path,O_RDONLY)
        guard descriptor>=0 else { throw VehicleQueueError.storage }
        defer { _ = close(descriptor) }
        guard fsync(descriptor)==0 else { throw VehicleQueueError.storage }
        #else
        throw VehicleQueueError.storage
        #endif
    }

    nonisolated static func isDeleted(directory: URL, environment: String, owner: UUID) throws -> Bool {
        let db = try VehicleQueueDatabase(directory:directory)
        return try !db.rows("SELECT 1 FROM deleted_accounts WHERE environment=? AND owner=?",[environment,owner.uuidString]).isEmpty
    }
    nonisolated static func withLiveOwners<T>(directory: URL, environment: String, owners: Set<UUID>, _ body: (Set<UUID>) throws -> T) throws -> T {
        let db=try VehicleQueueDatabase(directory:directory)
        return try db.transaction {
            let deleted=Set(try db.rows("SELECT owner FROM deleted_accounts WHERE environment=?",[environment]).compactMap { $0[0].flatMap(UUID.init(uuidString:)) })
            return try body(owners.subtracting(deleted))
        }
    }
    nonisolated static func withCleanupLock<T>(directory: URL, _ body: () throws -> T) throws -> T {
        try VehicleQueueDatabase(directory:directory).transaction(body)
    }

    /// Caller must have durably stored an authoritative completion receipt first.
    /// File removal is inside the same exclusion lock and BEFORE relational deletion;
    /// a rollback leaves the source inventory available for a safe retry.
    nonisolated static func cleanupDeletedAccount(directory: URL, environment: String, owner: UUID,
                                                   removeFiles: () throws -> Void) throws {
        let db = try VehicleQueueDatabase(directory: directory)
        // Commit the fence independently. Failure later must never reopen this account.
        try db.transaction {
            try db.execute("INSERT OR IGNORE INTO deleted_accounts(environment,owner) VALUES(?,?)", [environment,owner.uuidString])
        }
        try db.transaction {
            try removeFiles()
            let prefix = environment + "|" + owner.uuidString + "|"
            let keys = try db.rows("SELECT context FROM devices WHERE environment=?", [environment]).compactMap { $0[0] }.filter { $0.hasPrefix(prefix) }
            for key in keys {
                for table in ["take_session_metadata", "session_metadata_sync", "vehicle_authorizations", "authorization_scopes"] {
                    try db.execute("DELETE FROM \(table) WHERE context=?", [key])
                }
                for table in ["return_recoveries", "return_reconciliations"] {
                    try db.execute("DELETE FROM \(table) WHERE event IN (SELECT id FROM events WHERE context=?)", [key])
                }
                try db.execute("DELETE FROM events WHERE context=?", [key])
                try db.execute("DELETE FROM devices WHERE context=?", [key])
            }
        }
        // Rebuild live pages to discard prior freelist remnants as well. No sequence reset
        // or database deletion. A busy/full-disk failure leaves cleanup pending for retry.
        try db.execute("VACUUM")
    }

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
        else { DeviceSetupDiagnostics.emit(.partition, .invalid); throw VehicleQueueError.contextUnavailable }
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

    private func openShortcutTakes(_ context: VehicleQueueContext, vehicle: UUID) throws -> [VehicleQueueRecord] {
        let rows = try records(context).filter { $0.event.vehicle == vehicle }
        let paired = Set(rows.compactMap { $0.event.takeID })
        let metadata = try currentTakeMetadata(context)
        // A local RETURN after several accepted aliases pairs their one logical session.
        // Never apply this to pending/uncertain TAKEs or aliases queued after that RETURN.
        var returnedAnchors: [UUID:Int64] = [:]
        for row in rows where row.event.kind == .returning && row.state != .terminal {
            if let cause = row.event.takeID, let anchor = metadata[cause]?.anchor_event_id {
                returnedAnchors[anchor] = max(returnedAnchors[anchor] ?? 0, row.event.sequence)
            }
        }
        var sessions = Set<UUID>()
        let open = rows.filter { row in
            guard row.event.kind == .take, row.state != .terminal, !paired.contains(row.event.id) else { return false }
            // Only this exact accepted event may use an authoritative snapshot.
            if row.state == .accepted, let m = metadata[row.event.id] {
                if m.session_state == "closed" { return false }
                if let anchor = m.anchor_event_id {
                    if let returned = returnedAnchors[anchor], returned > row.event.sequence { return false }
                    return sessions.insert(anchor).inserted
                }
            }
            return true
        }
        return open
    }

    private func returnSnapshot(_ context: VehicleQueueContext, vehicle: UUID, namespace: UUID) throws -> VehicleReturnIdentity {
        try require(context)
        try db.requireNamespace(context, namespace)
        guard try db.authorizedVehicles(context).contains(vehicle),
              let authorization = try db.rows("SELECT generation,state,namespace FROM authorization_scopes WHERE context=?", [context.key]).first
        else { throw ShortcutQueueError.contextChanged }
        let rows = try records(context).filter { $0.event.vehicle == vehicle }
        let take: VehicleQueueRecord
        var rejectedEvent: QueuedVehicleEvent?
        var rejection: String?
        var eligibility = "normal"
        if let rejected = rows.first(where: { $0.event.kind == .returning && $0.state == .blocked }) {
            guard rejected.reason != Failure.preAdmissionRejection.rawValue else { throw ShortcutQueueError.legacyReturn }
            guard let reason = rejected.reason, ReturnRecoveryPolicy.homeCodes.contains(reason),
                  try records(context).first(where: { $0.state != .accepted && $0.state != .terminal })?.event.id == rejected.event.id,
                  let cause = rows.first(where: { $0.event.id == rejected.event.takeID && $0.event.kind == .take })
            else { throw ShortcutQueueError.recoveryBlocked }
            take = cause; rejectedEvent = rejected.event; rejection = reason
            eligibility = "new_recovery"
            if let previous = try recovery(context, event: rejected.event.id) {
                if previous.state == .blocked {
                    if previous.reason == "RETURN_RECOVERY_LEGACY_UNVERIFIED" { throw ShortcutQueueError.legacyReturn }
                    let renewable = ReturnRecoveryPolicy.renewable.union(["RETURN_RECOVERY_ORDER_CONFLICT", "RETURN_RECONCILIATION_VERIFICATION_EXPIRED"])
                    guard let reason = previous.reason, renewable.contains(reason) else { throw ShortcutQueueError.recoveryBlocked }
                    eligibility = "renew|\(previous.id)|\(previous.reconciliation)|\(reason)"
                } else {
                    guard previous.state != .accepted else { throw ShortcutQueueError.contextChanged }
                    // Transport mapping/retries do not change the immutable attempt being resumed.
                    eligibility = "resume|\(previous.id)|\(previous.reconciliation)"
                }
            }
        } else {
            let open = try openShortcutTakes(context, vehicle: vehicle)
            guard open.count == 1 else { throw ShortcutQueueError.noUniqueTake }
            take = open[0]
        }
        guard take.state != .terminal, take.state != .blocked else { throw ShortcutQueueError.contextChanged }
        let metadata = try currentTakeMetadata(context)
        let m = take.state == .accepted ? metadata[take.event.id] : nil
        guard m?.session_state != "closed" else { throw ShortcutQueueError.contextChanged }
        return .init(authorization: authorization, take: take.event, anchor: m?.anchor_event_id,
                     session: m?.session_ref, rejectedReturn: rejectedEvent, rejection: rejection,
                     recoveryEligibility: eligibility)
    }

    func prepareReturn(_ context: VehicleQueueContext, vehicle: UUID, namespace: UUID) throws -> VehicleReturnPreparation {
        try db.transaction {
            .init(context: context, vehicle: vehicle, namespace: namespace,
                  snapshot: try returnSnapshot(context, vehicle: vehicle, namespace: namespace))
        }
    }

    func commitReturn(_ preparation: VehicleReturnPreparation, time: Date? = nil, location: VehicleLocationEvidence,
                      permit: VehicleRecordingPermit) throws -> QueuedVehicleEvent {
        try permit.record {
            try Task.checkCancellation()
            return try enqueue(preparation.context, id: UUID(), vehicle: preparation.vehicle, occurredAt: time ?? Date(),
                        takeID: nil, location: location, shortcut: .returning, namespace: preparation.namespace,
                        preparation: preparation, nativeRecordingTime: time == nil)
        }
    }

    private func enqueue(_ context: VehicleQueueContext, id: UUID, vehicle: UUID, occurredAt: Date,
                         takeID: UUID?, location: VehicleLocationEvidence?, shortcut: QueuedVehicleEvent.Kind? = nil, namespace: UUID? = nil, preparation: VehicleReturnPreparation? = nil, nativeRecordingTime: Bool = false) throws -> QueuedVehicleEvent {
        guard id.uuidString.split(separator: "-")[2].first == "4",
              occurredAt.timeIntervalSince1970.isFinite,
              (0...253402300799).contains(occurredAt.timeIntervalSince1970)
        else { throw VehicleQueueError.invalidInput }
        do { try location?.validate(at: occurredAt) }
        catch { if preparation != nil { throw ShortcutQueueError.location }; throw error }
        return try db.transaction {
            // Read the final clock only after acquiring the cross-process SQLite write lock.
            let occurredAt = nativeRecordingTime ? Date() : occurredAt
            if preparation != nil { try Task.checkCancellation() }
            do { try location?.validate(at: occurredAt) }
            catch { if preparation != nil { throw ShortcutQueueError.location }; throw error }
            try require(context)
            guard try db.authorizedVehicles(context).contains(vehicle) else { throw VehicleQueueError.contextUnavailable }
            if let namespace { try db.requireNamespace(context, namespace) }
            if let preparation {
                guard try preparation.snapshot.permits(returnSnapshot(context, vehicle: vehicle, namespace: preparation.namespace))
                else { throw ShortcutQueueError.contextChanged }
            }
            var takeID = takeID
            if let shortcut {
                let rows = try records(context).filter { $0.event.vehicle == vehicle }
                if shortcut == .returning, let rejected = rows.first(where: {
                    $0.event.kind == .returning && $0.state == .blocked
                }) {
                    guard rejected.reason != Failure.preAdmissionRejection.rawValue else { throw ShortcutQueueError.legacyReturn }
                    guard let reason = rejected.reason, ReturnRecoveryPolicy.homeCodes.contains(reason),
                          try records(context).first(where: { $0.state != .accepted && $0.state != .terminal })?.event.id == rejected.event.id
                    else { throw ShortcutQueueError.recoveryBlocked }
                    var reconciliation = false
                    if let previous = try recovery(context, event: rejected.event.id) {
                        if previous.state != .blocked { return rejected.event }
                        if previous.reason == "RETURN_RECOVERY_LEGACY_UNVERIFIED" { throw ShortcutQueueError.legacyReturn }
                        reconciliation = previous.reconciliation || previous.reason == "RETURN_RECOVERY_ORDER_CONFLICT"
                        let renewable = ReturnRecoveryPolicy.renewable.union(["RETURN_RECOVERY_ORDER_CONFLICT", "RETURN_RECONCILIATION_VERIFICATION_EXPIRED"])
                        guard let reason = previous.reason, renewable.contains(reason)
                        else { throw ShortcutQueueError.recoveryBlocked }
                    }
                    guard let location else { throw ShortcutQueueError.location }
                    let recoveryID = UUID()
                    let bytes = try VehicleEventWire.recovery(rejected.event, id: recoveryID, at: occurredAt, location: location, reconciliation: reconciliation)
                    let table = reconciliation ? "return_reconciliations" : "return_recoveries"
                    try db.execute("INSERT INTO \(table)(id,event,payload,state) VALUES(?,?,?,'preparing')",
                                   [recoveryID.uuidString, rejected.event.id.uuidString, String(decoding: bytes, as: UTF8.self)])
                    return rejected.event // No sequence allocation or original evidence mutation.
                }
                let open = try openShortcutTakes(context, vehicle: vehicle)
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

    func recordFailure(_ context: VehicleQueueContext, event: UUID, attempt: UUID, failure: Failure, rejectionCode: String? = nil) throws {
        try db.transaction {
            try require(context)
            let row = try record(context, event)
            guard [.preparing, .registered].contains(row.state), row.attempt == attempt else {
                throw VehicleQueueError.invalidTransition
            }
            let code = failure == .preAdmissionRejection && row.event.kind == .returning
                ? rejectionCode.flatMap { ReturnRecoveryPolicy.homeCodes.contains($0) ? $0 : nil } : nil
            try db.execute("UPDATE events SET state=?,reason=? WHERE id=?",
                           [failure == .authentication ? "awaitingAuthentication" : "blocked", code ?? failure.rawValue, event.uuidString])
        }
    }

    func recovery(_ context: VehicleQueueContext, event: UUID) throws -> VehicleRecoveryRecord? {
        _ = try record(context, event)
        let reconciliationRows = try db.rows("SELECT id,payload,state,session,task,reason FROM return_reconciliations WHERE event=? ORDER BY rowid DESC LIMIT 1", [event.uuidString])
        let reconciliation = !reconciliationRows.isEmpty
        let table = reconciliation ? "return_reconciliations" : "return_recoveries"
        guard let r = try db.rows("SELECT id,payload,state,session,task,reason FROM \(table) WHERE event=? ORDER BY rowid DESC LIMIT 1", [event.uuidString]).first else { return nil }
        guard let id = r[0].flatMap(UUID.init(uuidString:)), let payload = r[1],
              let state = r[2].flatMap(VehicleQueueState.init(rawValue:)),
              r[4] == nil || r[4].flatMap(Int64.init) != nil else { throw VehicleQueueError.storage }
        return .init(id: id, event: event, payload: Data(payload.utf8), state: state,
                     session: r[3], task: r[4].flatMap(Int64.init), reason: r[5], reconciliation: reconciliation)
    }

    /// Called only after transport task reconciliation. Identity/payload never change.
    func updateRecovery(_ context: VehicleQueueContext, event: UUID, id: UUID,
                        state: VehicleQueueState, session: String? = nil, task: Int64? = nil, reason: String? = nil, acknowledgment: String? = nil) throws {
        try db.transaction {
            try require(context)
            let row = try record(context, event)
            guard row.state == .blocked, let old = try recovery(context, event: event), old.id == id,
                  [.preparing, .registered, .awaitingAuthentication].contains(old.state),
                  [.preparing, .registered, .awaitingAuthentication, .blocked, .accepted].contains(state),
                  try db.authorizedVehicles(context).contains(row.event.vehicle) else { throw VehicleQueueError.invalidTransition }
            guard state != .registered || (session != nil && task != nil) else { throw VehicleQueueError.invalidInput }
            guard state != .registered || old.state != .registered || (old.session == session && old.task == task)
            else { throw VehicleQueueError.invalidTransition }
            let table = old.reconciliation ? "return_reconciliations" : "return_recoveries"
            try db.execute("UPDATE \(table) SET state=?,session=?,task=?,reason=? WHERE id=?",
                           [state.rawValue, session, task.map(String.init), reason, id.uuidString])
            if state == .accepted {
                if old.reconciliation {
                    guard let acknowledgment else { throw VehicleQueueError.invalidInput }
                    try db.execute("UPDATE return_reconciliations SET acknowledgment=? WHERE id=?", [acknowledgment, id.uuidString])
                }
                try db.execute("UPDATE events SET state=?,reason=? WHERE id=?",
                    [old.reconciliation ? "terminal" : "accepted", old.reconciliation ? "resolved_current_state" : "accepted", event.uuidString])
            }
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

    private static func metadataDate(_ value: String) -> Date? {
        let formatter=ISO8601DateFormatter()
        formatter.formatOptions=[.withInternetDateTime,.withFractionalSeconds]
        if let date=formatter.date(from:value) { return date }
        formatter.formatOptions=[.withInternetDateTime]
        return formatter.date(from:value)
    }

    /// Bounded rotating backfill. Snapshot I/O is never part of Shortcut eligibility.
    func metadataBatch(_ context: VehicleQueueContext, excluding: Set<UUID> = []) throws -> TakeMetadataBatch? {
        try require(context)
        guard let scope = try db.rows("SELECT generation FROM authorization_scopes WHERE context=? AND state='verified'", [context.key]).first?[0] else { return nil }
        let allowed = try db.authorizedVehicles(context)
        let records = try records(context)
        let paired = Set(records.compactMap { $0.event.takeID })
        let metadata = try currentTakeMetadata(context)
        let all = records.filter { $0.state == .accepted && $0.event.kind == .take && allowed.contains($0.event.vehicle) && !excluding.contains($0.event.id) }
        func blocks(_ row: VehicleQueueRecord) -> Bool {
            !paired.contains(row.event.id) && metadata[row.event.id]?.session_state != "closed"
        }
        let refreshed = try db.rows("SELECT event,refresh_order FROM take_session_metadata WHERE context=?", [context.key])
        let order = Dictionary(uniqueKeysWithValues: refreshed.compactMap { r -> (UUID, Int64)? in
            guard let id = r[0].flatMap(UUID.init(uuidString:)), let n = r[1].flatMap(Int64.init) else { return nil }; return (id,n)
        })
        let selected = all.sorted { a,b in
            if blocks(a) != blocks(b) { return blocks(a) }
            let x=order[a.event.id] ?? -1, y=order[b.event.id] ?? -1
            return x == y ? a.event.sequence < b.event.sequence : x < y
        }.prefix(64)
        guard !selected.isEmpty else { return nil }
        return .init(request: .init(request_id: UUID(), takes: selected.map { .init(event_id:$0.event.id,device_sequence:$0.event.sequence,vehicle_ref:$0.event.vehicle) }), authorization: scope)
    }

    func applyMetadata(_ context: VehicleQueueContext, batch: TakeMetadataBatch, snapshot: TakeMetadataSnapshot) throws {
        try db.transaction {
            try require(context)
            guard let scope = try db.rows("SELECT generation FROM authorization_scopes WHERE context=? AND state='verified'", [context.key]).first?[0], scope == batch.authorization,
                  snapshot.request_id == batch.request.request_id, snapshot.device_ref == context.device,
                  snapshot.projection_revision >= 0, snapshot.last_processed_sequence >= 0,
                  snapshot.items.count == batch.request.takes.count, (1...64).contains(snapshot.items.count),
                  Set(snapshot.items.map(\.event_id)).count == snapshot.items.count,
                  Self.metadataDate(snapshot.observed_at) != nil else { throw VehicleQueueError.invalidInput }
            let prior = try db.rows("SELECT revision,refresh_order,observed_at FROM session_metadata_sync WHERE context=?", [context.key]).first
            let revision = prior?[0].flatMap(Int64.init) ?? -1
            guard snapshot.projection_revision >= revision else { throw VehicleQueueError.conflict }
            // Server observation time, never the phone clock. BEGIN IMMEDIATE serializes
            // this comparison and all writes across app/Shortcut SQLite connections.
            if snapshot.projection_revision == revision, let previous = prior?[2],
               let oldTime = Self.metadataDate(previous), let newTime = Self.metadataDate(snapshot.observed_at) {
                guard newTime >= oldTime else { throw VehicleQueueError.conflict }
                if newTime == oldTime {
                    for item in snapshot.items {
                        guard let bytes = try db.rows("SELECT payload FROM take_session_metadata WHERE context=? AND event=?", [context.key,item.event_id.uuidString]).first?[0],
                              try JSONDecoder().decode(TakeSessionMetadata.self,from:Data(bytes.utf8)) == item else { throw VehicleQueueError.conflict }
                    }
                    return // Exact duplicate only; ambiguous ties never change evidence/cache.
                }
            }
            let serial = (prior?[1].flatMap(Int64.init) ?? 0)
            guard serial < Int64.max else { throw VehicleQueueError.storage }
            let allowed = try db.authorizedVehicles(context)
            for item in snapshot.items {
                guard let ref = batch.request.takes.first(where: { $0.event_id == item.event_id }),
                      ref.device_sequence == item.device_sequence, ref.vehicle_ref == item.vehicle_ref,
                      allowed.contains(item.vehicle_ref) else { throw VehicleQueueError.invalidInput }
                let row = try record(context,item.event_id)
                guard row.state == .accepted, row.event.kind == .take,
                      row.event.sequence == item.device_sequence, row.event.vehicle == item.vehicle_ref,
                      snapshot.last_processed_sequence >= item.device_sequence else { throw VehicleQueueError.invalidInput }
                if item.status == "accepted" {
                    guard item.anchor_event_id != nil, item.session_ref != nil,
                          ["open","closed"].contains(item.session_state), ["provisional","finalized"].contains(item.finality) else { throw VehicleQueueError.invalidInput }
                    if item.session_state == "closed" {
                        guard let date = item.closed_at, Self.metadataDate(date) != nil,
                              ["return","handover","vehicle_switch","account_deletion","current_state_reconciliation"].contains(item.closure_kind),
                              item.closure_kind != "current_state_reconciliation" || item.reconciliation_operation_id != nil else { throw VehicleQueueError.invalidInput }
                    } else {
                        guard item.closed_at == nil, item.closure_kind == nil, item.reconciliation_operation_id == nil, item.finality == "provisional" else { throw VehicleQueueError.invalidInput }
                    }
                } else {
                    guard item.status == "unavailable", item.anchor_event_id == nil, item.session_ref == nil,
                          item.session_state == nil, item.closed_at == nil, item.closure_kind == nil,
                          item.reconciliation_operation_id == nil, item.finality == nil else { throw VehicleQueueError.invalidInput }
                }
                let payload=String(decoding: try JSONEncoder().encode(item),as:UTF8.self)
                try db.execute("INSERT INTO take_session_metadata(context,event,authorization,revision,payload,refresh_order) VALUES(?,?,?,?,?,?) ON CONFLICT(context,event) DO UPDATE SET authorization=excluded.authorization,revision=excluded.revision,payload=excluded.payload,refresh_order=excluded.refresh_order",
                    [context.key,item.event_id.uuidString,scope,String(snapshot.projection_revision),payload,String(serial+1)])
            }
            try db.execute("INSERT INTO session_metadata_sync(context,revision,refresh_order,observed_at) VALUES(?,?,?,?) ON CONFLICT(context) DO UPDATE SET revision=excluded.revision,refresh_order=excluded.refresh_order,observed_at=excluded.observed_at", [context.key,String(snapshot.projection_revision),String(serial+1),snapshot.observed_at])
        }
    }

    private func currentTakeMetadata(_ context: VehicleQueueContext) throws -> [UUID:TakeSessionMetadata] {
        let rows = try db.rows("SELECT m.payload,m.revision,s.revision FROM take_session_metadata m JOIN session_metadata_sync s ON s.context=m.context JOIN authorization_scopes a ON a.context=m.context AND a.generation=m.authorization AND a.state='verified' WHERE m.context=?",[context.key])
        var result: [UUID:TakeSessionMetadata] = [:]
        for row in rows {
            guard let payload=row[0], let item=try? JSONDecoder().decode(TakeSessionMetadata.self,from:Data(payload.utf8)), item.status == "accepted" else { continue }
            if row[1] == row[2] || item.finality == "finalized" { result[item.event_id]=item }
        }
        return result
    }

    private func require(_ context: VehicleQueueContext, active: Bool = true) throws {
        guard try db.rows("SELECT 1 FROM deleted_accounts WHERE environment=? AND owner=?", [context.environment,context.owner.uuidString]).isEmpty else { throw VehicleQueueError.contextUnavailable }
        guard let row = try db.rows("SELECT active FROM devices WHERE context=?", [context.key]).first,
              !active || row[0] == "1" else { throw VehicleQueueError.contextUnavailable }
    }

    private func record(_ context: VehicleQueueContext, _ id: UUID) throws -> VehicleQueueRecord {
        guard let row = try records(context).first(where: { $0.event.id == id }) else { throw VehicleQueueError.conflict }
        return row
    }
}

/// Never escapes its owning actor after initialization. Errors intentionally omit SQL/data.
final class VehicleQueueDatabase: @unchecked Sendable {
    private let handle: OpaquePointer

    init(directory: URL) throws {
        guard directory.isFileURL else { throw VehicleQueueError.invalidInput }
        let fm = FileManager.default
        try DeviceSetupDiagnostics.check(.directory, .creation) { try fm.createDirectory(at: directory, withIntermediateDirectories: true) }
        #if os(iOS)
        try DeviceSetupDiagnostics.check(.protection, .attributes) { try fm.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication], ofItemAtPath: directory.path) }
        var root = directory
        var values = URLResourceValues(); values.isExcludedFromBackup = true
        try DeviceSetupDiagnostics.check(.backup, .exclusion) { try root.setResourceValues(values) }
        #endif
        var pointer: OpaquePointer?
        let path = directory.appendingPathComponent("vehicle-events.sqlite").path
        guard sqlite3_open_v2(path, &pointer, SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX, nil) == SQLITE_OK,
              let pointer else {
            DeviceSetupDiagnostics.emit(.sqlite, .opening)
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
        try execute("PRAGMA fullfsync=ON")
        try execute("PRAGMA secure_delete=ON")
        try transaction {
            guard let version = try rows("PRAGMA user_version").first?[0], ["0", "1", "2", "3", "4", "5", "6"].contains(version) else {
                DeviceSetupDiagnostics.emit(.schema, .unsupported)
                throw VehicleQueueError.unsupportedSchema
            }
            try execute("CREATE TABLE IF NOT EXISTS devices(context TEXT PRIMARY KEY,environment TEXT NOT NULL,device TEXT NOT NULL,last_sequence INTEGER NOT NULL CHECK(last_sequence>=0),active INTEGER NOT NULL CHECK(active IN(0,1)),UNIQUE(environment,device))")
            try execute("CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,context TEXT NOT NULL REFERENCES devices(context),sequence INTEGER NOT NULL CHECK(sequence>0),vehicle TEXT NOT NULL,cause TEXT REFERENCES events(id),payload TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('pending','preparing','registered','awaitingAuthentication','accepted','terminal','blocked')),attempt TEXT,session TEXT,task INTEGER,reason TEXT,UNIQUE(context,sequence),UNIQUE(context,cause))")
            try execute("CREATE TABLE IF NOT EXISTS authorization_scopes(context TEXT PRIMARY KEY REFERENCES devices(context),generation TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('verificationPending','verified','revoked')),namespace TEXT)")
            try execute("CREATE TABLE IF NOT EXISTS vehicle_authorizations(context TEXT NOT NULL REFERENCES authorization_scopes(context),vehicle TEXT NOT NULL,allowed INTEGER NOT NULL CHECK(allowed IN(0,1)),PRIMARY KEY(context,vehicle))")
            try execute("CREATE TABLE IF NOT EXISTS return_recoveries(id TEXT PRIMARY KEY,event TEXT NOT NULL REFERENCES events(id),payload TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('preparing','registered','awaitingAuthentication','blocked','accepted')),session TEXT,task INTEGER,reason TEXT)")
            try execute("CREATE UNIQUE INDEX IF NOT EXISTS return_recovery_active ON return_recoveries(event) WHERE state IN('preparing','registered','awaitingAuthentication')")
            try execute("CREATE TRIGGER IF NOT EXISTS return_recovery_immutable BEFORE UPDATE OF id,event,payload ON return_recoveries BEGIN SELECT RAISE(ABORT,'immutable recovery'); END")
            try execute("CREATE TABLE IF NOT EXISTS return_reconciliations(id TEXT PRIMARY KEY,event TEXT NOT NULL REFERENCES events(id),payload TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('preparing','registered','awaitingAuthentication','blocked','accepted')),session TEXT,task INTEGER,reason TEXT,acknowledgment TEXT)")
            try execute("CREATE UNIQUE INDEX IF NOT EXISTS return_reconciliation_active ON return_reconciliations(event) WHERE state IN('preparing','registered','awaitingAuthentication')")
            try execute("CREATE TRIGGER IF NOT EXISTS return_reconciliation_immutable BEFORE UPDATE OF id,event,payload ON return_reconciliations BEGIN SELECT RAISE(ABORT,'immutable reconciliation'); END")
            // Enforce cross-table exclusion even across separate App Intent processes.
            for (table, other) in [("return_reconciliations", "return_recoveries"), ("return_recoveries", "return_reconciliations")] {
                for action in ["INSERT", "UPDATE"] {
                    try execute("CREATE TRIGGER IF NOT EXISTS \(table)_exclusive_\(action) BEFORE \(action) ON \(table) WHEN NEW.state IN('preparing','registered','awaitingAuthentication') AND EXISTS(SELECT 1 FROM \(other) WHERE event=NEW.event AND state IN('preparing','registered','awaitingAuthentication','accepted')) BEGIN SELECT RAISE(ABORT,'active resolution'); END")
                }
            }
            try execute("CREATE TABLE IF NOT EXISTS session_metadata_sync(context TEXT PRIMARY KEY REFERENCES devices(context),revision INTEGER NOT NULL CHECK(revision>=0),refresh_order INTEGER NOT NULL CHECK(refresh_order>=0))")
            try execute("CREATE TABLE IF NOT EXISTS take_session_metadata(context TEXT NOT NULL REFERENCES devices(context),event TEXT NOT NULL REFERENCES events(id),authorization TEXT NOT NULL,revision INTEGER NOT NULL CHECK(revision>=0),payload TEXT NOT NULL,refresh_order INTEGER NOT NULL,PRIMARY KEY(context,event))")
            // Also tolerate the unreleased early-v5 cache; original event/task tables are untouched.
            if try !rows("PRAGMA table_info(session_metadata_sync)").contains(where: { $0[1] == "observed_at" }) {
                try execute("ALTER TABLE session_metadata_sync ADD COLUMN observed_at TEXT")
                try execute("DELETE FROM take_session_metadata")
                try execute("DELETE FROM session_metadata_sync")
            }
            try execute("CREATE TABLE IF NOT EXISTS deleted_accounts(environment TEXT NOT NULL,owner TEXT NOT NULL,PRIMARY KEY(environment,owner))")
            // Persistent fences survive cleanup, callbacks and independent Shortcut processes.
            for action in ["INSERT", "UPDATE"] {
                try execute("CREATE TRIGGER IF NOT EXISTS deleted_device_\(action) BEFORE \(action) ON devices WHEN EXISTS(SELECT 1 FROM deleted_accounts x WHERE x.environment=NEW.environment AND substr(NEW.context,length(x.environment)+2,37)=x.owner||'|') BEGIN SELECT RAISE(ABORT,'deleted account'); END")
            }
            try execute("PRAGMA user_version=6")
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
        let prepared=sqlite3_prepare_v2(handle, sql, -1, &statement, nil)
        guard prepared == SQLITE_OK, let statement else {
            DeviceSetupDiagnostics.sqlite(.prepare,prepared); throw VehicleQueueError.storage
        }
        defer { sqlite3_finalize(statement) }
        for (index, value) in values.enumerated() {
            let result: Int32
            if let value {
                result = value.withCString { sqlite3_bind_text(statement, Int32(index + 1), $0, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self)) }
            } else { result = sqlite3_bind_null(statement, Int32(index + 1)) }
            guard result == SQLITE_OK else { DeviceSetupDiagnostics.sqlite(.bind,result); throw VehicleQueueError.storage }
        }
        var result: [[String?]] = []
        while true {
            let stepped=sqlite3_step(statement)
            switch stepped {
            case SQLITE_ROW:
                result.append((0..<sqlite3_column_count(statement)).map { column in
                    sqlite3_column_text(statement, column).map { String(cString: $0) }
                })
            case SQLITE_DONE: return result
            default: DeviceSetupDiagnostics.sqlite(.step,stepped); throw VehicleQueueError.storage
            }
        }
    }
}
