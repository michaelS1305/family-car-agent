import Foundation
import SQLite3
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

private func rejectionSQL(_ directory: URL, _ statement: String) throws {
    var db: OpaquePointer?
    guard sqlite3_open(directory.appendingPathComponent("vehicle-events.sqlite").path, &db) == SQLITE_OK else { throw VehicleQueueError.storage }
    defer { sqlite3_close_v2(db) }
    guard sqlite3_exec(db, statement, nil, nil, nil) == SQLITE_OK else { throw VehicleQueueError.storage }
}

private func migrationRows(_ directory: URL, _ query: String) throws -> [[String?]] {
    var db: OpaquePointer?
    guard sqlite3_open_v2(directory.appendingPathComponent("vehicle-events.sqlite").path, &db, SQLITE_OPEN_READONLY, nil) == SQLITE_OK else { throw VehicleQueueError.storage }
    defer { sqlite3_close_v2(db) }
    var statement: OpaquePointer?
    guard sqlite3_prepare_v2(db, query, -1, &statement, nil) == SQLITE_OK else { throw VehicleQueueError.storage }
    defer { sqlite3_finalize(statement) }
    var rows: [[String?]] = []
    while true {
        let result = sqlite3_step(statement)
        if result == SQLITE_DONE { return rows }
        guard result == SQLITE_ROW else { throw VehicleQueueError.storage }
        rows.append((0..<sqlite3_column_count(statement)).map { column in
            sqlite3_column_text(statement, column).map { String(cString: $0) }
        })
    }
}

@MainActor private final class SyncSessionVault: SessionVault {
    var saved: AuthSession?
    var failWrite = false
    func read() throws -> AuthSession? { saved }
    func write(_ value: AuthSession) throws {
        if failWrite { throw AuthFailure.configuration }
        saved = value
    }
    func clear() throws { saved = nil }
}
private actor SyncSessionExchange: AuthTransport {
    let refreshed: AuthSession
    private(set) var calls = 0
    var release: CheckedContinuation<Void, Never>?
    init(_ refreshed: AuthSession) { self.refreshed = refreshed }
    func exchange(grant: String, fields: [String: String]) async throws -> AuthSession {
        calls += 1
        await withCheckedContinuation { release = $0 }
        return refreshed
    }
    func finish() { release?.resume(); release = nil }
}
@MainActor private final class SyncAuth: VehicleUploadAuthentication {
    let context: VehicleQueueContext
    var permitted = true
    var refreshOffline = false
    var current = true
    var suppliedContext: VehicleQueueContext?
    var force: [Bool] = []
    var onRequest: (() -> Void)?
    init(_ context: VehicleQueueContext) { self.context = context }
    func permits(_ context: VehicleQueueContext) -> Bool { permitted && self.context == context }
    func authorization(for context: VehicleQueueContext, forceRefresh: Bool) async throws -> VehicleUploadAuthorization {
        force.append(forceRefresh); onRequest?()
        if forceRefresh && refreshOffline { throw AuthFailure.network }
        return .init(context: suppliedContext ?? self.context, generation: 1, accessToken: forceRefresh ? "test-new" : "test-old")
    }
    func isCurrent(_ authorization: VehicleUploadAuthorization) -> Bool { current && permitted && authorization.context == context }
    func rejectAuthorization(for context: VehicleQueueContext) { if self.context == context { permitted = false } }
}

@MainActor private final class SyncTransport: VehicleUploadTransport {
    struct Created { let task: VehicleUploadTask; let bytes: Data; let request: URLRequest }
    let identifier: String
    var tasks: [Int64: VehicleUploadTask] = [:]
    var created: [Created] = []
    var resumed: [Int64] = []
    var cancelled: [Int64] = []
    var nextIdentifier: Int64?
    init(_ identifier: String) { self.identifier = identifier }
    func allTasks() async -> [VehicleUploadTask] { Array(tasks.values) }
    func create(request: URLRequest, file: URL, tag: String) throws -> VehicleUploadTask {
        let task = VehicleUploadTask(identifier: nextIdentifier ?? Int64(created.count + 1), tag: tag, state: .suspended)
        nextIdentifier = nil
        tasks[task.identifier] = task
        created.append(.init(task: task, bytes: try Data(contentsOf: file), request: request))
        return task
    }
    func resume(_ task: Int64) {
        guard let value = tasks[task] else { return }
        resumed.append(task); tasks[task] = .init(identifier: task, tag: value.tag, state: .running)
    }
    func cancel(_ task: Int64) { cancelled.append(task); tasks.removeValue(forKey: task) }
    func finish(_ id: Int64, status: Int? = 200, body: String = "", failed: Bool = false, after: String? = nil) -> VehicleUploadCompletion {
        let task = tasks.removeValue(forKey: id) ?? created.first(where: { $0.task.identifier == id })!.task
        return .init(task: id, tag: task.tag, status: status, body: Data(body.utf8), retryAfter: after, transportFailed: failed)
    }
}

