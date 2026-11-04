import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

@MainActor private final class SyncSessionVault: SessionVault {
    var saved: AuthSession?
    func read() throws -> AuthSession? { saved }
    func write(_ value: AuthSession) throws { saved = value }
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
    var clock = Date(timeIntervalSince1970: 1_800_000_000)
    var coordinator: VehicleSyncCoordinator!
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
        coordinator = try VehicleSyncCoordinator(environment: .development, context: context, queue: queue,
            authentication: auth, transport: transport, directory: root.appendingPathComponent("uploads"), now: { [unowned self] in self.clock })
    }
    func start() async throws { try await queue.initializeFreshDevice(context) }
    func take(vehicle: UUID = UUID()) async throws -> QueuedVehicleEvent {
        try await queue.enqueueTake(context, vehicle: vehicle, occurredAt: clock)
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

        let sharedFixture = try await fixture(), ctx = sharedFixture.context
        let vault = SyncSessionVault()
        vault.saved = AuthSession(owner: ctx.owner, accessToken: "old", refreshToken: "secret-sentinel",
                                  expires: .distantPast, activated: true)
        let exchange = SyncSessionExchange(.init(owner: ctx.owner, accessToken: "new", refreshToken: "second-sentinel", expires: .distantFuture))
        let sessions = SessionManager(vault: vault, transport: exchange)
        try sessions.restore()
        let provider = SessionVehicleAuthentication(environment: .development, sessions: sessions)
        precondition(!provider.permits(ctx))
        let vehicleA = UUID(), vehicleB = UUID()
        try sessions.authorizeVehicleScope(provider.scope(ctx), owner: ctx.owner, generation: sessions.generation,
                                           bindings: [vehicleA: "A", vehicleB: "B"])
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
        _ = try await sharedFixture.take()
        await actual.wake()
        precondition(sharedFixture.transport.created.count == 1)
        let paths = FileManager.default.enumerator(at: sharedFixture.root, includingPropertiesForKeys: [.isRegularFileKey])!
        for case let file as URL in paths where try file.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile == true {
            let bytes = try Data(contentsOf: file)
            for marker in ["second-sentinel", "secret-sentinel", "Bearer new"] {
                precondition(bytes.range(of: Data(marker.utf8)) == nil)
            }
        }
        try sessions.clear()
        precondition(!provider.isCurrent(grant) && provider.shortcutVehicles(ctx).isEmpty)
        vault.saved = AuthSession(owner: UUID(), accessToken: "another", refreshToken: "third-sentinel", expires: .distantFuture, activated: true)
        try sessions.restore()
        precondition(!provider.permits(ctx) && provider.shortcutVehicles(ctx).isEmpty)
        print("PASS: real shared session provider, explicit scope, refresh, logout and different login")

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
    }
}
