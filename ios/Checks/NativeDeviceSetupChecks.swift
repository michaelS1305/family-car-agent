import Foundation

@MainActor private final class SetupStore: NativeDeviceStore {
    var values: [UUID: NativeDeviceRegistration] = [:]
    var writes = 0
    var failWrite: Int?
    func read(owner: UUID) throws -> NativeDeviceRegistration? { values[owner] }
    func write(_ value: NativeDeviceRegistration) throws {
        writes += 1
        if failWrite == writes { throw VehicleQueueError.storage }
        values[value.owner] = value
    }
}
@MainActor private final class SetupGateway: NativeDeviceSetupGateway {
    let device = UUID()
    var current = true
    var hasSavedScope = false
    var unavailable = false
    var timeout = false
    var verificationOffline = false
    let namespace = UUID()
    var staleAfterRegister = false
    var staleAfterBind = false
    var pause = false
    var continuation: CheckedContinuation<Void, Never>?
    var requests: [UUID] = []
    var vehicles: Set<UUID> = []
    var bindCalls = 0
    var enables: [VehicleQueueContext] = []
    var queue: VehicleEventQueue?
    func check() throws { if !current { throw NativeDeviceSetupError.stale } }
    func register(requestID: UUID) async throws -> UUID {
        requests.append(requestID)
        if pause { await withCheckedContinuation { continuation = $0 } }
        if timeout { throw AuthFailure.network }
        if staleAfterRegister { current = false }
        return device
    }
    func validate(device: UUID) async throws {
        precondition(device == self.device)
        if unavailable { throw NativeDeviceSetupError.unavailable }
        if verificationOffline { throw AuthFailure.network }
    }
    func bind(device: UUID, vehicle: UUID) async throws {
        precondition(device == self.device); bindCalls += 1; vehicles.insert(vehicle)
        if staleAfterBind { current = false }
    }
    func enable(_ context: VehicleQueueContext, verification: UUID) async throws {
        try await queue?.completeVerification(context, generation: verification, vehicles: vehicles, namespace: namespace)
        enables.append(context)
    }
}