@MainActor private final class SyncFixture {
    let root: URL
    let context: VehicleQueueContext
    let queue: VehicleEventQueue
    let auth: SyncAuth
    let transport: SyncTransport
    var namespace: UUID?
    var clock = Date(timeIntervalSince1970: 1_800_000_000)
    var coordinator: VehicleSyncCoordinator!
    var retryWait: @MainActor (TimeInterval) async throws -> Void = { try await Task.sleep(for: .seconds($0)) }
    init(root: URL) throws {
        self.root = root
        context = try VehicleQueueContext(environment: .development,
            identity: .init(owner: UUID(), user: 1, family: 2, generation: 1, version: 1), device: UUID())
        queue = try VehicleEventQueue(directory: root.appendingPathComponent("db"))
        auth = SyncAuth(context)
        transport = SyncTransport(VehicleSyncCoordinator.sessionIdentifier(environment: .development, context: context))
        try restoreCoordinator()
    }
    func restoreCoordinator() throws {
        coordinator?.fence()
        coordinator = try VehicleSyncCoordinator(environment: .development, context: context, queue: queue,
            authentication: auth, transport: transport, directory: root.appendingPathComponent("uploads"), now: { [unowned self] in self.clock }, retryWait: retryWait)
    }
    func start() async throws { try await queue.initializeFreshDevice(context) }
    func take(vehicle: UUID = UUID()) async throws -> QueuedVehicleEvent {
        var vehicles = try await queue.authorizedVehicles(context); vehicles.insert(vehicle)
        let verification = try await queue.beginVerification(context)
        try await queue.completeVerification(context, generation: verification, vehicles: vehicles, namespace: namespace)
        return try await queue.enqueueTake(context, vehicle: vehicle, occurredAt: clock)
    }
    func states() async throws -> [VehicleQueueState] { try await queue.records(context).map(\.state) }
}

@main struct VehicleSyncChecks {
    @MainActor static func main() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("fca-sync-check-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        func fixture() async throws -> SyncFixture {
            let f = try SyncFixture(root: root.appendingPathComponent(UUID().uuidString))
            try await f.start(); return f
        }
        let accepted = #"{"kind":"accepted","admission_outcome":"accepted","transition":"redundant_take"}"#
        let duplicate = #"{"kind":"retry","admission_outcome":"accepted"}"#
        let terminal = #"{"kind":"terminal","admission_outcome":"vehicle_retired"}"#

        // Build an independent v2 database with the shipped v2 schema and real
        // accepted TAKE, legacy blocked RETURN and pending TAKE payloads.
        let migrationSource = try await fixture()
        let migrationTake = try await migrationSource.take()
        await migrationSource.coordinator.wake()
        await migrationSource.coordinator.receive(migrationSource.transport.finish(1, body: accepted))
        migrationSource.clock.addTimeInterval(10)
        let migrationReturn = try await migrationSource.queue.enqueueReturn(migrationSource.context,
            vehicle: migrationTake.vehicle, occurredAt: migrationSource.clock, takeID: migrationTake.id,
            location: .init(latitude: 32, longitude: 34, accuracy: 10, measuredAt: migrationSource.clock))
        await migrationSource.coordinator.wake()
        await migrationSource.coordinator.receive(migrationSource.transport.finish(2, status: 409))
        migrationSource.coordinator.fence()
        _ = try await migrationSource.queue.enqueueTake(migrationSource.context,
            vehicle: migrationTake.vehicle, occurredAt: migrationSource.clock.addingTimeInterval(10))
        let v2 = root.appendingPathComponent("legacy-v2")
        try FileManager.default.createDirectory(at: v2, withIntermediateDirectories: true)
        try rejectionSQL(v2, """
            CREATE TABLE IF NOT EXISTS devices(context TEXT PRIMARY KEY,environment TEXT NOT NULL,device TEXT NOT NULL,last_sequence INTEGER NOT NULL CHECK(last_sequence>=0),active INTEGER NOT NULL CHECK(active IN(0,1)),UNIQUE(environment,device));
            CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,context TEXT NOT NULL REFERENCES devices(context),sequence INTEGER NOT NULL CHECK(sequence>0),vehicle TEXT NOT NULL,cause TEXT REFERENCES events(id),payload TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('pending','preparing','registered','awaitingAuthentication','accepted','terminal','blocked')),attempt TEXT,session TEXT,task INTEGER,reason TEXT,UNIQUE(context,sequence),UNIQUE(context,cause));
            CREATE TABLE IF NOT EXISTS authorization_scopes(context TEXT PRIMARY KEY REFERENCES devices(context),generation TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('verificationPending','verified','revoked')),namespace TEXT);
            CREATE TABLE IF NOT EXISTS vehicle_authorizations(context TEXT NOT NULL REFERENCES authorization_scopes(context),vehicle TEXT NOT NULL,allowed INTEGER NOT NULL CHECK(allowed IN(0,1)),PRIMARY KEY(context,vehicle));
            PRAGMA user_version=2;
            """)
        let sourcePath = migrationSource.root.appendingPathComponent("db/vehicle-events.sqlite").path.replacingOccurrences(of: "'", with: "''")
        try rejectionSQL(v2, """
            ATTACH DATABASE '\(sourcePath)' AS original;
            INSERT INTO devices SELECT * FROM original.devices;
            INSERT INTO events SELECT * FROM original.events ORDER BY sequence;
            INSERT INTO authorization_scopes SELECT * FROM original.authorization_scopes;
            INSERT INTO vehicle_authorizations SELECT * FROM original.vehicle_authorizations;
            DETACH DATABASE original;
            """)
        let tables = ["devices", "events", "authorization_scopes", "vehicle_authorizations"]
        let before = try tables.map { try migrationRows(v2, "SELECT * FROM \($0) ORDER BY 1") }
        let versionBefore = try migrationRows(v2, "PRAGMA user_version")
        precondition(versionBefore == [["2"]])
        let migrated = try VehicleEventQueue(directory: v2)
        let preserved = try await migrated.records(migrationSource.context)
        precondition(preserved.map { $0.event.sequence } == [1, 2, 3])
        precondition(preserved.map(\.state) == [.accepted, .blocked, .pending])
        precondition(preserved[1].event == migrationReturn)
        for _ in 0..<2 {
            let reopened = try VehicleEventQueue(directory: v2)
            let records = try await reopened.records(migrationSource.context)
            precondition(records.map(\.event) == preserved.map(\.event))
            let after = try tables.map { try migrationRows(v2, "SELECT * FROM \($0) ORDER BY 1") }
            let version = try migrationRows(v2, "PRAGMA user_version")
            let recoveryRows = try migrationRows(v2, "SELECT * FROM return_recoveries")
            precondition(after == before && version == [["3"]] && recoveryRows.isEmpty)
        }
        print("PASS: SQLite v2 to v3 preserves payloads, IDs, ordering, states, blocked RETURN and idempotent reopening")

