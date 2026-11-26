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
    var metadataTransport: (any TakeMetadataTransport)?
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
            authentication: auth, transport: transport, directory: root.appendingPathComponent("uploads"), metadataTransport: metadataTransport, now: { [unowned self] in self.clock }, retryWait: retryWait)
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

@MainActor private final class MetadataUnavailableTransport: TakeMetadataTransport {
    var requests: [TakeMetadataRequest] = []
    func fetch(_ request:TakeMetadataRequest,device:UUID,token:String) async throws -> TakeMetadataSnapshot {
        requests.append(request)
        return .init(request_id:request.request_id,device_ref:device,projection_revision:1,last_processed_sequence:1000,
            observed_at:String(format:"2026-11-24T00:00:%02dZ",requests.count),items:request.takes.map {
                .init(event_id:$0.event_id,device_sequence:$0.device_sequence,vehicle_ref:$0.vehicle_ref,status:"unavailable",anchor_event_id:nil,session_ref:nil,session_state:nil,closed_at:nil,closure_kind:nil,reconciliation_operation_id:nil,finality:nil)
            })
    }
}

@MainActor private final class MetadataProbe: TakeMetadataTransport {
    var requests: [TakeMetadataRequest] = []
    var completion: CheckedContinuation<TakeMetadataSnapshot, any Error>?
    func fetch(_ request: TakeMetadataRequest, device: UUID, token: String) async throws -> TakeMetadataSnapshot {
        requests.append(request)
        return try await withCheckedThrowingContinuation { completion=$0 }
    }
}

// Blocking semaphore waits belong to a dedicated OS thread, not Swift's async executor.
private func awaitNativeTestSignal(_ signal: DispatchSemaphore) async {
    await withCheckedContinuation { continuation in
        Thread.detachNewThread {
            signal.wait()
            continuation.resume()
        }
    }
}

// A real independent SQLite connection holds the write lock on an OS thread.
private final class HeldNativeWriteLock: @unchecked Sendable {
    private let release = DispatchSemaphore(value: 0)
    private let finished = DispatchSemaphore(value: 0)
    init(_ directory: URL) {
        let ready = DispatchSemaphore(value: 0)
        let path = directory.appendingPathComponent("vehicle-events.sqlite").path
        Thread.detachNewThread { [self] in
            var db: OpaquePointer?
            precondition(sqlite3_open(path, &db) == SQLITE_OK)
            precondition(sqlite3_exec(db, "BEGIN IMMEDIATE", nil, nil, nil) == SQLITE_OK)
            ready.signal()
            release.wait()
            precondition(sqlite3_exec(db, "COMMIT", nil, nil, nil) == SQLITE_OK)
            sqlite3_close_v2(db)
            finished.signal()
        }
        ready.wait()
    }
    func unlock() { release.signal(); finished.wait() }
}