@main struct NativeDeviceSetupChecks {
    @MainActor static func fails(_ operation: () async throws -> Void) async {
        do { try await operation(); fatalError("Expected controlled failure") } catch { }
    }
    @MainActor static func main() async throws {
        let shortcutMappings: [(VehicleConnectionMethod, String, String)] = [
            (.carPlay, "8d40b6d0c6874fd2a6298a60eb8d49df", "00312d9300b64cdba857d469fd04a4fe"),
            (.bluetooth, "b4bd8ed12ab04c6b96c33769609c85a2", "60b68b80a05e4d74a09b5060b177f2c8")
        ]
        for (method, take, returning) in shortcutMappings {
            var ui = VehicleConnectionPresentation()
            ui.restore(method: method, authorization: .authorized)
            precondition(ui.shortcutURL(for: .take)?.absoluteString == "https://www.icloud.com/shortcuts/" + take)
            precondition(ui.shortcutURL(for: .returning)?.absoluteString == "https://www.icloud.com/shortcuts/" + returning)
            for state: VehicleConnectionAuthorizationState in [.inactive, .verificationPending, .temporarilyUnavailable, .verificationRequired, .recoveryRequired, .bindingRemoved] {
                ui.restore(method: method, authorization: state)
                precondition(ui.shortcutURL(for: .take) == nil && ui.shortcutURL(for: .returning) == nil)
            }
        }
        var missingMethod = VehicleConnectionPresentation()
        missingMethod.restore(method: nil, authorization: .authorized)
        precondition(missingMethod.shortcutURL(for: .take) == nil && missingMethod.shortcutURL(for: .returning) == nil)
        print("PASS: four Shortcut URLs; missing method and unauthorized states fail closed")
        for method in VehicleConnectionMethod.allCases {
            var ui = VehicleConnectionPresentation()
            precondition(ui.screen == .loading && !ui.showsShortcuts)
            ui.restore(method: nil, authorization: .inactive)
            precondition(ui.screen == .selection)
            ui.choose(method)
            precondition(ui.screen == .setup && ui.method == method && ui.showsActivation && ui.canGoBack)
            ui.back(); precondition(ui.screen == .selection)
            ui.choose(method == .carPlay ? .bluetooth : .carPlay)
            precondition(ui.screen == .setup && ui.method != method)
            ui.verifying(); precondition(!ui.showsActivation && !ui.showsShortcuts && !ui.canGoBack)
            ui.restore(method: method, authorization: .authorized)
            precondition(ui.showsShortcuts && !ui.showsActivation && !ui.canGoBack)
            ui.back(); ui.choose(method == .carPlay ? .bluetooth : .carPlay)
            precondition(ui.screen == .setup && ui.method == method)
            var reopened = VehicleConnectionPresentation()
            reopened.restore(method: method, authorization: .authorized)
            precondition(reopened.screen == .setup && reopened.showsShortcuts)
            for state: VehicleConnectionAuthorizationState in [.verificationPending, .temporarilyUnavailable, .verificationRequired, .recoveryRequired, .bindingRemoved] {
                reopened.restore(method: method, authorization: state)
                precondition(!reopened.showsShortcuts && !reopened.canGoBack && reopened.screen == .setup)
            }
            var anotherVehicle = VehicleConnectionPresentation()
            anotherVehicle.restore(method: nil, authorization: .bindingRemoved)
            precondition(anotherVehicle.screen == .selection && anotherVehicle.method == nil)
            anotherVehicle.unavailable(); precondition(!anotherVehicle.showsActivation && !anotherVehicle.showsShortcuts)
        }
        print("PASS: two-screen presentation, both methods, back, restored per-vehicle setup and untrusted authorization states")
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("fca-native-setup-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let identity = ChatIdentity(owner: UUID(), user: 1, family: 2, generation: 3, version: 4)
        let vehicle = UUID(), second = UUID()
        func fixture(_ store: SetupStore) throws -> (NativeDeviceSetup, VehicleEventQueue) {
            let queue = try VehicleEventQueue(directory: root.appendingPathComponent(UUID().uuidString))
            return (NativeDeviceSetup(environment: .development, store: store, queue: queue), queue)
        }
        let store = SetupStore(), gateway = SetupGateway()
        let (service, queue) = try fixture(store)
        gateway.queue = queue
        gateway.timeout = true
        await fails { try await service.activate(identity: identity, vehicle: vehicle, method: .carPlay, gateway: gateway) }
        let request = try service.saved(identity)!.requestID
        precondition(gateway.requests == [request] && gateway.enables.isEmpty)
        gateway.timeout = false
        try await service.activate(identity: identity, vehicle: nil, method: nil, gateway: gateway)
        precondition(gateway.requests == [request]) // Restoration cannot complete a pending registration implicitly.
        let relaunched = NativeDeviceSetup(environment: .development, store: store, queue: queue)
        try await relaunched.activate(identity: identity, vehicle: vehicle, method: .carPlay, gateway: gateway)
        precondition(gateway.requests == [request, request] && gateway.enables.count == 1)
        let context = gateway.enables[0]
        let scope = VehicleSessionScope(environment: context.environment, user: identity.user, family: identity.family, device: context.device)
        try await relaunched.validateOffline(identity, scope: scope)
        let event = try await queue.enqueueTake(context, vehicle: vehicle, occurredAt: Date())
        try await relaunched.activate(identity: identity, vehicle: vehicle, method: .carPlay, gateway: gateway)
        try await relaunched.activate(identity: identity, vehicle: second, method: .bluetooth, gateway: gateway)
        precondition(gateway.requests.count == 2 && gateway.vehicles == [vehicle, second])
        precondition(gateway.enables.allSatisfy { $0.device == context.device })
        try relaunched.setMethod(.bluetooth, vehicle: vehicle, identity: identity)
        let methods = try relaunched.saved(identity)?.methods
        precondition(methods == [vehicle: .bluetooth, second: .bluetooth])
        let rows = try await queue.records(context)
        precondition(rows.count == 1 && rows[0].event == event)
        let next = try await queue.enqueueTake(context, vehicle: second, occurredAt: Date())
        precondition(next.sequence == event.sequence + 1)
        let calls = gateway.requests.count
        try await relaunched.activate(identity: identity, vehicle: nil, method: nil, gateway: gateway)
        precondition(gateway.requests.count == calls && gateway.vehicles.count == 2)
        print("PASS: durable request retry, repeat activation, multiple vehicles, restoration, methods preserve events/sequence")
        var state = try await relaunched.connectionState(identity, vehicle: vehicle, namespace: gateway.namespace)
        precondition(state == .authorized)
        let refreshPuts = gateway.bindCalls
        gateway.verificationOffline = true
        await fails { try await relaunched.activate(identity: identity, vehicle: nil, method: nil, gateway: gateway) }
        state = try await relaunched.connectionState(identity, vehicle: vehicle, namespace: gateway.namespace)
        precondition(state == .verificationPending && !state.isAuthorized)
        state = state.afterVerificationFailure()
        precondition(state == .temporarilyUnavailable && !state.permitsActivation)
        let relaunchedUI = NativeDeviceSetup(environment: .development, store: store, queue: queue)
        let restoredState = try await relaunchedUI.connectionState(identity, vehicle: vehicle, namespace: gateway.namespace)
        precondition(restoredState == .verificationPending && !restoredState.permitsActivation)
        gateway.verificationOffline = false
        try await relaunchedUI.activate(identity: identity, vehicle: nil, method: nil, gateway: gateway)
        state = try await relaunchedUI.connectionState(identity, vehicle: vehicle, namespace: gateway.namespace)
        precondition(state == .authorized && gateway.bindCalls == refreshPuts)
        gateway.vehicles.remove(vehicle)
        let puts = gateway.bindCalls
        try await relaunched.activate(identity: identity, vehicle: nil, method: nil, gateway: gateway)
        precondition(gateway.bindCalls == puts && !gateway.vehicles.contains(vehicle))
        state = try await relaunched.connectionState(identity, vehicle: vehicle, namespace: gateway.namespace)
        precondition(state == .bindingRemoved && state.permitsActivation && !state.isAuthorized)
        try await relaunched.activate(identity: identity, vehicle: vehicle, method: .bluetooth, gateway: gateway)
        precondition(gateway.bindCalls == puts + 1)
        state = try await relaunched.connectionState(identity, vehicle: vehicle, namespace: gateway.namespace)
        precondition(state == .authorized)
        print("PASS: persisted UI state after failed GET refresh/relaunch, no PUT retry, explicit reactivation only")
        store.failWrite = store.writes + 1
        await fails { try relaunched.setMethod(.carPlay, vehicle: vehicle, identity: identity) }
        let persistedMethod = try relaunched.saved(identity)?.methods[vehicle]
        precondition(persistedMethod == .bluetooth)
        store.failWrite = nil

        for failedWrite in 1...4 {
            let journal = SetupStore(), remote = SetupGateway()
            let (initial, db) = try fixture(journal)
            remote.queue = db
            journal.failWrite = failedWrite
            await fails { try await initial.activate(identity: identity, vehicle: vehicle, method: .carPlay, gateway: remote) }
            precondition(remote.enables.isEmpty)
            if failedWrite == 1 { precondition(remote.requests.isEmpty) }
            let original = remote.requests.first
            journal.failWrite = nil
            let recovery = NativeDeviceSetup(environment: .development, store: journal, queue: db)
            try await recovery.activate(identity: identity, vehicle: vehicle, method: .carPlay, gateway: remote)
            if let original { precondition(remote.requests.allSatisfy { $0 == original }) }
            let event = try await db.enqueueTake(remote.enables[0], vehicle: vehicle, occurredAt: Date())
            precondition(event.sequence == 1)
        }
        print("PASS: interrupted request/reference/queue-ready/method persistence never enables incomplete setup")

        let (missingQueue, _) = try fixture(store)
        await fails { try await missingQueue.validateOffline(identity, scope: scope) }
        let freshMissingJournal = NativeDeviceSetup(environment: .development, store: SetupStore(), queue: queue)
        await fails { try await freshMissingJournal.validateOffline(identity, scope: scope) }
        let enables = gateway.enables.count
        await fails { try await missingQueue.activate(identity: identity, vehicle: vehicle, method: .carPlay, gateway: gateway) }
        precondition(gateway.enables.count == enables && gateway.requests.count == calls)
        let otherFamily = ChatIdentity(owner: identity.owner, user: 1, family: 77, generation: 3, version: 4)
        await fails { try await relaunched.validateOffline(otherFamily, scope: scope) }
        let wrongDevice = VehicleSessionScope(environment: scope.environment, user: scope.user, family: scope.family, device: UUID())
        await fails { try await relaunched.validateOffline(identity, scope: wrongDevice) }
        await fails { try await relaunched.activate(identity: otherFamily, vehicle: vehicle, method: .carPlay, gateway: gateway) }
        gateway.unavailable = true
        await fails { try await relaunched.activate(identity: identity, vehicle: vehicle, method: .carPlay, gateway: gateway) }
        precondition(gateway.enables.count == enables)
        let empty = SetupStore(), known = SetupGateway(); known.hasSavedScope = true
        let (lostJournal, _) = try fixture(empty)
        await fails { try await lostJournal.activate(identity: identity, vehicle: vehicle, method: .carPlay, gateway: known) }
        precondition(known.requests.isEmpty)
        let lostAfterLogout = NativeDeviceSetup(environment: .development, store: SetupStore(), queue: queue)
        let loggedInAgain = SetupGateway()
        await fails { try await lostAfterLogout.activate(identity: identity, vehicle: vehicle, method: .carPlay, gateway: loggedInAgain) }
        precondition(loggedInAgain.requests.isEmpty)
        print("PASS: missing existing queue/journal, family mismatch and revoked device fail closed")

        for atRegistration in [true, false] {
            let journal = SetupStore(), remote = SetupGateway()
            remote.staleAfterRegister = atRegistration; remote.staleAfterBind = !atRegistration
            let (setup, _) = try fixture(journal)
            await fails { try await setup.activate(identity: identity, vehicle: vehicle, method: .carPlay, gateway: remote) }
            precondition(remote.enables.isEmpty)
            if atRegistration { precondition(journal.values[identity.owner]?.device == nil) }
            precondition(journal.values[identity.owner]?.methods.isEmpty == true)
        }
        print("PASS: stale registration/binding results after logout or identity switch cannot activate")

        let concurrentStore = SetupStore(), concurrentGateway = SetupGateway()
        let (concurrent, _) = try fixture(concurrentStore)
        concurrentGateway.pause = true
        let activation = Task { try await concurrent.activate(identity: identity, vehicle: vehicle, method: .carPlay, gateway: concurrentGateway) }
        while concurrentGateway.continuation == nil { await Task.yield() }
        await fails { try await concurrent.activate(identity: identity, vehicle: second, method: .bluetooth, gateway: concurrentGateway) }
        concurrentGateway.continuation?.resume(); concurrentGateway.continuation = nil
        try await activation.value
        precondition(concurrentGateway.requests.count == 1 && concurrentGateway.vehicles == [vehicle])
        let otherIdentity = ChatIdentity(owner: UUID(), user: 22, family: 33, generation: 4, version: 5)
        let otherGateway = SetupGateway()
        try await concurrent.activate(identity: otherIdentity, vehicle: second, method: .bluetooth, gateway: otherGateway)
        precondition(concurrentStore.values.count == 2 && otherGateway.enables[0].owner == otherIdentity.owner)
        precondition(concurrentStore.values[identity.owner]?.device != concurrentStore.values[otherIdentity.owner]?.device)
        print("PASS: duplicate-tap exclusion and separate account installations")

        let files = NativeDeviceFileStore(directory: root.appendingPathComponent("journal"))
        let value = try relaunched.saved(identity)!
        try files.write(value)
        let restored = try NativeDeviceFileStore(directory: root.appendingPathComponent("journal")).read(owner: identity.owner)
        precondition(restored == value)
        let otherOwner = try files.read(owner: UUID())
        precondition(otherOwner == nil)
        try Data("invalid".utf8).write(to: root.appendingPathComponent("journal/" + identity.owner.uuidString + ".json"))
        await fails { _ = try files.read(owner: identity.owner) }
        let broken = NativeDeviceSetup(environment: .development, store: files, queue: queue)
        await fails { try await broken.validateOffline(identity, scope: scope) }
        let inaccessibleStore = NativeDeviceFileStore(directory: root.appendingPathComponent("journal/" + identity.owner.uuidString + ".json"))
        await fails { _ = try inaccessibleStore.read(owner: identity.owner) }
        print("PASS: real file persistence, account partition and corrupt journal rejection")
    }
}