        let sharedFixture = try await fixture(), ctx = sharedFixture.context
        let vault = SyncSessionVault()
        vault.saved = AuthSession(owner: ctx.owner, accessToken: "old", refreshToken: "secret-sentinel",
                                  expires: .distantPast, activated: true)
        let exchange = SyncSessionExchange(.init(owner: ctx.owner, accessToken: "new", refreshToken: "second-sentinel", expires: .distantFuture))
        let sessions = SessionManager(vault: vault, transport: exchange)
        try sessions.restore()
        let provider = SessionVehicleAuthentication(environment: .development, sessions: sessions, queueDirectory: sharedFixture.root.appendingPathComponent("db"))
        precondition(!provider.permits(ctx))
        let vehicleA = UUID(), vehicleB = UUID()
        try sessions.authorizeVehicleScope(provider.scope(ctx), owner: ctx.owner, generation: sessions.generation,
                                           bindings: [vehicleA: "A", vehicleB: "B"])
        let initialVerification = try await sharedFixture.queue.beginVerification(ctx)
        try await sharedFixture.queue.completeVerification(ctx, generation: initialVerification, vehicles: [vehicleA, vehicleB], namespace: sessions.session?.shortcutNamespace)
        sharedFixture.namespace = sessions.session?.shortcutNamespace
        let options = provider.shortcutVehicles(ctx)
        precondition(Set(options.values) == [vehicleA, vehicleB] && options[vehicleA.uuidString] == nil)
        let fg = Task { try await sessions.access(owner: ctx.owner) }
        while await exchange.calls == 0 { await Task.yield() }
        let bg = Task { try await provider.authorization(for: ctx, forceRefresh: false) }
        await exchange.finish()
        let grant = try await bg.value, foreground = try await fg.value
        let calls = await exchange.calls
        precondition(calls == 1 && foreground == grant.accessToken && provider.isCurrent(grant))
        let actual = try VehicleSyncCoordinator(environment: .development, context: ctx, queue: sharedFixture.queue,
            authentication: provider, transport: sharedFixture.transport, directory: sharedFixture.root.appendingPathComponent("actual"))
        let boundEvent = try await sharedFixture.take(vehicle: vehicleA)
        await actual.wake()
        precondition(sharedFixture.transport.created.count == 1)
        try sessions.authorizeVehicleScope(provider.scope(ctx), owner: ctx.owner, generation: sessions.generation,
                                           bindings: [vehicleB: "B"])
        await actual.wake()
        precondition(sharedFixture.transport.created.count == 1 && sharedFixture.transport.cancelled == [1])
        precondition(!provider.permitsVehicle(vehicleA, in: ctx) && Set(provider.shortcutVehicles(ctx).values) == [vehicleB])
        let bindingRetained = try await sharedFixture.queue.records(ctx)
        precondition(bindingRetained.count == 1 && bindingRetained[0].event == boundEvent)
        try sessions.authorizeVehicleScope(provider.scope(ctx), owner: ctx.owner, generation: sessions.generation,
                                           bindings: [vehicleA: "A", vehicleB: "B"])
        let offlineRestored = SessionManager(vault: vault, transport: exchange)
        try offlineRestored.restore()
        let offlineProvider = SessionVehicleAuthentication(environment: .development, sessions: offlineRestored, queueDirectory: sharedFixture.root.appendingPathComponent("db"))
        precondition(offlineProvider.shortcutVehicles(ctx) == options)
        for logout in [false, true] {
            let testVault = SyncSessionVault(); testVault.saved = vault.saved
            let manager = SessionManager(vault: testVault, transport: exchange)
            try manager.restore()
            let permit = VehicleRecordingPermit()
            manager.onVehicleBindingsReduced = { permit.invalidate() }
            manager.onInvalidation = { _ in permit.invalidate() }
            let db = try VehicleEventQueue(directory: root.appendingPathComponent(UUID().uuidString))
            try await db.initializeFreshDevice(ctx)
            let verified = try await db.beginVerification(ctx)
            try await db.completeVerification(ctx, generation: verified, vehicles: [vehicleA, vehicleB], namespace: sessions.session?.shortcutNamespace)
            let original = try await db.enqueueTake(ctx, vehicle: vehicleB, occurredAt: Date())
            let arrived = AsyncStream<Void>.makeStream(), proceed = AsyncStream<Void>.makeStream()
            let selectedNamespace = manager.session!.shortcutNamespace!
            let pending = Task {
                arrived.continuation.yield(())
                for await _ in proceed.stream { break }
                return try await db.recordAuthorizedShortcut(ctx, vehicle: vehicleA, kind: .take,
                    time: Date(), location: nil, namespace: selectedNamespace, permit: permit)
            }
            for await _ in arrived.stream { break }
            if logout { try manager.clear() }
            else { try manager.authorizeVehicleScope(provider.scope(ctx), owner: ctx.owner, generation: manager.generation, bindings: [vehicleB: "B"]) }
            proceed.continuation.yield(()); proceed.continuation.finish(); arrived.continuation.finish()
            do { _ = try await pending.value; fatalError("Stale TAKE allocated a sequence") }
            catch VehicleQueueError.contextUnavailable {}
            let remaining = try await db.records(ctx)
            precondition(remaining.map(\.event) == [original])
            let next = try await db.enqueueTake(ctx, vehicle: vehicleB, occurredAt: Date())
            precondition(next.sequence == original.sequence + 1)
        }
        try VehicleEventQueue.revokeAuthorization(directory: sharedFixture.root.appendingPathComponent("db"), context: ctx)
        vault.failWrite = true
        do {
            try offlineRestored.authorizeVehicleScope(provider.scope(ctx), owner: ctx.owner,
                generation: offlineRestored.generation, bindings: [:])
            fatalError("Expected failed Keychain write")
        } catch AuthFailure.configuration {}
        precondition(offlineProvider.shortcutVehicles(ctx).isEmpty)
        if CommandLine.arguments.contains("--verify-durable-revocation") {
            let restart = SessionManager(vault: vault, transport: exchange)
            try restart.restore()
            if SessionVehicleAuthentication(environment: .development, sessions: restart, queueDirectory: sharedFixture.root.appendingPathComponent("db")).permitsVehicle(vehicleA, in: ctx) {
                print("FAIL: fresh authentication provider recovered revoked binding after vault write failure")
                exit(1)
            }
        }
        vault.failWrite = false
        try offlineRestored.checkVehicleProfile(user: ctx.user, family: ctx.family, expectedUser: ctx.user, expectedFamily: ctx.family)
        do {
            try offlineRestored.checkVehicleProfile(user: ctx.user, family: ctx.family + 1, expectedUser: ctx.user, expectedFamily: ctx.family)
            fatalError("Expected second profile check to reject a changed family")
        } catch AuthFailure.stale {}
        precondition(offlineRestored.session?.vehicleScope == nil && vault.saved?.vehicleScope == nil)
        await actual.wake()
        precondition(sharedFixture.transport.created.count == 1) // Durable revocation also blocks the older live SessionManager.
        print("PASS: confirmed binding removal cancels scheduling without sequence loss; reauthorization and offline picker restoration")
        func checkStoredFiles(at root: URL) throws {
            let paths = FileManager.default.enumerator(at: root, includingPropertiesForKeys: [.isRegularFileKey])!
            for case let file as URL in paths where try file.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile == true {
                let bytes = try Data(contentsOf: file)
                for marker in ["second-sentinel", "secret-sentinel", "Bearer new"] {
                    precondition(bytes.range(of: Data(marker.utf8)) == nil)
                }
            }
        }
        try checkStoredFiles(at: sharedFixture.root)
        try sessions.clear()
        precondition(!provider.isCurrent(grant) && provider.shortcutVehicles(ctx).isEmpty)
        vault.saved = AuthSession(owner: UUID(), accessToken: "another", refreshToken: "third-sentinel", expires: .distantFuture, activated: true)
        try sessions.restore()
        precondition(!provider.permits(ctx) && provider.shortcutVehicles(ctx).isEmpty)
        print("PASS: real shared session provider, explicit scope, refresh, logout and different login")