@main struct VehicleSyncChecks {
    @MainActor static func main() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("fca-sync-check-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        func fixture() async throws -> SyncFixture {
            let f = try SyncFixture(root: root.appendingPathComponent(UUID().uuidString))
            try await f.start(); return f
        }
        try await nativeReturnSemanticChecks(root: root)
        // Native acquisition wait is simulated between read-only preparation and atomic commit.
        let native = try await fixture()
        native.namespace = UUID()
        let nativeTake = try await native.take()
        let nativePermit = VehicleRecordingPermit()
        let preparation = try await native.queue.prepareReturn(native.context, vehicle: nativeTake.vehicle, namespace: native.namespace!)
        let beforeWait = try await native.queue.records(native.context)
        precondition(beforeWait.map(\.event) == [nativeTake])
        let decision = native.clock.addingTimeInterval(12)
        let evidence = VehicleLocationEvidence(latitude: 32, longitude: 34, accuracy: 10, measuredAt: native.clock.addingTimeInterval(10))
        let nativeReturn = try await native.queue.commitReturn(preparation, time: decision, location: evidence, permit: nativePermit)
        precondition(nativeReturn.sequence == 2 && nativeReturn.takeID == nativeTake.id)
        precondition(nativeReturn.occurredAt == decision && nativeReturn.location == evidence)
        // A second process holding the same old snapshot cannot insert a duplicate.
        let secondWriter = try VehicleEventQueue(directory: native.root.appendingPathComponent("db"))
        do {
            _ = try await secondWriter.commitReturn(preparation, time: decision, location: evidence, permit: nativePermit)
            preconditionFailure("Concurrent RETURN must not allocate a sequence")
        } catch { }
        let nextTake = try await native.queue.recordShortcut(native.context, vehicle: nativeTake.vehicle, kind: .take, time: decision, location: nil)
        precondition(nextTake.sequence == 3)
        do {
            _ = try await secondWriter.commitReturn(preparation, time: decision, location: evidence, permit: nativePermit)
            preconditionFailure("Delayed RETURN must not close a different TAKE")
        } catch { }
        let nextPreparation = try await native.queue.prepareReturn(native.context, vehicle: nativeTake.vehicle, namespace: native.namespace!)
        do {
            _ = try await native.queue.commitReturn(nextPreparation, time: decision.addingTimeInterval(31), location: evidence, permit: nativePermit)
            preconditionFailure("Evidence must be fresh at the final recording time")
        } catch { }
        let unchanged = try await native.queue.records(native.context)
        precondition(unchanged.map(\.event) == [nativeTake,nativeReturn,nextTake])
        try VehicleEventQueue.revokeAuthorization(directory: native.root.appendingPathComponent("db"), context: native.context)
        do {
            _ = try await native.queue.commitReturn(nextPreparation, time: decision, location: evidence, permit: nativePermit)
            preconditionFailure("Revoked cross-process context must not record")
        } catch { }
        let afterRevocation = try await native.queue.records(native.context)
        precondition(afterRevocation.map(\.event) == unchanged.map(\.event))
        print("PASS: native RETURN preparation, final timestamps, concurrent writers, changed TAKE, freshness and revocation")
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
            precondition(after == before && version == [["5"]] && recoveryRows.isEmpty)
        }
        print("PASS: SQLite v2 to v5 preserves payloads, IDs, ordering, states, blocked RETURN and idempotent reopening")

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

        try await recoveryChecks(root: root)
        try await reconciliationHardening(root: root)
        try await metadataChecks(root: root)
    }
    @MainActor private static func recoveryChecks(root: URL) async throws {
        func fixture() async throws -> SyncFixture {
            let f = try SyncFixture(root: root.appendingPathComponent(UUID().uuidString))
            try await f.start(); return f
        }
        let accepted = #"{"kind":"accepted","admission_outcome":"accepted","transition":"redundant_take"}"#
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
            if ReturnRecoveryPolicy.renewable.contains(code) || code == "RETURN_RECOVERY_ORDER_CONFLICT" {
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
        // Finalization is proven only by the server. ORDER_CONFLICT permits a
        // separate explicit request, never changes original evidence locally.
        let (cf, ce) = try await rejectedReturn()
        try await explicitReturn(cf, ce)
        await cf.coordinator.wake()
        await cf.coordinator.receive(cf.transport.finish(3, status: 409, body: "{\"detail\":{\"code\":\"RETURN_RECOVERY_ORDER_CONFLICT\"}}"))
        try await explicitReturn(cf, ce)
        let cr = try await cf.queue.recovery(cf.context, event: ce.id)!
        precondition(cr.reconciliation)
        let nextTake = try await cf.queue.enqueueTake(cf.context, vehicle: ce.vehicle, occurredAt: cf.clock.addingTimeInterval(1))
        let nextReturn = try await cf.queue.enqueueReturn(cf.context, vehicle: ce.vehicle, occurredAt: cf.clock.addingTimeInterval(2),
            takeID: nextTake.id, location: .init(latitude: 32, longitude: 34, accuracy: 10, measuredAt: cf.clock.addingTimeInterval(2)))
        try await explicitReturn(cf, ce)
        let crAgain = try await cf.queue.recovery(cf.context, event: ce.id)!
        precondition(cr.id == crAgain.id && cr.payload == crAgain.payload)
        let restarted = try VehicleEventQueue(directory: cf.root.appendingPathComponent("db"))
        let restored = try await restarted.recovery(cf.context, event: ce.id)!
        precondition(restored.reconciliation && restored.payload == cr.payload)
        await cf.coordinator.wake()
        precondition(cf.transport.created.last!.request.url!.path.hasSuffix("/reconciliation"))
        await cf.coordinator.receive(cf.transport.finish(4, status: nil, failed: true))
        let uncertain = try await cf.queue.recovery(cf.context, event: ce.id)!
        precondition(uncertain.id == cr.id && uncertain.payload == cr.payload)
        cf.clock.addTimeInterval(180)
        await cf.coordinator.wake()
        let resolution = "{\"kind\":\"resolved_current_state\",\"event_id\":\"\(ce.id)\",\"reconciliation_id\":\"\(cr.id)\",\"operation_id\":\"\(UUID())\",\"device_sequence\":2,\"last_processed_sequence\":2,\"historical_receipt\":{\"kind\":\"terminal\",\"admission_outcome\":\"before_finalized_boundary\"},\"effective_at\":\"2026-11-23T14:06:00Z\",\"session_effect\":\"closed_linked_session\"}"
        await cf.coordinator.receive(cf.transport.finish(5, body: resolution))
        let resolvedRows = try await cf.queue.records(cf.context)
        precondition(resolvedRows[1].event == ce && resolvedRows[1].state == .terminal)
        precondition(resolvedRows[1].reason == "resolved_current_state")
        precondition(resolvedRows.map { $0.event.sequence } == [1, 2, 3, 4])
        precondition(resolvedRows[2].event == nextTake && resolvedRows[3].event == nextReturn)
        precondition(cf.transport.created.count == 6) // Ordered next TAKE starts only after acknowledgment.
        cf.coordinator.fence()
        let acknowledgment = try migrationRows(cf.root.appendingPathComponent("db"), "SELECT acknowledgment FROM return_reconciliations")
        precondition(acknowledgment.count == 1 && acknowledgment[0][0]?.contains("resolved_current_state") == true)
        // A real v3 database with an existing blocked recovery upgrades without
        // recreating event evidence or its in-flight immutable payload.
        let (v3f, v3e) = try await rejectedReturn()
        try await explicitReturn(v3f, v3e)
        let v3attempt = try await v3f.queue.recovery(v3f.context, event: v3e.id)!
        let v3dir = v3f.root.appendingPathComponent("db")
        try rejectionSQL(v3dir, "DROP TRIGGER return_recoveries_exclusive_INSERT; DROP TRIGGER return_recoveries_exclusive_UPDATE; DROP TABLE return_reconciliations; PRAGMA user_version=3;")
        let migratedV3 = try VehicleEventQueue(directory: v3dir)
        let v3restored = try await migratedV3.recovery(v3f.context, event: v3e.id)!
        precondition(v3restored.payload == v3attempt.payload && v3restored.id == v3attempt.id)
        let v3rows = try await migratedV3.records(v3f.context)
        precondition(v3rows[1].event == v3e && v3rows[1].state == .blocked)
        _ = try VehicleEventQueue(directory: v3dir)
        let upgradedVersion = try migrationRows(v3dir, "PRAGMA user_version")
        precondition(upgradedVersion == [["5"]])
        v3f.coordinator.fence()
        // Expiry requires an explicit new invocation. It never rewrites a task.
        let (ef, ee) = try await rejectedReturn()
        try await explicitReturn(ef, ee)
        await ef.coordinator.wake()
        await ef.coordinator.receive(ef.transport.finish(3, status: 409, body: "{\"detail\":{\"code\":\"RETURN_RECOVERY_ORDER_CONFLICT\"}}"))
        try await explicitReturn(ef, ee)
        let beforeExpiry = try await ef.queue.recovery(ef.context, event: ee.id)!
        await ef.coordinator.wake()
        await ef.coordinator.receive(ef.transport.finish(4, status: 409, body: "{\"detail\":{\"code\":\"RETURN_RECONCILIATION_VERIFICATION_EXPIRED\"}}"))
        await ef.coordinator.wake()
        precondition(ef.transport.created.count == 4)
        try await explicitReturn(ef, ee)
        let afterExpiry = try await ef.queue.recovery(ef.context, event: ee.id)!
        precondition(afterExpiry.reconciliation && afterExpiry.id != beforeExpiry.id)
        ef.coordinator.fence()
        print("PASS: current-state reconciliation immutable identity, restart, lost response and atomic terminal acknowledgment")
        print("PASS: RETURN recovery identity, restart, uncertain retry, expiry, refusal, legacy and queued TAKE")
    }


    @MainActor private static func reconciliationHardening(root: URL) async throws {
        let accepted = #"{"kind":"accepted","admission_outcome":"accepted","transition":"redundant_take"}"#
        func explicit(_ f: SyncFixture, _ e: QueuedVehicleEvent) async throws {
            f.clock.addTimeInterval(1)
            let returned = try await f.queue.recordShortcut(f.context, vehicle: e.vehicle, kind: .returning,
                time: f.clock, location: .init(latitude: 32, longitude: 34, accuracy: 10, measuredAt: f.clock))
            precondition(returned == e)
        }
        func prepared(productionSequence: Bool = false) async throws -> (SyncFixture, QueuedVehicleEvent, VehicleRecoveryRecord) {
            let f = try SyncFixture(root: root.appendingPathComponent(UUID().uuidString))
            try await f.start()
            let vehicle = UUID()
            // Six accepted synthetic pairs precede the sanitized Production 13/14 fixture.
            if productionSequence {
                for _ in 0..<6 {
                    let t = try await f.take(vehicle: vehicle)
                    await f.coordinator.wake()
                    await f.coordinator.receive(f.transport.finish(f.transport.created.last!.task.identifier, body: accepted))
                    _ = try await f.queue.enqueueReturn(f.context, vehicle: vehicle, occurredAt: f.clock, takeID: t.id,
                        location: .init(latitude: 32, longitude: 34, accuracy: 10, measuredAt: f.clock))
                    await f.coordinator.wake()
                    await f.coordinator.receive(f.transport.finish(f.transport.created.last!.task.identifier, body: accepted))
                }
            }
            let verification = try await f.queue.beginVerification(f.context)
            try await f.queue.completeVerification(f.context, generation: verification, vehicles: [vehicle])
            let t = try await f.queue.enqueueTake(f.context,
                id: UUID(uuidString: "37765bae-39c3-4cea-bd53-10e30f2c7913")!, vehicle: vehicle, occurredAt: f.clock)
            await f.coordinator.wake()
            await f.coordinator.receive(f.transport.finish(f.transport.created.last!.task.identifier, body: accepted))
            f.clock.addTimeInterval(10)
            let e = try await f.queue.enqueueReturn(f.context,
                id: UUID(uuidString: "07e91a49-bc53-4a33-8c41-f9c2b310fd28")!, vehicle: vehicle, occurredAt: f.clock, takeID: t.id,
                location: .init(latitude: 32, longitude: 34, accuracy: 10, measuredAt: f.clock))
            await f.coordinator.wake()
            await f.coordinator.receive(f.transport.finish(f.transport.created.last!.task.identifier, status: 409,
                body: #"{"detail":{"code":"RETURN_OUTSIDE_HOME"}}"#))
            try await explicit(f, e)
            do {
                try rejectionSQL(f.root.appendingPathComponent("db"), "INSERT INTO return_reconciliations(id,event,payload,state) VALUES('overlap','\(e.id.uuidString)','{}','preparing');")
                preconditionFailure("Concurrent reconciliation allowed")
            } catch VehicleQueueError.storage {}
            await f.coordinator.wake()
            await f.coordinator.receive(f.transport.finish(f.transport.created.last!.task.identifier, status: 409,
                body: #"{"detail":{"code":"RETURN_RECOVERY_ORDER_CONFLICT"}}"#))
            try await explicit(f, e)
            return (f, e, try await f.queue.recovery(f.context, event: e.id)!)
        }
        func response(_ e: QueuedVehicleEvent, _ r: VehicleRecoveryRecord, change: String? = nil) throws -> String {
            var body: [String: Any] = ["kind": "resolved_current_state", "event_id": e.id.uuidString,
                "reconciliation_id": r.id.uuidString, "operation_id": UUID().uuidString,
                "device_sequence": e.sequence, "last_processed_sequence": e.sequence,
                "historical_receipt": ["kind": "terminal", "admission_outcome": "before_finalized_boundary"],
                "effective_at": "2026-11-23T14:06:00Z", "session_effect": "closed_linked_session"]
            if change == "event_id" { body["event_id"] = UUID().uuidString }
            if change == "device_sequence" || change == "last_processed_sequence" { body[change!] = e.sequence + 1 }
            if change == "canonical" { body["reconciliation_id"] = UUID().uuidString }
            return String(decoding: try JSONSerialization.data(withJSONObject: body, options: [.sortedKeys]), as: UTF8.self)
        }
        func unchanged(_ f: SyncFixture, _ e: QueuedVehicleEvent, _ r: VehicleRecoveryRecord) async throws {
            let q = try VehicleEventQueue(directory: f.root.appendingPathComponent("db"))
            let rows = try await q.records(f.context)
            precondition(rows.first(where: { $0.event.id == e.id })?.state == .blocked)
            precondition(rows.first(where: { $0.event.id == e.id })?.event == e)
            let task = try await q.recovery(f.context, event: e.id)!
            precondition(task.id == r.id && task.payload == r.payload && task.state != .accepted)
            let ack = try migrationRows(f.root.appendingPathComponent("db"), "SELECT acknowledgment FROM return_reconciliations")
            precondition(ack == [[nil]])
        }
        // Independent schema copied from the shipping v3 source, not obtained by downgrading v4.
        let dir = root.appendingPathComponent("independent-v3")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try rejectionSQL(dir, """
            CREATE TABLE IF NOT EXISTS devices(context TEXT PRIMARY KEY,environment TEXT NOT NULL,device TEXT NOT NULL,last_sequence INTEGER NOT NULL CHECK(last_sequence>=0),active INTEGER NOT NULL CHECK(active IN(0,1)),UNIQUE(environment,device));
            CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,context TEXT NOT NULL REFERENCES devices(context),sequence INTEGER NOT NULL CHECK(sequence>0),vehicle TEXT NOT NULL,cause TEXT REFERENCES events(id),payload TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('pending','preparing','registered','awaitingAuthentication','accepted','terminal','blocked')),attempt TEXT,session TEXT,task INTEGER,reason TEXT,UNIQUE(context,sequence),UNIQUE(context,cause));
            CREATE TABLE IF NOT EXISTS authorization_scopes(context TEXT PRIMARY KEY REFERENCES devices(context),generation TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('verificationPending','verified','revoked')),namespace TEXT);
            CREATE TABLE IF NOT EXISTS vehicle_authorizations(context TEXT NOT NULL REFERENCES authorization_scopes(context),vehicle TEXT NOT NULL,allowed INTEGER NOT NULL CHECK(allowed IN(0,1)),PRIMARY KEY(context,vehicle));
            CREATE TABLE IF NOT EXISTS return_recoveries(id TEXT PRIMARY KEY,event TEXT NOT NULL REFERENCES events(id),payload TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('preparing','registered','awaitingAuthentication','blocked','accepted')),session TEXT,task INTEGER,reason TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS return_recovery_active ON return_recoveries(event) WHERE state IN('preparing','registered','awaitingAuthentication');
            CREATE TRIGGER IF NOT EXISTS return_recovery_immutable BEFORE UPDATE OF id,event,payload ON return_recoveries BEGIN SELECT RAISE(ABORT,'immutable recovery'); END;
            PRAGMA user_version=3;
            INSERT INTO devices VALUES('fixture-context','fixture-environment','fixture-device',16,1);
            INSERT INTO authorization_scopes VALUES('fixture-context','fixture-generation','verified','fixture-namespace');
            INSERT INTO vehicle_authorizations VALUES('fixture-context','00000000-0000-4000-8000-000000000002',1);
            INSERT INTO events VALUES('37765BAE-39C3-4CEA-BD53-10E30F2C7913','fixture-context',13,'00000000-0000-4000-8000-000000000002',NULL,'{"id":"37765BAE-39C3-4CEA-BD53-10E30F2C7913","vehicle":"00000000-0000-4000-8000-000000000002","sequence":13,"occurredAt":100,"kind":"take"}','accepted',NULL,NULL,NULL,'accepted');
            INSERT INTO events VALUES('07E91A49-BC53-4A33-8C41-F9C2B310FD28','fixture-context',14,'00000000-0000-4000-8000-000000000002','37765BAE-39C3-4CEA-BD53-10E30F2C7913','{"id":"07E91A49-BC53-4A33-8C41-F9C2B310FD28","vehicle":"00000000-0000-4000-8000-000000000002","sequence":14,"occurredAt":110,"kind":"return","takeID":"37765BAE-39C3-4CEA-BD53-10E30F2C7913","location":{"latitude":32,"longitude":34,"accuracy":10,"measuredAt":110}}','blocked',NULL,NULL,NULL,'RETURN_OUTSIDE_HOME');
            INSERT INTO events VALUES('00000000-0000-4000-8000-000000000015','fixture-context',15,'00000000-0000-4000-8000-000000000002',NULL,'{"id":"00000000-0000-4000-8000-000000000015","vehicle":"00000000-0000-4000-8000-000000000002","sequence":15,"occurredAt":120,"kind":"take"}','registered','00000000-0000-4000-8000-000000000043','background-session',42,NULL);
            INSERT INTO events VALUES('00000000-0000-4000-8000-000000000016','fixture-context',16,'00000000-0000-4000-8000-000000000002','00000000-0000-4000-8000-000000000015','{"id":"00000000-0000-4000-8000-000000000016","vehicle":"00000000-0000-4000-8000-000000000002","sequence":16,"occurredAt":130,"kind":"return","takeID":"00000000-0000-4000-8000-000000000015","location":{"latitude":32,"longitude":34,"accuracy":10,"measuredAt":130}}','pending',NULL,NULL,NULL,NULL);
            INSERT INTO return_recoveries VALUES('00000000-0000-4000-8000-000000000041','07E91A49-BC53-4A33-8C41-F9C2B310FD28','{"recovery_id":"00000000-0000-4000-8000-000000000041","original_return":{"event_id":"07E91A49-BC53-4A33-8C41-F9C2B310FD28","vehicle_ref":"00000000-0000-4000-8000-000000000002","device_sequence":14,"occurred_at":"2001-01-01T00:01:50Z","take_event_id":"37765BAE-39C3-4CEA-BD53-10E30F2C7913","latitude":32,"longitude":34,"accuracy_m":10,"location_at":"2001-01-01T00:01:50Z"},"verification":{"invoked_at":"2001-01-01T00:02:00Z","location_at":"2001-01-01T00:02:00Z","latitude":32,"longitude":34,"accuracy_m":10}}','blocked',NULL,NULL,'RETURN_OUTSIDE_HOME');
            INSERT INTO return_recoveries VALUES('00000000-0000-4000-8000-000000000042','07E91A49-BC53-4A33-8C41-F9C2B310FD28','{"recovery_id":"00000000-0000-4000-8000-000000000042","original_return":{"event_id":"07E91A49-BC53-4A33-8C41-F9C2B310FD28","vehicle_ref":"00000000-0000-4000-8000-000000000002","device_sequence":14,"occurred_at":"2001-01-01T00:01:50Z","take_event_id":"37765BAE-39C3-4CEA-BD53-10E30F2C7913","latitude":32,"longitude":34,"accuracy_m":10,"location_at":"2001-01-01T00:01:50Z"},"verification":{"invoked_at":"2001-01-01T00:02:00Z","location_at":"2001-01-01T00:02:00Z","latitude":32,"longitude":34,"accuracy_m":10}}','registered','background-session',43,NULL);
            """)
        let tables = ["devices", "events", "authorization_scopes", "vehicle_authorizations", "return_recoveries"]
        let before = try tables.map { try migrationRows(dir, "SELECT * FROM \($0) ORDER BY 1") }
        for _ in 0..<2 {
            _ = try VehicleEventQueue(directory: dir)
            let after = try tables.map { try migrationRows(dir, "SELECT * FROM \($0) ORDER BY 1") }
            precondition(before == after)
            let payloads = try migrationRows(dir, "SELECT payload FROM events ORDER BY sequence")
            let events = try payloads.map { try JSONDecoder().decode(QueuedVehicleEvent.self, from: Data($0[0]!.utf8)) }
            precondition(events.map(\.sequence) == [13, 14, 15, 16])
            precondition(events[1].takeID == events[0].id && events[3].takeID == events[2].id)
            let version = try migrationRows(dir, "PRAGMA user_version")
            let tasks = try migrationRows(dir, "SELECT * FROM return_reconciliations")
            precondition(version == [["5"]] && tasks.isEmpty)
        }
        print("PASS: independent v3 schema, all rows/upload mappings preserved, v5 reopen/idempotency")

        for fault in ["between-writes", "commit"] {
            let (f, e, r) = try await prepared()
            let db = f.root.appendingPathComponent("db")
            if fault == "between-writes" {
                try rejectionSQL(db, "CREATE TRIGGER fail_terminal BEFORE UPDATE OF state ON events WHEN NEW.state='terminal' BEGIN SELECT RAISE(ABORT,'test fault'); END;")
            } else {
                // The last write succeeds; deferred FK is checked only by COMMIT.
                try rejectionSQL(db, "CREATE TABLE fault_parent(id INTEGER PRIMARY KEY); CREATE TABLE fault_child(id INTEGER REFERENCES fault_parent(id) DEFERRABLE INITIALLY DEFERRED); CREATE TRIGGER fail_commit AFTER UPDATE OF state ON events WHEN NEW.state='terminal' BEGIN INSERT INTO fault_child VALUES(99); END;")
            }
            do {
                try await f.queue.updateRecovery(f.context, event: e.id, id: r.id, state: .accepted, acknowledgment: response(e, r))
                preconditionFailure("Injected transaction failure did not fail")
            } catch VehicleQueueError.storage {}
            try await unchanged(f, e, r)
            let oldRows = try migrationRows(db, "SELECT state FROM return_reconciliations")
            precondition(oldRows == [["preparing"]])
            if fault == "commit" {
                let rows = try migrationRows(db, "SELECT * FROM fault_child")
                precondition(rows.isEmpty)
            }
            try rejectionSQL(db, "DROP TRIGGER \(fault == "commit" ? "fail_commit" : "fail_terminal");")
            await f.coordinator.wake()
            await f.coordinator.receive(f.transport.finish(f.transport.created.last!.task.identifier, body: try response(e, r)))
            let resolved = try await f.states(); precondition(resolved == [.accepted, .terminal])
            f.coordinator.fence()
        }
        print("PASS: acknowledgment/terminal write rollback and deferred-constraint COMMIT rollback; retry succeeds")

        for invalid in ["event_id", "device_sequence", "last_processed_sequence", "malformed", "stale"] {
            let (f, e, r) = try await prepared()
            await f.coordinator.wake()
            let count = f.transport.created.count
            if invalid == "stale" {
                await f.coordinator.receive(f.transport.finish(3, body: try response(e, r)))
            } else {
                let body = invalid == "malformed" ? "not-json" : try response(e, r, change: invalid)
                await f.coordinator.receive(f.transport.finish(f.transport.created.last!.task.identifier, body: body))
            }
            try await unchanged(f, e, r)
            precondition(f.transport.created.count == count)
            f.coordinator.fence()
        }
        print("PASS: five invalid/stale response cases never acknowledge or release RETURN")

        let (f, e, r) = try await prepared(productionSequence: true)
        precondition(e.sequence == 14)
        var following: [QueuedVehicleEvent] = []
        for _ in 0..<3 {
            f.clock.addTimeInterval(1)
            let t = try await f.queue.enqueueTake(f.context, vehicle: e.vehicle, occurredAt: f.clock)
            let ret = try await f.queue.enqueueReturn(f.context, vehicle: e.vehicle, occurredAt: f.clock,
                takeID: t.id, location: .init(latitude: 32, longitude: 34, accuracy: 10, measuredAt: f.clock))
            following.append(contentsOf: [t, ret])
        }
        await f.coordinator.wake()
        let initialTask = f.transport.created.last!.task.identifier
        let count = f.transport.created.count
        try f.restoreCoordinator()
        await f.coordinator.wake()
        precondition(f.transport.created.count == count && f.transport.tasks.count == 1)
        // SQL-level mutual exclusion, in both directions, not only an actor guard.
        let db = f.root.appendingPathComponent("db")
        do {
            try rejectionSQL(db, "INSERT INTO return_recoveries(id,event,payload,state) VALUES('overlap','\(e.id.uuidString)','{}','preparing');")
            preconditionFailure("Concurrent recovery allowed")
        } catch VehicleQueueError.storage {}
        await f.coordinator.receive(f.transport.finish(initialTask, status: 503,
            body: #"{"detail":{"code":"RETURN_RECONCILIATION_DISABLED"}}"#))
        try await unchanged(f, e, r)
        try await explicit(f, e)
        precondition(f.transport.created.count == count)
        f.clock.addTimeInterval(180)
        try f.restoreCoordinator()
        await f.coordinator.wake()
        precondition(f.transport.created.last!.bytes == r.payload)
        // Simulate server commit followed by a lost acknowledgment, then restart with no OS task.
        await f.coordinator.receive(f.transport.finish(f.transport.created.last!.task.identifier, status: nil, failed: true))
        f.clock.addTimeInterval(180)
        try f.restoreCoordinator()
        try await unchanged(f, e, r)
        await f.coordinator.wake()
        precondition(f.transport.created.last!.bytes == r.payload)
        let canonical = try response(e, r, change: "canonical")
        await f.coordinator.receive(f.transport.finish(f.transport.created.last!.task.identifier, body: canonical))
        let reopened = try VehicleEventQueue(directory: db)
        var rows = try await reopened.records(f.context)
        precondition(rows[13].event == e && rows[13].state == .terminal && rows[13].reason == "resolved_current_state")
        precondition(Array(rows.suffix(6)).map(\.event) == following)
        for event in following {
            let sent = f.transport.created.last!
            let expectedBytes = try VehicleEventWire.encode(event)
            precondition(sent.bytes == expectedBytes)
            await f.coordinator.receive(f.transport.finish(sent.task.identifier, body: accepted))
        }
        rows = try await reopened.records(f.context)
        precondition(rows.map { $0.event.sequence } == Array(Int64(1)...20))
        precondition(rows.enumerated().allSatisfy { $0.offset == 13 ? $0.element.state == .terminal : $0.element.state == .accepted })
        precondition(Array(rows.suffix(6)).map(\.event) == following && f.transport.tasks.isEmpty)
        let ack = try migrationRows(db, "SELECT acknowledgment FROM return_reconciliations")
        precondition(ack == [[canonical]])
        f.coordinator.fence()
        print("PASS: Production 13/14 fixture, 15...20 ordered pairs, restored upload, disabled flag, lost response, canonical acknowledgment")

        let (ef, ee, er) = try await prepared()
        await ef.coordinator.wake()
        await ef.coordinator.receive(ef.transport.finish(ef.transport.created.last!.task.identifier, status: 409,
            body: #"{"detail":{"code":"RETURN_RECONCILIATION_VERIFICATION_EXPIRED"}}"#))
        let expired = try await ef.queue.recovery(ef.context, event: ee.id)!
        if case .locationExpired? = ReturnRecoveryPolicy.shortcutFailure(expired) {} else { preconditionFailure() }
        let n = ef.transport.created.count
        try ef.restoreCoordinator(); await ef.coordinator.wake()
        precondition(ef.transport.created.count == n)
        try await explicit(ef, ee)
        let fresh = try await ef.queue.recovery(ef.context, event: ee.id)!
        precondition(fresh.id != er.id && fresh.payload != er.payload)
        ef.coordinator.fence()
        for reason in ["RETURN_RECONCILIATION_SEQUENCE_CONFLICT", "authorizationRejected", "unrecognizedRecoveryRejection"] {
            let blocked = VehicleRecoveryRecord(id: er.id, event: ee.id, payload: er.payload, state: .blocked, session: nil, task: nil, reason: reason, reconciliation: true)
            if case .recoveryBlocked? = ReturnRecoveryPolicy.shortcutFailure(blocked) {} else { preconditionFailure() }
        }
        let stored = VehicleRecoveryRecord(id: er.id, event: ee.id, payload: er.payload, state: .preparing, session: nil, task: nil, reason: "deliveryUnknown", reconciliation: true)
        if case .retryStored? = ReturnRecoveryPolicy.shortcutFailure(stored) {} else { preconditionFailure() }
        print("PASS: expiry requires explicit fresh evidence; retryable/permanent Shortcut message classification")
    }


    @MainActor private static func nativeReturnSemanticChecks(root: URL) async throws {
        func fixture() async throws -> (SyncFixture, QueuedVehicleEvent) {
            let f = try SyncFixture(root: root.appendingPathComponent(UUID().uuidString))
            try await f.start(); f.namespace = UUID(); f.clock = Date().addingTimeInterval(-60)
            return (f, try await f.take())
        }
        func prepare(_ f: SyncFixture, _ take: QueuedVehicleEvent) async throws -> VehicleReturnPreparation {
            try await f.queue.prepareReturn(f.context, vehicle: take.vehicle, namespace: f.namespace!)
        }
        func commit(_ f: SyncFixture, _ p: VehicleReturnPreparation) async throws -> QueuedVehicleEvent {
            try await f.queue.commitReturn(p, location: .init(latitude: 32, longitude: 34, accuracy: 10, measuredAt: Date()), permit: VehicleRecordingPermit())
        }
        func metadata(_ f: SyncFixture, _ take: QueuedVehicleEvent, anchor: UUID, session: UUID, closed: Bool = false, revision: Int64 = 1) async throws {
            let all = try await f.queue.metadataBatch(f.context)!
            let batch = TakeMetadataBatch(request: .init(request_id: UUID(), takes: all.request.takes.filter { $0.event_id == take.id }), authorization: all.authorization)
            let item = TakeSessionMetadata(event_id: take.id, device_sequence: take.sequence, vehicle_ref: take.vehicle,
                status: "accepted", anchor_event_id: anchor, session_ref: session, session_state: closed ? "closed" : "open",
                closed_at: closed ? "2026-11-24T00:00:00Z" : nil, closure_kind: closed ? "return" : nil,
                reconciliation_operation_id: nil, finality: "provisional")
            try await f.queue.applyMetadata(f.context, batch: batch, snapshot: .init(request_id: batch.request.request_id,
                device_ref: f.context.device, projection_revision: revision, last_processed_sequence: 100,
                observed_at: "2026-11-24T00:00:0\(revision)Z", items: [item]))
        }
        let accepted = #"{"kind":"accepted","admission_outcome":"accepted"}"#
        for finish in [false, true] {
            let (f,t) = try await fixture(); let p = try await prepare(f,t)
            await f.coordinator.wake()
            if finish { await f.coordinator.receive(f.transport.finish(1,body:accepted)) }
            let r = try await commit(f,p)
            precondition(r.takeID == t.id && r.sequence == 2)
            f.coordinator.fence()
        }
        // Unknown -> self-anchor is safe; unknown -> another logical anchor is not.
        for same in [true,false] {
            let (f,t) = try await fixture(); let p = try await prepare(f,t)
            await f.coordinator.wake(); await f.coordinator.receive(f.transport.finish(1,body:accepted))
            try await metadata(f,t,anchor:same ? t.id : UUID(),session:UUID())
            if same { let r = try await commit(f,p); precondition(r.takeID == t.id) }
            else { do { _ = try await commit(f,p); preconditionFailure() } catch ShortcutQueueError.contextChanged {} }
            f.coordinator.fence()
        }
        for closed in [true,false] {
            let (f,t) = try await fixture()
            await f.coordinator.wake(); await f.coordinator.receive(f.transport.finish(1,body:accepted))
            let session = UUID()
            try await metadata(f,t,anchor:t.id,session:session)
            let p = try await prepare(f,t)
            try await metadata(f,t,anchor:closed ? t.id : UUID(),session:session,closed:closed,revision:2)
            do { _ = try await commit(f,p); preconditionFailure() }
            catch ShortcutQueueError.contextChanged {} catch ShortcutQueueError.noUniqueTake {}
            f.coordinator.fence()
        }
        let (unrelated,t) = try await fixture()
        let other = try await unrelated.take()
        await unrelated.coordinator.wake(); await unrelated.coordinator.receive(unrelated.transport.finish(1,body:accepted))
        await unrelated.coordinator.receive(unrelated.transport.finish(2,body:accepted))
        let p = try await prepare(unrelated,t)
        try await metadata(unrelated,other,anchor:other.id,session:UUID())
        try rejectionSQL(unrelated.root.appendingPathComponent("db"), "UPDATE events SET reason='nonsemantic' WHERE id='\(other.id)'")
        let r = try await commit(unrelated,p); precondition(r.takeID == t.id)
        unrelated.coordinator.fence()
        print("PASS: pending/registered/accepted transitions, unrelated metadata/state, self-anchor resolution, closure and remapping")

        for expired in [false,true] {
            let (f,t) = try await fixture(); let p = try await prepare(f,t)
            let db = f.root.appendingPathComponent("db")
            let writer = try VehicleEventQueue(directory:db)
            let lock = HeldNativeWriteLock(db)
            let started = DispatchSemaphore(value:0)
            let measured = Date().addingTimeInterval(expired ? -29 : 0)
            let task = Task.detached {
                started.signal()
                return try await writer.commitReturn(p, location:.init(latitude:32,longitude:34,accuracy:10,measuredAt:measured), permit:VehicleRecordingPermit())
            }
            await awaitNativeTestSignal(started)
            try await Task.sleep(for:.seconds(1.5))
            let released = Date(); lock.unlock()
            if expired {
                do { _ = try await task.value; preconditionFailure("Expired lock-wait evidence accepted") } catch ShortcutQueueError.location {}
                let rows = try await f.queue.records(f.context); precondition(rows.map(\.event) == [t])
                let retry = try await commit(f,p); precondition(retry.sequence == 2)
            } else {
                let result = try await task.value
                precondition(result.occurredAt >= released && result.location?.measuredAt == measured)
                precondition(result.sequence == 2)
            }
        }
        let (race,take) = try await fixture(); let prepared = try await prepare(race,take)
        let dir = race.root.appendingPathComponent("db")
        let one = try VehicleEventQueue(directory:dir), two = try VehicleEventQueue(directory:dir)
        let lock = HeldNativeWriteLock(dir)
        let started = DispatchSemaphore(value:0)
        let evidence = VehicleLocationEvidence(latitude:32,longitude:34,accuracy:10,measuredAt:Date())
        func contender(_ queue:VehicleEventQueue) -> Task<Bool, Error> {
            Task.detached {
                started.signal()
                do { _ = try await queue.commitReturn(prepared,location:evidence,permit:VehicleRecordingPermit()); return true }
                catch ShortcutQueueError.noUniqueTake { return false }
                catch ShortcutQueueError.contextChanged { return false }
            }
        }
        let first = contender(one), second = contender(two)
        await awaitNativeTestSignal(started); await awaitNativeTestSignal(started)
        try await Task.sleep(for:.milliseconds(250)); lock.unlock()
        let wins = try await [first.value,second.value].filter { $0 }.count
        precondition(wins == 1)
        let rows = try await race.queue.records(race.context)
        precondition(rows.count == 2 && rows[1].event.takeID == take.id && rows.map { $0.event.sequence } == [1,2])
        print("PASS: real SQLite write contention, production clock, expiry rollback and competing RETURN transactions")
    }

    @MainActor private static func metadataChecks(root: URL) async throws {
        let f=try SyncFixture(root:root.appendingPathComponent("session-metadata")); try await f.start()
        let vehicle=UUID()
        let accepted = #"{"kind":"accepted","admission_outcome":"accepted"}"#
        func finish() async {
            await f.coordinator.wake()
            await f.coordinator.receive(f.transport.finish(f.transport.created.last!.task.identifier,body:accepted))
        }
        func shortcut(_ kind: QueuedVehicleEvent.Kind) async throws -> QueuedVehicleEvent {
            f.clock.addTimeInterval(1)
            return try await f.queue.recordShortcut(f.context,vehicle:vehicle,kind:kind,time:f.clock,
                location:kind == .returning ? .init(latitude:32,longitude:34,accuracy:10,measuredAt:f.clock) : nil)
        }
        for _ in 0..<6 {
            _=try await f.take(vehicle:vehicle); await finish()
            _=try await shortcut(.returning); await finish()
        }
        let take13=try await shortcut(.take); await finish()
        precondition(take13.sequence == 13)
        let ret14=try await shortcut(.returning)
        await f.coordinator.wake()
        await f.coordinator.receive(f.transport.finish(f.transport.created.last!.task.identifier,status:409,body:#"{"detail":{"code":"RETURN_OUTSIDE_HOME"}}"#))
        let take15=try await shortcut(.take)
        precondition(take15.sequence == 15)
        _=try await shortcut(.returning); await f.coordinator.wake()
        await f.coordinator.receive(f.transport.finish(f.transport.created.last!.task.identifier,status:409,body:#"{"detail":{"code":"RETURN_RECOVERY_ORDER_CONFLICT"}}"#))
        _=try await shortcut(.returning); await f.coordinator.wake()
        let r=try await f.queue.recovery(f.context,event:ret14.id)!
        let ack="{\"kind\":\"resolved_current_state\",\"event_id\":\"\(ret14.id)\",\"reconciliation_id\":\"\(r.id)\",\"operation_id\":\"\(UUID())\",\"device_sequence\":14,\"last_processed_sequence\":14,\"historical_receipt\":{\"kind\":\"terminal\",\"admission_outcome\":\"before_finalized_boundary\"},\"effective_at\":\"2026-11-24T00:00:00Z\",\"session_effect\":\"closed_linked_session\"}"
        await f.coordinator.receive(f.transport.finish(f.transport.created.last!.task.identifier,body:ack))
        await f.coordinator.receive(f.transport.finish(f.transport.created.last!.task.identifier,body:#"{"kind":"accepted","admission_outcome":"accepted","transition":"redundant_take"}"#))
        do { _=try await shortcut(.take); preconditionFailure("Missing metadata cannot clear TAKE15") } catch ShortcutQueueError.alreadyTaken {}
        let historyVehicle=UUID()
        _=try await f.take(vehicle:historyVehicle); await finish()
        _=try await f.queue.recordShortcut(f.context,vehicle:historyVehicle,kind:.returning,time:f.clock,location:.init(latitude:32,longitude:34,accuracy:10,measuredAt:f.clock)); await finish()
        for _ in 0..<70 {
            _=try await f.queue.recordShortcut(f.context,vehicle:historyVehicle,kind:.take,time:f.clock,location:nil); await finish()
            _=try await f.queue.recordShortcut(f.context,vehicle:historyVehicle,kind:.returning,time:f.clock,location:.init(latitude:32,longitude:34,accuracy:10,measuredAt:f.clock)); await finish()
        }
        let original=try await f.queue.records(f.context).map(\.event)
        let batch=try await f.queue.metadataBatch(f.context)!
        precondition(batch.request.takes.count == 64 && batch.request.takes.first?.event_id == take15.id)
        let continuationBatch=try await f.queue.metadataBatch(f.context,excluding:Set(batch.request.takes.map(\.event_id)))!
        precondition(Set(continuationBatch.request.takes.map(\.event_id)).isDisjoint(with:Set(batch.request.takes.map(\.event_id))))
        let session=UUID(), operation=UUID()
        func response(_ batch: TakeMetadataBatch, revision:Int64, closed:Bool=true, finalized:Bool=false) -> TakeMetadataSnapshot {
            .init(request_id:batch.request.request_id,device_ref:f.context.device,projection_revision:revision,last_processed_sequence:1000,
                observed_at:"2026-11-24T00:00:00.123456Z",items:batch.request.takes.map { ref in
                    .init(event_id:ref.event_id,device_sequence:ref.device_sequence,vehicle_ref:ref.vehicle_ref,status:"accepted",
                        anchor_event_id:take13.id,session_ref:session,session_state:closed ? "closed":"open",
                        closed_at:closed ? "2026-11-24T00:00:00.123456Z":nil,closure_kind:closed ? "current_state_reconciliation":nil,
                        reconciliation_operation_id:closed ? operation:nil,finality:finalized ? "finalized":"provisional")
                })
        }
        let db=f.root.appendingPathComponent("db")
        // Trigger abort after metadata row writes proves the entire snapshot rolls back.
        try rejectionSQL(db,"CREATE TRIGGER metadata_fault BEFORE INSERT ON session_metadata_sync BEGIN SELECT RAISE(ABORT,'test'); END;")
        do { try await f.queue.applyMetadata(f.context,batch:batch,snapshot:response(batch,revision:1)); preconditionFailure() } catch VehicleQueueError.storage {}
        let empty=try migrationRows(db,"SELECT * FROM take_session_metadata"); precondition(empty.isEmpty)
        try rejectionSQL(db,"DROP TRIGGER metadata_fault;")
        try await f.queue.applyMetadata(f.context,batch:batch,snapshot:response(batch,revision:1))
        let reopened=try VehicleEventQueue(directory:db)
        let unchanged=try await reopened.records(f.context).map(\.event); precondition(original == unchanged)
        // No network/transport exists on this queue: persisted provisional closure is enough.
        let newTake=try await reopened.recordShortcut(f.context,vehicle:vehicle,kind:.take,time:f.clock.addingTimeInterval(1),location:nil)
        precondition(newTake.sequence == original.last!.sequence+1)
        // A reply requested before the new offline TAKE must never suppress it.
        try await reopened.applyMetadata(f.context,batch:batch,snapshot:response(batch,revision:1))
        do { _=try await shortcut(.take); preconditionFailure("Pending TAKE suppressed") } catch ShortcutQueueError.alreadyTaken {}
        let ret=try await shortcut(.returning); precondition(ret.takeID == newTake.id)
        await finish(); await finish()
        for _ in 0..<2 { _=try await shortcut(.take); await finish(); _=try await shortcut(.returning); await finish() }
        print("PASS: metadata 13/14/15 backfill, real Shortcut offline TAKE after 13/14/15 and >64 history, immutable evidence, pending protection and subsequent pairs")

        // A newer partial snapshot invalidates other provisional entries.
        let partial=TakeMetadataBatch(request:.init(request_id:UUID(),takes:batch.request.takes.filter{$0.event_id == take13.id}),authorization:batch.authorization)
        try await reopened.applyMetadata(f.context,batch:partial,snapshot:response(partial,revision:2))
        do { _=try await shortcut(.take); preconditionFailure("Known stale provisional closure used") } catch ShortcutQueueError.alreadyTaken {}
        do { try await reopened.applyMetadata(f.context,batch:batch,snapshot:response(batch,revision:1)); preconditionFailure() } catch VehicleQueueError.conflict {}
        // A replay can reopen/remap an alias. An open snapshot must protect it.
        try await reopened.applyMetadata(f.context,batch:batch,snapshot:response(batch,revision:3,closed:false))
        do { _=try await shortcut(.take); preconditionFailure() } catch ShortcutQueueError.alreadyTaken {}
        // Alias13 already has RETURN14; group semantics avoid a phantom session.
        // New aliases without pairings group to one logical anchor, permitting one RETURN.
        let otherVehicle=UUID(); let other=try await f.take(vehicle:otherVehicle); await finish()
        let alias=try await f.queue.enqueueTake(f.context,vehicle:otherVehicle,occurredAt:f.clock); await finish()
        let aliases=try await f.queue.metadataBatch(f.context)!
        let aliasBatch=TakeMetadataBatch(request:.init(request_id:UUID(),takes:aliases.request.takes.filter{$0.vehicle_ref == otherVehicle}),authorization:aliases.authorization)
        let items=aliasBatch.request.takes.map { ref in TakeSessionMetadata(event_id:ref.event_id,device_sequence:ref.device_sequence,vehicle_ref:ref.vehicle_ref,status:"accepted",anchor_event_id:other.id,session_ref:UUID(uuidString:"00000000-0000-4000-8000-000000000001")!,session_state:"open",closed_at:nil,closure_kind:nil,reconciliation_operation_id:nil,finality:"provisional") }
        let openSnapshot=TakeMetadataSnapshot(request_id:aliasBatch.request.request_id,device_ref:f.context.device,projection_revision:4,last_processed_sequence:alias.sequence,observed_at:"2026-11-24T00:00:00Z",items:items)
        try await f.queue.applyMetadata(f.context,batch:aliasBatch,snapshot:openSnapshot)
        do { _=try await f.queue.recordShortcut(f.context,vehicle:otherVehicle,kind:.take,time:f.clock,location:nil); preconditionFailure() } catch ShortcutQueueError.alreadyTaken {}
        let linked=try await f.queue.recordShortcut(f.context,vehicle:otherVehicle,kind:.returning,time:f.clock,location:.init(latitude:32,longitude:34,accuracy:10,measuredAt:f.clock))
        precondition([other.id,alias.id].contains(linked.takeID!))
        let afterAliases=try await f.queue.recordShortcut(f.context,vehicle:otherVehicle,kind:.take,time:f.clock,location:nil)
        precondition(afterAliases.sequence == linked.sequence+1)
        do { _=try await f.queue.recordShortcut(f.context,vehicle:otherVehicle,kind:.take,time:f.clock,location:nil); preconditionFailure() } catch ShortcutQueueError.alreadyTaken {}
        print("PASS: stale/out-of-order revisions, replay reopen, multiple vehicles and open aliases grouped for actual RETURN")

        let latest=try await f.queue.metadataBatch(f.context)!
        let good=response(latest,revision:5,finalized:true)
        for bad in [TakeMetadataSnapshot(request_id:UUID(),device_ref:good.device_ref,projection_revision:5,last_processed_sequence:100,observed_at:good.observed_at,items:good.items),TakeMetadataSnapshot(request_id:good.request_id,device_ref:UUID(),projection_revision:5,last_processed_sequence:100,observed_at:good.observed_at,items:good.items)] {
            do { try await f.queue.applyMetadata(f.context,batch:latest,snapshot:bad); preconditionFailure() } catch VehicleQueueError.invalidInput {}
        }
        try await f.queue.applyMetadata(f.context,batch:latest,snapshot:good)
        // Failed/no response cannot reveal an unknown revision while offline.
        let offline=try await f.queue.recordShortcut(f.context,vehicle:vehicle,kind:.take,time:f.clock,location:nil)
        precondition(offline.kind == .take)
        let verify=try await f.queue.beginVerification(f.context)
        try await f.queue.completeVerification(f.context,generation:verify,vehicles:[vehicle,otherVehicle])
        do { try await f.queue.applyMetadata(f.context,batch:latest,snapshot:good); preconditionFailure() } catch VehicleQueueError.invalidInput {}
        f.coordinator.fence()
        print("PASS: snapshot rollback, wrong request/device, authorization generation fence; offline cannot discover unknown server revisions")

        let bounded=try SyncFixture(root:root.appendingPathComponent("metadata-bounded")); try await bounded.start()
        let bt=try await bounded.take()
        for _ in 0..<259 { _=try await bounded.queue.enqueueTake(bounded.context,vehicle:bt.vehicle,occurredAt:bounded.clock) }
        try rejectionSQL(bounded.root.appendingPathComponent("db"),"UPDATE events SET state='accepted';")
        let automatic=MetadataUnavailableTransport(); bounded.metadataTransport=automatic; try bounded.restoreCoordinator()
        await bounded.coordinator.wake()
        for _ in 0..<100000 { if automatic.requests.count == 4 { break }; await Task.yield() }
        precondition(automatic.requests.count == 4 && automatic.requests.allSatisfy{$0.takes.count == 64})
        let visited=automatic.requests.flatMap{$0.takes.map(\.event_id)}
        precondition(Set(visited).count == 256)
        for _ in 0..<100 { await Task.yield() }
        precondition(automatic.requests.count == 4)
        bounded.coordinator.fence()
        print("PASS: actual coordinator bounded backfill, four distinct 64-item batches, no unbounded continuation")

        let ordered=try SyncFixture(root:root.appendingPathComponent("metadata-order")); try await ordered.start()
        let ot=try await ordered.take(); await ordered.coordinator.wake()
        await ordered.coordinator.receive(ordered.transport.finish(1,body:accepted))
        let ob=try await ordered.queue.metadataBatch(ordered.context)!
        let closedItem=TakeSessionMetadata(event_id:ot.id,device_sequence:ot.sequence,vehicle_ref:ot.vehicle,status:"accepted",anchor_event_id:ot.id,session_ref:UUID(),session_state:"closed",closed_at:"2026-11-24T00:00:00Z",closure_kind:"return",reconciliation_operation_id:nil,finality:"provisional")
        let missingItem=TakeSessionMetadata(event_id:ot.id,device_sequence:ot.sequence,vehicle_ref:ot.vehicle,status:"unavailable",anchor_event_id:nil,session_ref:nil,session_state:nil,closed_at:nil,closure_kind:nil,reconciliation_operation_id:nil,finality:nil)
        func orderedResponse(_ item: TakeSessionMetadata, _ time:String) -> TakeMetadataSnapshot {
            .init(request_id:ob.request.request_id,device_ref:ordered.context.device,projection_revision:8,last_processed_sequence:ot.sequence,observed_at:time,items:[item])
        }
        let oc=orderedResponse(closedItem,"2026-11-24T00:00:01Z")
        let ou=orderedResponse(missingItem,"2026-11-24T00:00:02Z")
        try await ordered.queue.applyMetadata(ordered.context,batch:ob,snapshot:oc)
        let second=try VehicleEventQueue(directory:ordered.root.appendingPathComponent("db"))
        // Independent SQLite connections race exactly as app and Shortcut processes do.
        func write(_ q:VehicleEventQueue,_ snapshot:TakeMetadataSnapshot) async throws {
            do { try await q.applyMetadata(ordered.context,batch:ob,snapshot:snapshot) }
            catch VehicleQueueError.conflict {} // The delayed older writer may lose the race.
        }
        async let older:Void=write(ordered.queue,oc)
        async let newer:Void=write(second,ou)
        _=try await (older,newer)
        let restarted=try VehicleEventQueue(directory:ordered.root.appendingPathComponent("db"))
        do { try await restarted.applyMetadata(ordered.context,batch:ob,snapshot:oc); preconditionFailure() } catch VehicleQueueError.conflict {}
        do { try await restarted.applyMetadata(ordered.context,batch:ob,snapshot:orderedResponse(closedItem,ou.observed_at)); preconditionFailure() } catch VehicleQueueError.conflict {}
        try await restarted.applyMetadata(ordered.context,batch:ob,snapshot:ou) // Exact retry is harmless.
        do { _=try await restarted.recordShortcut(ordered.context,vehicle:ot.vehicle,kind:.take,time:ordered.clock,location:nil); preconditionFailure("Unavailable overwritten by old closed") } catch ShortcutQueueError.alreadyTaken {}
        ordered.coordinator.fence()
        print("PASS: equal revision ordering, unavailable survives concurrent SQLite writers/restart, ties fail closed")

        // Literal shipping v4 DDL, independent of the new application initializer.
        let v4dir=root.appendingPathComponent("independent-v4")
        try FileManager.default.createDirectory(at:v4dir,withIntermediateDirectories:true)
        try rejectionSQL(v4dir, """
            CREATE TABLE IF NOT EXISTS devices(context TEXT PRIMARY KEY,environment TEXT NOT NULL,device TEXT NOT NULL,last_sequence INTEGER NOT NULL CHECK(last_sequence>=0),active INTEGER NOT NULL CHECK(active IN(0,1)),UNIQUE(environment,device));
            CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,context TEXT NOT NULL REFERENCES devices(context),sequence INTEGER NOT NULL CHECK(sequence>0),vehicle TEXT NOT NULL,cause TEXT REFERENCES events(id),payload TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('pending','preparing','registered','awaitingAuthentication','accepted','terminal','blocked')),attempt TEXT,session TEXT,task INTEGER,reason TEXT,UNIQUE(context,sequence),UNIQUE(context,cause));
            CREATE TABLE IF NOT EXISTS authorization_scopes(context TEXT PRIMARY KEY REFERENCES devices(context),generation TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('verificationPending','verified','revoked')),namespace TEXT);
            CREATE TABLE IF NOT EXISTS vehicle_authorizations(context TEXT NOT NULL REFERENCES authorization_scopes(context),vehicle TEXT NOT NULL,allowed INTEGER NOT NULL CHECK(allowed IN(0,1)),PRIMARY KEY(context,vehicle));
            CREATE TABLE IF NOT EXISTS return_recoveries(id TEXT PRIMARY KEY,event TEXT NOT NULL REFERENCES events(id),payload TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('preparing','registered','awaitingAuthentication','blocked','accepted')),session TEXT,task INTEGER,reason TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS return_recovery_active ON return_recoveries(event) WHERE state IN('preparing','registered','awaitingAuthentication');
            CREATE TRIGGER IF NOT EXISTS return_recovery_immutable BEFORE UPDATE OF id,event,payload ON return_recoveries BEGIN SELECT RAISE(ABORT,'immutable recovery'); END;
            CREATE TABLE IF NOT EXISTS return_reconciliations(id TEXT PRIMARY KEY,event TEXT NOT NULL REFERENCES events(id),payload TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('preparing','registered','awaitingAuthentication','blocked','accepted')),session TEXT,task INTEGER,reason TEXT,acknowledgment TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS return_reconciliation_active ON return_reconciliations(event) WHERE state IN('preparing','registered','awaitingAuthentication');
            CREATE TRIGGER IF NOT EXISTS return_reconciliation_immutable BEFORE UPDATE OF id,event,payload ON return_reconciliations BEGIN SELECT RAISE(ABORT,'immutable reconciliation'); END;
            CREATE TRIGGER IF NOT EXISTS return_reconciliations_exclusive_INSERT BEFORE INSERT ON return_reconciliations WHEN NEW.state IN('preparing','registered','awaitingAuthentication') AND EXISTS(SELECT 1 FROM return_recoveries WHERE event=NEW.event AND state IN('preparing','registered','awaitingAuthentication','accepted')) BEGIN SELECT RAISE(ABORT,'active resolution'); END;
            CREATE TRIGGER IF NOT EXISTS return_reconciliations_exclusive_UPDATE BEFORE UPDATE ON return_reconciliations WHEN NEW.state IN('preparing','registered','awaitingAuthentication') AND EXISTS(SELECT 1 FROM return_recoveries WHERE event=NEW.event AND state IN('preparing','registered','awaitingAuthentication','accepted')) BEGIN SELECT RAISE(ABORT,'active resolution'); END;
            CREATE TRIGGER IF NOT EXISTS return_recoveries_exclusive_INSERT BEFORE INSERT ON return_recoveries WHEN NEW.state IN('preparing','registered','awaitingAuthentication') AND EXISTS(SELECT 1 FROM return_reconciliations WHERE event=NEW.event AND state IN('preparing','registered','awaitingAuthentication','accepted')) BEGIN SELECT RAISE(ABORT,'active resolution'); END;
            CREATE TRIGGER IF NOT EXISTS return_recoveries_exclusive_UPDATE BEFORE UPDATE ON return_recoveries WHEN NEW.state IN('preparing','registered','awaitingAuthentication') AND EXISTS(SELECT 1 FROM return_reconciliations WHERE event=NEW.event AND state IN('preparing','registered','awaitingAuthentication','accepted')) BEGIN SELECT RAISE(ABORT,'active resolution'); END;
            INSERT INTO devices VALUES('fixture-context','fixture-environment','fixture-device',16,1);
            INSERT INTO authorization_scopes VALUES('fixture-context','fixture-generation','verified','fixture-namespace');
            INSERT INTO vehicle_authorizations VALUES('fixture-context','00000000-0000-4000-8000-000000000002',1);
            INSERT INTO events VALUES('37765BAE-39C3-4CEA-BD53-10E30F2C7913','fixture-context',13,'00000000-0000-4000-8000-000000000002',NULL,'{"id":"37765BAE-39C3-4CEA-BD53-10E30F2C7913","vehicle":"00000000-0000-4000-8000-000000000002","sequence":13,"occurredAt":100,"kind":"take"}','accepted',NULL,NULL,NULL,'accepted');
            INSERT INTO events VALUES('07E91A49-BC53-4A33-8C41-F9C2B310FD28','fixture-context',14,'00000000-0000-4000-8000-000000000002','37765BAE-39C3-4CEA-BD53-10E30F2C7913','{"id":"07E91A49-BC53-4A33-8C41-F9C2B310FD28","vehicle":"00000000-0000-4000-8000-000000000002","sequence":14,"occurredAt":110,"kind":"return","takeID":"37765BAE-39C3-4CEA-BD53-10E30F2C7913","location":{"latitude":32,"longitude":34,"accuracy":10,"measuredAt":110}}','blocked',NULL,NULL,NULL,'RETURN_OUTSIDE_HOME');
            INSERT INTO events VALUES('00000000-0000-4000-8000-000000000015','fixture-context',15,'00000000-0000-4000-8000-000000000002',NULL,'{"id":"00000000-0000-4000-8000-000000000015","vehicle":"00000000-0000-4000-8000-000000000002","sequence":15,"occurredAt":120,"kind":"take"}','registered','00000000-0000-4000-8000-000000000043','background-session',42,NULL);
            INSERT INTO events VALUES('00000000-0000-4000-8000-000000000016','fixture-context',16,'00000000-0000-4000-8000-000000000002','00000000-0000-4000-8000-000000000015','{"id":"00000000-0000-4000-8000-000000000016","vehicle":"00000000-0000-4000-8000-000000000002","sequence":16,"occurredAt":130,"kind":"return","takeID":"00000000-0000-4000-8000-000000000015","location":{"latitude":32,"longitude":34,"accuracy":10,"measuredAt":130}}','pending',NULL,NULL,NULL,NULL);
            INSERT INTO return_recoveries VALUES('00000000-0000-4000-8000-000000000041','07E91A49-BC53-4A33-8C41-F9C2B310FD28','{"recovery_id":"00000000-0000-4000-8000-000000000041","original_return":{"event_id":"07E91A49-BC53-4A33-8C41-F9C2B310FD28","vehicle_ref":"00000000-0000-4000-8000-000000000002","device_sequence":14,"occurred_at":"2001-01-01T00:01:50Z","take_event_id":"37765BAE-39C3-4CEA-BD53-10E30F2C7913","latitude":32,"longitude":34,"accuracy_m":10,"location_at":"2001-01-01T00:01:50Z"},"verification":{"invoked_at":"2001-01-01T00:02:00Z","location_at":"2001-01-01T00:02:00Z","latitude":32,"longitude":34,"accuracy_m":10}}','blocked',NULL,NULL,'RETURN_OUTSIDE_HOME');
            INSERT INTO return_recoveries VALUES('00000000-0000-4000-8000-000000000042','07E91A49-BC53-4A33-8C41-F9C2B310FD28','{"recovery_id":"00000000-0000-4000-8000-000000000042","original_return":{"event_id":"07E91A49-BC53-4A33-8C41-F9C2B310FD28","vehicle_ref":"00000000-0000-4000-8000-000000000002","device_sequence":14,"occurred_at":"2001-01-01T00:01:50Z","take_event_id":"37765BAE-39C3-4CEA-BD53-10E30F2C7913","latitude":32,"longitude":34,"accuracy_m":10,"location_at":"2001-01-01T00:01:50Z"},"verification":{"invoked_at":"2001-01-01T00:02:00Z","location_at":"2001-01-01T00:02:00Z","latitude":32,"longitude":34,"accuracy_m":10}}','registered','background-session',43,NULL);

            UPDATE return_recoveries SET state='blocked',reason='RETURN_RECOVERY_ORDER_CONFLICT' WHERE state='registered';
            INSERT INTO return_reconciliations VALUES('00000000-0000-4000-8000-000000000051','07E91A49-BC53-4A33-8C41-F9C2B310FD28','{"reconciliation_id":"00000000-0000-4000-8000-000000000051","original_return":{"event_id":"07E91A49-BC53-4A33-8C41-F9C2B310FD28","device_sequence":14}}','registered','reconciliation-upload-session',51,NULL,NULL);
            INSERT INTO events SELECT '00000000-0000-4000-8000-000000000017',context,17,vehicle,NULL,replace(replace(payload,'37765BAE-39C3-4CEA-BD53-10E30F2C7913','00000000-0000-4000-8000-000000000017'),'"sequence":13','"sequence":17'),'accepted',NULL,NULL,NULL,'accepted' FROM events WHERE sequence=13;
            INSERT INTO events SELECT '00000000-0000-4000-8000-000000000018',context,18,vehicle,'00000000-0000-4000-8000-000000000017',replace(replace(replace(payload,'07E91A49-BC53-4A33-8C41-F9C2B310FD28','00000000-0000-4000-8000-000000000018'),'37765BAE-39C3-4CEA-BD53-10E30F2C7913','00000000-0000-4000-8000-000000000017'),'"sequence":14','"sequence":18'),'terminal',NULL,NULL,NULL,'resolved_current_state' FROM events WHERE sequence=14;
            INSERT INTO return_reconciliations VALUES('00000000-0000-4000-8000-000000000052','00000000-0000-4000-8000-000000000018','{"reconciliation_id":"00000000-0000-4000-8000-000000000052"}','accepted',NULL,NULL,NULL,'{"kind":"resolved_current_state","event_id":"00000000-0000-4000-8000-000000000018","device_sequence":18,"last_processed_sequence":18}');
            UPDATE devices SET last_sequence=18;
            PRAGMA user_version=4;
            """)
        let tables=["devices","events","authorization_scopes","vehicle_authorizations","return_recoveries","return_reconciliations"]
        let before=try tables.map {try migrationRows(v4dir,"SELECT * FROM \($0) ORDER BY 1")}
        for _ in 0..<2 {
            _=try VehicleEventQueue(directory:v4dir)
            let after=try tables.map {try migrationRows(v4dir,"SELECT * FROM \($0) ORDER BY 1")}
            precondition(before == after)
        }
        print("PASS: independent SQLite v4-v5 fixture, events, recovery/reconciliation payloads, mappings and acknowledgments preserved")
        let network=try SyncFixture(root:root.appendingPathComponent("metadata-network")); try await network.start()
        let nt=try await network.take(); await network.coordinator.wake()
        await network.coordinator.receive(network.transport.finish(1,body:accepted))
        let probe=MetadataProbe(); network.metadataTransport=probe; try network.restoreCoordinator()
        await network.coordinator.wake() // Returns while the metadata response is suspended.
        for _ in 0..<10000 { if probe.completion != nil { break }; await Task.yield() }
        precondition(probe.requests.count == 1 && probe.completion != nil)
        let nr=try await network.queue.recordShortcut(network.context,vehicle:nt.vehicle,kind:.returning,time:network.clock,
            location:.init(latitude:32,longitude:34,accuracy:10,measuredAt:network.clock))
        precondition(nr.takeID == nt.id)
        let continuation=probe.completion; probe.completion=nil
        continuation?.resume(throwing:AuthFailure.network)
        for _ in 0..<100 { await Task.yield() }
        let saved=try await network.queue.records(network.context)
        precondition(saved.map(\.event) == [nt,nr])
        await network.coordinator.wake()
        for _ in 0..<10000 { if probe.completion != nil { break }; await Task.yield() }
        precondition(probe.requests.count == 2)
        network.coordinator.fence()
        probe.completion?.resume(throwing:CancellationError()); probe.completion=nil
        print("PASS: actual sync wake never waits for metadata; failed refresh preserves evidence and lifecycle wake retries")
    }

}