        // Exercise real structured responses, not just a generic 4xx blocked-head assertion.
        let unavailableBody = #"{"detail":{"code":"DEVICE_OR_VEHICLE_UNAVAILABLE","message":"unavailable"}}"#
        for (status, body, rejected) in [
            (404, unavailableBody, true),
            (403, #"{"detail":{"code":"IDENTITY_UNAVAILABLE"}}"#, true),
            (404, #"{"detail":{"code":"OTHER_ERROR"}}"#, false),
            (422, unavailableBody, false),
            (404, "not-json", false),
            (404, #"{"code":"DEVICE_OR_VEHICLE_UNAVAILABLE"}"#, false)
        ] {
            let f = try await fixture()
            let event = try await f.take()
            let pending = try await f.take()
            await f.coordinator.wake()
            await f.coordinator.receive(f.transport.finish(1, status: status, body: body))
            let rows = try await f.queue.records(f.context)
            precondition(rows.map(\.event) == [event, pending] && rows[0].state == .blocked && rows[1].state == .pending)
            let grants = try await f.queue.authorizedVehicles(f.context)
            precondition(grants.isEmpty == rejected)
            if rejected {
                do { _ = try await f.queue.enqueueTake(f.context, vehicle: event.vehicle, occurredAt: f.clock); fatalError("Rejected scope allocated TAKE") }
                catch VehicleQueueError.contextUnavailable {}
                do {
                    _ = try await f.queue.enqueueReturn(f.context, vehicle: event.vehicle, occurredAt: f.clock, takeID: event.id,
                        location: .init(latitude: 32, longitude: 34, accuracy: 5, measuredAt: f.clock))
                    fatalError("Rejected scope allocated RETURN")
                } catch VehicleQueueError.contextUnavailable {}
                let verification = try await f.queue.beginVerification(f.context)
                try await f.queue.completeVerification(f.context, generation: verification, vehicles: [event.vehicle, pending.vehicle])
                f.auth.permitted = true; try f.restoreCoordinator(); await f.coordinator.wake()
                precondition(f.transport.created.count == 1) // Reverification cannot skip the rejected sequence.
            } else {
                _ = try await f.queue.enqueueTake(f.context, vehicle: event.vehicle, occurredAt: f.clock)
            }
        }
        for failWrites in [false, true] {
            let f = try await fixture(), vehicle = UUID()
            let v = SyncSessionVault()
            v.saved = AuthSession(owner: f.context.owner, accessToken: "synthetic", refreshToken: "synthetic-refresh", expires: .distantFuture, activated: true)
            let manager = SessionManager(vault: v, transport: exchange); try manager.restore()
            let real = SessionVehicleAuthentication(environment: .development, sessions: manager, queueDirectory: f.root.appendingPathComponent("db"))
            try manager.authorizeVehicleScope(real.scope(f.context), owner: f.context.owner, generation: manager.generation, bindings: [vehicle: "Test"])
            let staleSnapshot = v.saved
            f.namespace = manager.session?.shortcutNamespace
            let event = try await f.take(vehicle: vehicle)
            let sync = try VehicleSyncCoordinator(environment: .development, context: f.context, queue: f.queue,
                authentication: real, transport: f.transport, directory: f.root.appendingPathComponent("real-rejection"))
            await sync.wake()
            if failWrites {
                try rejectionSQL(f.root.appendingPathComponent("db"), "CREATE TRIGGER reject_scope_write BEFORE UPDATE ON authorization_scopes BEGIN SELECT RAISE(ABORT,'test'); END; CREATE TRIGGER reject_device_write BEFORE UPDATE ON devices BEGIN SELECT RAISE(ABORT,'test'); END")
            }
            v.failWrite = true // Preserve stale Keychain even while memory is fenced.
            await sync.receive(f.transport.finish(1, status: 404, body: unavailableBody))
            precondition(real.shortcutVehicles(f.context).isEmpty && !real.permitsVehicle(vehicle, in: f.context))
            await sync.wake(); precondition(f.transport.created.count == 1)
            let kept = try await f.queue.records(f.context)
            precondition(kept.count == 1 && kept[0].event == event)
            if !failWrites {
                precondition(kept[0].state == .blocked)
                let oldVault = SyncSessionVault(); oldVault.saved = staleSnapshot
                let restoredSession = SessionManager(vault: oldVault, transport: exchange); try restoredSession.restore()
                let fresh = SessionVehicleAuthentication(environment: .development, sessions: restoredSession, queueDirectory: f.root.appendingPathComponent("db"))
                precondition(fresh.shortcutVehicles(f.context).isEmpty)
            } else {
                precondition(kept[0].state == .registered) // No false claim of persistence when every write failed.
            }
        }
        print("PASS: structured authorization rejection, durable fence, stale Keychain, TAKE/RETURN denial, generic errors and memory fail-closed")

        let ordered = try await fixture()
        let first = try await ordered.take()
        let second = try await ordered.queue.enqueueReturn(ordered.context, vehicle: first.vehicle, occurredAt: ordered.clock,
            takeID: first.id, location: .init(latitude: 32, longitude: 34, accuracy: 10, measuredAt: ordered.clock))
        let third = try await ordered.take()
        await ordered.coordinator.wake(); await ordered.coordinator.wake()
        precondition(ordered.transport.created.count == 1)
        let registered = try await ordered.queue.records(ordered.context)
        precondition(registered[0].state == .registered && registered[0].taskIdentifier == ordered.transport.resumed.first)
        // HTTP 200 alone is not an admission. Preserve bytes through ambiguous retry.
        await ordered.coordinator.receive(ordered.transport.finish(1))
        precondition(ordered.transport.created.count == 1)
        await ordered.coordinator.wake(); precondition(ordered.transport.created.count == 1)
        ordered.clock = ordered.clock.addingTimeInterval(61)
        try ordered.restoreCoordinator() // Cooldown and queue both survive coordinator recreation.
        await ordered.coordinator.wake()
        precondition(ordered.transport.created.count == 2)
        precondition(ordered.transport.created[0].bytes == ordered.transport.created[1].bytes)
        let response = ordered.transport.finish(2, body: duplicate)
        await ordered.coordinator.receive(response)
        precondition(ordered.transport.created.count == 3)
        await ordered.coordinator.receive(response) // Duplicate callback must not resolve the new head.
        precondition(ordered.transport.created.count == 3)
        await ordered.coordinator.receive(ordered.transport.finish(3, body: accepted))
        precondition(ordered.transport.created.count == 4)
        await ordered.coordinator.receive(ordered.transport.finish(4, body: accepted))
        let allAccepted = try await ordered.states(); precondition(allAccepted == [.accepted, .accepted, .accepted])
        let payloads = try ordered.transport.created.map { try JSONSerialization.jsonObject(with: $0.bytes) as! [String: Any] }
        precondition(payloads.map { $0["device_sequence"] as! Int } == [1, 1, 2, 3])
        precondition(payloads[2]["take_event_id"] as? String == first.id.uuidString)
        precondition(payloads[2]["event_id"] as? String == second.id.uuidString && payloads[3]["event_id"] as? String == third.id.uuidString)
        precondition(ordered.transport.created[2].request.url!.path.hasSuffix("/events/return"))
        precondition(!String(decoding: ordered.transport.created[0].bytes, as: UTF8.self).contains("test-old"))
        print("PASS: ordered multi-car TAKE/RETURN, immutable retry, duplicate callbacks")

        let reused = try await fixture(); _ = try await reused.take(); _ = try await reused.take()
        await reused.coordinator.wake()
        reused.transport.nextIdentifier = 1
        await reused.coordinator.receive(reused.transport.finish(1, body: accepted))
        await reused.coordinator.receive(reused.transport.finish(1, body: accepted))
        let reusedStates = try await reused.states(); precondition(reusedStates == [.accepted, .accepted])

        for disposition in ["gap", "conflict", "unavailable", "malformed", "future_clock_skew"] {
            let f = try await fixture(); _ = try await f.take(); _ = try await f.take()
            await f.coordinator.wake()
            await f.coordinator.receive(f.transport.finish(1, body: "{\"kind\":\"\(disposition)\",\"admission_outcome\":null}"))
            await f.coordinator.wake()
            let states = try await f.states(); precondition(states == [.blocked, .pending])
            precondition(f.transport.created.count == 1)
        }
        for body in [terminal, #"{"kind":"retry","admission_outcome":"causal_conflict"}"#] {
            let f = try await fixture(); _ = try await f.take(); _ = try await f.take()
            await f.coordinator.wake(); await f.coordinator.receive(f.transport.finish(1, body: body))
            let states = try await f.states(); precondition(states == [.terminal, .registered])
        }
        let causal = try await fixture(); let cause = try await causal.take()
        _ = try await causal.queue.enqueueReturn(causal.context, vehicle: cause.vehicle, occurredAt: causal.clock,
            takeID: cause.id, location: .init(latitude: 32, longitude: 34, accuracy: 10, measuredAt: causal.clock))
        await causal.coordinator.wake(); await causal.coordinator.receive(causal.transport.finish(1, body: terminal))
        let causeStates = try await causal.states(); precondition(causeStates == [.terminal, .blocked])
        print("PASS: all AdmissionResult dispositions and terminal causal protection")

        let expired = try await fixture(); _ = try await expired.take()
        await expired.coordinator.wake(); await expired.coordinator.receive(expired.transport.finish(1, status: 401))
        precondition(expired.auth.force == [false, true])
        precondition(expired.transport.created[0].bytes == expired.transport.created[1].bytes)
        await expired.coordinator.receive(expired.transport.finish(2, status: 401))
        try expired.restoreCoordinator()
        await expired.coordinator.wake()
        let awaiting = try await expired.states(); precondition(awaiting == [.awaitingAuthentication])
        await expired.coordinator.suspend()
        await expired.coordinator.wake()
        precondition(expired.transport.created.count == 2 && expired.transport.tasks.isEmpty)
        let offline = try await fixture(); _ = try await offline.take()
        await offline.coordinator.wake()
        offline.auth.refreshOffline = true
        await offline.coordinator.receive(offline.transport.finish(1, status: 401))
        await offline.coordinator.wake()
        precondition(offline.transport.created.count == 1)
        offline.auth.refreshOffline = false; offline.clock.addTimeInterval(61)
        try offline.restoreCoordinator()
        await offline.coordinator.wake()
        precondition(offline.transport.created.count == 2)
        precondition(offline.transport.created[1].request.value(forHTTPHeaderField: "Authorization") == "Bearer test-new")
        precondition(offline.transport.created[1].bytes == offline.transport.created[0].bytes)
        let late = offline.transport.finish(2, body: accepted)
        await offline.coordinator.suspend()
        await offline.coordinator.receive(late)
        let retained = try await offline.states()
        precondition(retained == [.registered] && offline.coordinator.diagnostic == .identityUnavailable)
        let mismatch = try await fixture(); _ = try await mismatch.take()
        mismatch.auth.suppliedContext = expired.context
        await mismatch.coordinator.wake(); precondition(mismatch.transport.created.isEmpty)
        mismatch.auth.suppliedContext = nil
        mismatch.auth.onRequest = { mismatch.auth.permitted = false }
        await mismatch.coordinator.wake(); precondition(mismatch.transport.created.isEmpty)
        print("PASS: 401, forced fresh authorization, logout and identity fencing")

        for status: Int? in [nil, 429, 500, 503] {
            let f = try await fixture(); _ = try await f.take(); _ = try await f.take()
            await f.coordinator.wake()
            await f.coordinator.receive(f.transport.finish(1, status: status, failed: status == nil, after: "120"))
            try f.restoreCoordinator()
            await f.coordinator.wake(); precondition(f.transport.created.count == 1)
            f.clock = f.clock.addingTimeInterval(121)
            await f.coordinator.wake(); precondition(f.transport.created.count == 2)
            precondition(f.transport.created[0].bytes == f.transport.created[1].bytes)
        }
        let early = try await fixture(); _ = try await early.take(); _ = try await early.take()
        await early.coordinator.wake(); await early.coordinator.receive(early.transport.finish(1, status: 422))
        await early.coordinator.wake()
        let earlyStates = try await early.states(); precondition(earlyStates == [.blocked, .pending])
        precondition(early.transport.created.count == 1)
        precondition(VehicleSyncCoordinator.retryDate("Wed, 01 Jan 2031 00:00:00 GMT", now: early.clock) > early.clock.addingTimeInterval(60))
        print("PASS: transport/HTTP uncertainty, durable Retry-After, early rejection")

        for body in ["not-json", #"{"kind":"accepted"}"#, #"{"kind":"terminal","admission_outcome":"unknown"}"#] {
            let f = try await fixture(); _ = try await f.take(); _ = try await f.take()
            await f.coordinator.wake(); await f.coordinator.receive(f.transport.finish(1, body: body))
            let states = try await f.states(); precondition(states == [.blocked, .pending])
            precondition(f.transport.created.count == 1)
        }
        let noResponse = try await fixture(); _ = try await noResponse.take()
        await noResponse.coordinator.wake(); await noResponse.coordinator.receive(noResponse.transport.finish(1, status: nil))
        let unknown = try await noResponse.states(); precondition(unknown == [.blocked])

        for mappingPersisted in [false, true] {
            let f = try await fixture(); let event = try await f.take()
            let claim = try await f.queue.prepareNext(f.context)!
            let task = VehicleUploadTask(identifier: 51, tag: event.id.uuidString + "/" + claim.attempt!.uuidString, state: .suspended)
            f.transport.tasks[51] = task
            if mappingPersisted {
                try await f.queue.markRegistered(f.context, event: event.id, attempt: claim.attempt!, sessionIdentifier: f.transport.identifier, taskIdentifier: 51)
            }
            try f.restoreCoordinator()
            await f.coordinator.wake(); await f.coordinator.wake()
            precondition(f.transport.created.isEmpty && f.transport.resumed == [51])
            let rows = try await f.queue.records(f.context)
            precondition(rows[0].state == .registered && rows[0].taskIdentifier == 51)
        }
        let lost = try await fixture(); let original = try await lost.take()
        _ = try await lost.queue.prepareNext(lost.context) // Termination before task creation.
        try lost.restoreCoordinator(); await lost.coordinator.wake()
        let lostRows = try await lost.queue.records(lost.context)
        precondition(lostRows[0].event == original && lostRows[0].state == .registered)
        let ambiguous = try await fixture(); _ = try await ambiguous.take()
        ambiguous.transport.tasks[1] = .init(identifier: 1, tag: nil, state: .running)
        ambiguous.transport.tasks[2] = .init(identifier: 2, tag: nil, state: .running)
        await ambiguous.coordinator.wake()
        precondition(ambiguous.transport.created.isEmpty && ambiguous.transport.cancelled.count == 2)
        let frozen = try await fixture(); let frozenEvent = try await frozen.take()
        let frozenClaim = try await frozen.queue.prepareNext(frozen.context)!
        frozen.transport.tasks[7] = .init(identifier: 7, tag: frozenEvent.id.uuidString + "/" + frozenClaim.attempt!.uuidString, state: .suspended)
        try await frozen.queue.suspend(frozen.context)
        await frozen.coordinator.wake()
        precondition(frozen.transport.resumed.isEmpty && frozen.transport.created.isEmpty)
        print("PASS: task restoration, create/mapping/resume crash windows, duplicate-task prevention")

        // Virtual wakeups: no network, real-time sleeps or OS background assumptions.
        for fenced in [false, true] {
            let f = try await fixture()
            var waiting: CheckedContinuation<Void, Never>?
            var delay: TimeInterval = 0
            f.retryWait = { seconds in
                delay = seconds
                await withCheckedContinuation { waiting = $0 }
            }
            try f.restoreCoordinator()
            let event = try await f.take()
            await f.coordinator.wake()
            await f.coordinator.receive(f.transport.finish(1, status: 503, after: "120"))
            for _ in 0..<10_000 { if waiting != nil { break }; await Task.yield() }
            precondition(waiting != nil && delay == 120 && f.transport.created.count == 1)
            if fenced { f.coordinator.fence() }
            f.clock.addTimeInterval(121)
            waiting?.resume(); waiting = nil
            for _ in 0..<10_000 { if f.transport.created.count == 2 { break }; await Task.yield() }
            precondition(f.transport.created.count == (fenced ? 1 : 2))
            if !fenced {
                let body = try JSONSerialization.jsonObject(with: f.transport.created[1].bytes) as! [String: Any]
                precondition((body["event_id"] as? String)?.lowercased() == event.id.uuidString.lowercased())
                await f.coordinator.receive(f.transport.finish(2, body: accepted))
            }
            f.coordinator.fence()
        }
        let recovery = try await fixture()
        var releaseRefresh: CheckedContinuation<Void, Never>?
        recovery.retryWait = { _ in await withCheckedContinuation { releaseRefresh = $0 } }
        try recovery.restoreCoordinator()
        _ = try await recovery.take()
        await recovery.coordinator.wake()
        recovery.auth.refreshOffline = true
        await recovery.coordinator.receive(recovery.transport.finish(1, status: 401))
        for _ in 0..<10_000 { if releaseRefresh != nil { break }; await Task.yield() }
        precondition(releaseRefresh != nil && recovery.transport.created.count == 1)
        recovery.auth.refreshOffline = false; recovery.clock.addTimeInterval(61)
        releaseRefresh?.resume(); releaseRefresh = nil
        for _ in 0..<10_000 { if recovery.transport.created.count == 2 { break }; await Task.yield() }
        precondition(recovery.transport.created.count == 2 && recovery.auth.force.last == true)
        await recovery.coordinator.receive(recovery.transport.finish(2, body: accepted))
        recovery.coordinator.fence()
        print("PASS: automatic cooldown retry, preserved event identity, logout fence and offline JWT refresh recovery")

        // RETURN recovery uses a separate durable request, never a replacement event.
        func rejectedReturn(code: String = "RETURN_OUTSIDE_HOME") async throws -> (SyncFixture, QueuedVehicleEvent) {
            let f = try await fixture()
            let take = try await f.take()
            await f.coordinator.wake()
            await f.coordinator.receive(f.transport.finish(1, body: accepted))
            f.clock.addTimeInterval(10)
            let event = try await f.queue.enqueueReturn(f.context, vehicle: take.vehicle, occurredAt: f.clock,
                takeID: take.id, location: .init(latitude: 32, longitude: 34, accuracy: 10, measuredAt: f.clock))
            await f.coordinator.wake()
            await f.coordinator.receive(f.transport.finish(2, status: 409, body: "{\"detail\":{\"code\":\"\(code)\"}}"))
            return (f, event)
        }
        func explicitReturn(_ f: SyncFixture, _ e: QueuedVehicleEvent) async throws {
            f.clock.addTimeInterval(1)
            let duplicate = try await f.queue.recordShortcut(f.context, vehicle: e.vehicle, kind: .returning,
                time: f.clock, location: .init(latitude: 32.1, longitude: 34.1, accuracy: 10, measuredAt: f.clock))
            precondition(duplicate == e)
        }
        let (rf, returning) = try await rejectedReturn()
        let queued = try await rf.queue.enqueueTake(rf.context, vehicle: returning.vehicle, occurredAt: rf.clock.addingTimeInterval(1))
        try await explicitReturn(rf, returning)
        guard let initial = try await rf.queue.recovery(rf.context, event: returning.id) else { preconditionFailure() }
        try await explicitReturn(rf, returning)
        let repeated = try await rf.queue.recovery(rf.context, event: returning.id)
        precondition(repeated?.id == initial.id && repeated?.payload == initial.payload)
        let reopened = try VehicleEventQueue(directory: rf.root.appendingPathComponent("db"))
        let durable = try await reopened.recovery(rf.context, event: returning.id)
        precondition(durable?.payload == initial.payload)
        let body = try JSONSerialization.jsonObject(with: initial.payload) as! [String: Any]
        let originalBytes = try JSONSerialization.data(withJSONObject: body["original_return"]!, options: [.sortedKeys])
        precondition(originalBytes == rf.transport.created[1].bytes)
        await rf.coordinator.wake()
        precondition(rf.transport.created.last!.request.url!.path.hasSuffix("/events/return/\(returning.id.uuidString)/recovery"))
        let recoveryTask = rf.transport.created.last!.task
        try rf.restoreCoordinator() // Existing task must be reattached, not duplicated.
        await rf.coordinator.wake()
        precondition(rf.transport.created.count == 3)
        await rf.coordinator.receive(rf.transport.finish(recoveryTask.identifier, status: nil, failed: true))
        rf.clock.addTimeInterval(180) // Server might have committed before timeout; replay even after expiry.
        try rf.restoreCoordinator()
        await rf.coordinator.wake()
        precondition(rf.transport.created.count == 4 && rf.transport.created[3].bytes == initial.payload)
        let receipt = "{\"kind\":\"accepted\",\"admission_outcome\":\"accepted\",\"recovery_outcome\":\"recovered\",\"event_id\":\"\(returning.id)\",\"recovery_id\":\"\(initial.id)\",\"verified_at\":\"2026-11-22T14:40:00+00:00\"}"
        await rf.coordinator.receive(rf.transport.finish(4, body: receipt))
        let rows = try await rf.queue.records(rf.context)
        precondition(rows[1].event == returning && rows[1].state == .accepted && rows[2].event == queued)
        precondition(rows.map { $0.event.sequence } == [1, 2, 3] && rf.transport.created.count == 5)
        rf.coordinator.fence()

        for code in ["RETURN_OUTSIDE_HOME", "RETURN_HOME_UNAVAILABLE", "RETURN_RECOVERY_VERIFICATION_EXPIRED",
                     "RETURN_RECOVERY_ORDER_CONFLICT", "RETURN_RECOVERY_LEGACY_UNVERIFIED", "UNKNOWN"] {
            let (f, e) = try await rejectedReturn()
            try await explicitReturn(f, e)
            let first = try await f.queue.recovery(f.context, event: e.id)!
            await f.coordinator.wake()
            await f.coordinator.receive(f.transport.finish(3, status: 409, body: "{\"detail\":{\"code\":\"\(code)\"}}"))
            await f.coordinator.wake() // Never creates fresh evidence on its own.
            precondition(f.transport.created.count == 3)
            if ReturnRecoveryPolicy.renewable.contains(code) {
                try await explicitReturn(f, e)
                let next = try await f.queue.recovery(f.context, event: e.id)!
                precondition(next.id != first.id && next.payload != first.payload)
            } else {
                do { try await explicitReturn(f, e); preconditionFailure("Unexpected eligibility") }
                catch ShortcutQueueError.legacyReturn { precondition(code == "RETURN_RECOVERY_LEGACY_UNVERIFIED") }
                catch ShortcutQueueError.recoveryBlocked { precondition(code != "RETURN_RECOVERY_LEGACY_UNVERIFIED") }
            }
            let saved = try await f.queue.records(f.context)
            precondition(saved.count == 2 && saved[1].event == e && saved[1].state == .blocked)
            f.coordinator.fence()
        }
        let (legacy, legacyEvent) = try await rejectedReturn(code: "UNKNOWN")
        do { try await explicitReturn(legacy, legacyEvent); preconditionFailure("Legacy must not be inferred") }
        catch ShortcutQueueError.legacyReturn {}
        let legacyAttempt = try await legacy.queue.recovery(legacy.context, event: legacyEvent.id)
        precondition(legacyAttempt == nil)
        legacy.coordinator.fence()
        print("PASS: RETURN recovery identity, restart, uncertain retry, expiry, refusal, legacy and queued TAKE")
    }
}
