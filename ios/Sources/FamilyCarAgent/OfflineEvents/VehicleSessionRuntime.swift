#if canImport(UIKit)
import Foundation
import UIKit
import Network

/// Process-wide composition root for the app target (including background relaunch).
/// No registration, queue creation or scheduling occurs merely by opening FCA.
@MainActor final class VehicleSessionRuntime {
    static let shared = Result { try VehicleSessionRuntime() }
    let environment: AppEnvironment
    let api: AuthAPI
    let sessions: SessionManager
    private let authentication: SessionVehicleAuthentication
    private var transport: VehicleBackgroundUploadTransport?
    private var coordinator: VehicleSyncCoordinator?
    private var setup: NativeDeviceSetup?
    private var identityEpoch = 0
    private(set) var authorizationStorageFailed = false
    private var recordingPermit = VehicleRecordingPermit()
    private let connectivity = NWPathMonitor()
    private func invalidateRecording() {
        recordingPermit.invalidate()
        recordingPermit = VehicleRecordingPermit()
    }

    private init() throws {
        let composition = try SessionComposition(
            bundleIdentifier: Bundle.main.bundleIdentifier,
            configurationName: Bundle.main.object(forInfoDictionaryKey: "FCAEnvironment") as? String,
            publicKey: Bundle.main.object(forInfoDictionaryKey: "FCASupabasePublishableKey") as? String,
            vault: { KeychainVault(environment: $0) })
        environment = composition.environment
        api = composition.api
        sessions = composition.sessions
        authentication = SessionVehicleAuthentication(environment: environment, sessions: sessions)
        sessions.onInvalidation = { [weak self] old in
            self?.invalidate(old)
            NativePushService.shared.invalidate()
        }
        sessions.onVehicleBindingsReduced = { [weak self] in self?.invalidateRecording() }
        connectivity.pathUpdateHandler = { [weak self] path in
            guard path.status == .satisfied else { return }
            Task { @MainActor in await self?.recoverPending() }
        }
        connectivity.start(queue: DispatchQueue(label: "fca.vehicle.connectivity"))
    }

    /// Recover only a previously authorized installation. Never register or bind here.
    func recoverPending() async {
        guard let session = sessions.session, session.vehicleScope != nil else { return }
        let epoch = identityEpoch
        do {
            try await validateInstallation(session)
            guard epoch == identityEpoch, sessions.session?.owner == session.owner else { return }
            let c = try context(session)
            _ = try attach(c, queue: VehicleEventQueue(directory: VehicleEventQueue.applicationDirectory()))
            await coordinator?.wake()
        } catch { /* Keep durable work intact; explicit setup exposes recovery errors. */ }
    }

    private func deviceSetup() throws -> NativeDeviceSetup {
        if let setup { return setup }
        let directory = try VehicleEventQueue.applicationDirectory()
        let store = NativeDeviceFileStore(directory: directory.deletingLastPathComponent().appendingPathComponent("NativeDeviceRegistration"))
        let value = NativeDeviceSetup(environment: environment, store: store, queue: try VehicleEventQueue(directory: directory))
        setup = value; return value
    }
    func savedConnection(identity: ChatIdentity, vehicle: UUID) throws -> VehicleConnectionMethod? {
        try SetupGateway(runtime: self, identity: identity).check()
        return try deviceSetup().saved(identity)?.methods[vehicle]
    }
    func connectionState(identity: ChatIdentity, vehicle: UUID) async throws -> VehicleConnectionAuthorizationState {
        let gateway = SetupGateway(runtime: self, identity: identity)
        try gateway.check()
        let state = try await deviceSetup().connectionState(identity, vehicle: vehicle, namespace: sessions.session?.shortcutNamespace)
        try gateway.check()
        return state
    }
    func changeConnection(identity: ChatIdentity, vehicle: UUID, method: VehicleConnectionMethod) throws {
        try SetupGateway(runtime: self, identity: identity).check()
        try deviceSetup().setMethod(method, vehicle: vehicle, identity: identity)
    }
    func activateConnection(identity: ChatIdentity, vehicle: UUID, method: VehicleConnectionMethod) async throws {
        let gateway = SetupGateway(runtime: self, identity: identity)
        do { try await deviceSetup().activate(identity: identity, vehicle: vehicle, method: method, gateway: gateway) }
        catch NativeDeviceSetupError.recoveryRequired {
            try gateway.check(); invalidate(sessions.session)
            throw NativeDeviceSetupError.recoveryRequired
        }
        guard sessions.session?.boundVehicles?[vehicle] != nil else { throw NativeDeviceSetupError.unavailable }
    }
    func refreshConnection(identity: ChatIdentity, vehicle: UUID) async throws -> Bool {
        let gateway = SetupGateway(runtime: self, identity: identity)
        try gateway.check()
        let service = try deviceSetup()
        guard try service.readyForRestore(identity, scope: sessions.session?.vehicleScope) else { return false }
        try await service.activate(identity: identity, vehicle: nil, method: nil, gateway: gateway)
        try gateway.check()
        return sessions.session?.boundVehicles?[vehicle] != nil
    }
    /// Called only after /api/me establishes the foreground identity. Never creates a registration.
    func restoreAuthorized(identity: ChatIdentity) {
        Task { [weak self] in
            guard let self else { return }
            do {
                try SetupGateway(runtime: self, identity: identity).check()
                let service = try deviceSetup()
                guard try service.readyForRestore(identity, scope: sessions.session?.vehicleScope) else { return }
                guard let session = sessions.session else { return }
                try await validateInstallation(session)
                let c = try context(session)
                _ = try attach(c, queue: VehicleEventQueue(directory: VehicleEventQueue.applicationDirectory()))
                await coordinator?.wake()
            } catch NativeDeviceSetupError.recoveryRequired {
                if sessions.session?.owner == identity.owner, sessions.generation == identity.generation { invalidate(sessions.session) }
            } catch { /* Local restoration never starts server verification. Explicit refresh exposes errors. */ }
        }
    }

    private final class SetupGateway: NativeDeviceSetupGateway {
        let runtime: VehicleSessionRuntime
        let identity: ChatIdentity
        let epoch: Int
        init(runtime: VehicleSessionRuntime, identity: ChatIdentity) {
            self.runtime = runtime; self.identity = identity; epoch = runtime.identityEpoch
        }
        var hasSavedScope: Bool { runtime.sessions.session?.vehicleScope != nil }
        func check() throws {
            guard !runtime.authorizationStorageFailed, !Task.isCancelled, runtime.identityEpoch == epoch,
                  runtime.sessions.generation == identity.generation,
                  let session = runtime.sessions.session, session.owner == identity.owner, session.activated else { throw NativeDeviceSetupError.stale }
            if let scope = session.vehicleScope {
                guard scope.user == identity.user, scope.family == identity.family else { throw NativeDeviceSetupError.stale }
            }
        }
        private func request<T>(_ operation: (String) async throws -> T) async throws -> T {
            func attempt(_ force: Bool) async throws -> T {
                try check()
                let token = try await runtime.sessions.access(owner: identity.owner, force: force)
                try check(); let result = try await operation(token); try check(); return result
            }
            do {
                do { return try await attempt(false) }
                catch AuthFailure.rejected(401, _) { return try await attempt(true) }
            } catch AuthFailure.rejected(403, let code) {
                try check(); try await runtime.denyBindings()
                throw AuthFailure.rejected(403, code)
            }
        }
        private func profile() async throws {
            let me = try await request { try await runtime.api.backend(Me.self, path: "/api/me", token: $0) }
            try runtime.sessions.checkVehicleProfile(user: me.user_id, family: me.family_id,
                                                     expectedUser: identity.user, expectedFamily: identity.family)
        }
        func register(requestID: UUID) async throws -> UUID {
            try await profile()
            return try await request { try await runtime.api.registerVehicleDevice(requestID: requestID, token: $0) }
        }
        func validate(device: UUID) async throws {
            // SQLite preflight is already committed by NativeDeviceSetup. Cancel known work.
            await runtime.coordinator?.wake()
            try check()
            try await profile()
            guard try await request({ try await runtime.api.permitsVehicleDevice(device, token: $0) }) else {
                try await runtime.denyBindings()
                throw NativeDeviceSetupError.unavailable
            }
        }
        func bind(device: UUID, vehicle: UUID) async throws {
            try await request { try await runtime.api.bindVehicleDevice(device: device, vehicle: vehicle, token: $0) }
        }
        func enable(_ context: VehicleQueueContext, verification: UUID) async throws {
            try check()
            do {
                do { try await runtime.enable(authorized: context, verification: verification) }
                catch AuthFailure.rejected(401, _) {
                    try check(); _ = try await runtime.sessions.access(owner: identity.owner, force: true)
                    try check(); try await runtime.enable(authorized: context, verification: verification)
                }
            } catch AuthFailure.rejected(403, let code) {
                try check(); try await runtime.denyBindings()
                throw AuthFailure.rejected(403, code)
            }
            try check()
        }
    }

    private func denyBindings() async throws {
        guard let s = sessions.session, let scope = s.vehicleScope else { return }
        do { try VehicleEventQueue.revokeAuthorization(directory: VehicleEventQueue.applicationDirectory(), context: context(s)) }
        catch {
            authorizationStorageFailed = true
            invalidate(s)
            throw error
        }
        do { try sessions.authorizeVehicleScope(scope, owner: s.owner, generation: sessions.generation, bindings: [:]) }
        catch { invalidate(s); throw error }
        if coordinator == nil {
            let c = try context(s)
            _ = try attach(c, queue: VehicleEventQueue(directory: VehicleEventQueue.applicationDirectory()))
        }
        await coordinator?.wake() // Cancels known unbound work without deleting or skipping its sequence.
    }

    /// Future registration integration only: caller must supply the server-authorized device.
    /// A fresh login never inherits the previous login's scheduling scope.
    func enable(authorized c: VehicleQueueContext, verification: UUID) async throws {
        let version = sessions.generation
        let epoch = identityEpoch
        guard !authorizationStorageFailed, c.environment == environment.backendURL.absoluteString + "|" + environment.supabaseURL.absoluteString,
              sessions.session?.activated == true else { throw AuthFailure.stale }
        let token = try await sessions.access(owner: c.owner)
        let profile = try await api.backend(Me.self, path: "/api/me", token: token)
        guard epoch == identityEpoch, sessions.generation == version, sessions.session?.owner == c.owner else { throw AuthFailure.stale }
        try sessions.checkVehicleProfile(user: profile.user_id, family: profile.family_id, expectedUser: c.user, expectedFamily: c.family)
        guard try await api.permitsVehicleDevice(c.device, token: token) else {
            if identityEpoch == epoch, sessions.generation == version, sessions.session?.owner == c.owner { try await denyBindings() }
            throw NativeDeviceSetupError.unavailable
        }
        let queue = try VehicleEventQueue(directory: VehicleEventQueue.applicationDirectory())
        try await queue.validateSequence(c)
        let bindings = try await api.usableVehicleBindings(device: c.device, token: token)
        guard epoch == identityEpoch, !Task.isCancelled else { throw AuthFailure.stale }
        try sessions.authorizeVehicleScope(authentication.scope(c), owner: c.owner, generation: version, bindings: bindings)
        try await queue.completeVerification(c, generation: verification, vehicles: Set(bindings.keys), namespace: sessions.session?.shortcutNamespace)
        guard epoch == identityEpoch, sessions.generation == version else { throw AuthFailure.stale }
        _ = try attach(c, queue: queue)
        await coordinator?.wake()
    }

    func shortcutVehicles() async throws -> [String: UUID] {
        guard !authorizationStorageFailed else { throw VehicleQueueError.storage }
        try sessions.restore()
        guard let session = sessions.session else { throw AuthFailure.stale }
        try await validateInstallation(session)
        return authentication.shortcutVehicles(try context(session))
    }

    private func validateInstallation(_ session: AuthSession) async throws {
        guard !authorizationStorageFailed else { throw VehicleQueueError.storage }
        guard let scope = session.vehicleScope else { throw NativeDeviceSetupError.recoveryRequired }
        let identity = ChatIdentity(owner: session.owner, user: scope.user, family: scope.family,
                                    generation: sessions.generation, version: 0)
        let epoch = identityEpoch
        try await deviceSetup().validateOffline(identity, scope: scope)
        guard epoch == identityEpoch, sessions.generation == identity.generation,
              sessions.session?.owner == session.owner, sessions.session?.vehicleScope == scope else { throw AuthFailure.stale }
    }

    struct PreparedReturn {
        let selection: String
        let queue: VehicleEventQueue
        let snapshot: VehicleReturnPreparation
        let permit: VehicleRecordingPermit
        let generation: Int
        let epoch: Int
    }

    func prepareNativeReturn(selection: String) async throws -> PreparedReturn {
        let permit = recordingPermit
        guard let vehicle = try await shortcutVehicles()[selection], let session = sessions.session,
              let namespace = session.shortcutNamespace else { throw AuthFailure.stale }
        let queue = try VehicleEventQueue(directory: VehicleEventQueue.applicationDirectory())
        let snapshot = try await queue.prepareReturn(context(session), vehicle: vehicle, namespace: namespace)
        return .init(selection: selection, queue: queue, snapshot: snapshot, permit: permit,
                     generation: sessions.generation, epoch: identityEpoch)
    }

    func recordNativeReturn(_ prepared: PreparedReturn, location: VehicleLocationEvidence, onCommit: () -> Void) async throws {
        guard prepared.generation == sessions.generation, prepared.epoch == identityEpoch,
              let vehicle = try await shortcutVehicles()[prepared.selection], vehicle == prepared.snapshot.vehicle,
              let session = sessions.session, try context(session) == prepared.snapshot.context,
              session.shortcutNamespace == prepared.snapshot.namespace else { throw ShortcutQueueError.contextChanged }
        try Task.checkCancellation()
        // Actual decision time, after acquisition and local installation revalidation.
        // enqueue validates the unchanged measurement timestamp against this time again.
        let event = try await prepared.queue.commitReturn(prepared.snapshot, location: location, permit: prepared.permit)
        onCommit() // After SQLite COMMIT, before any scheduling or classified processing outcome.
        do { _ = try attach(prepared.snapshot.context, queue: prepared.queue) }
        catch { throw ShortcutQueueError.retryStored }
        guard let sync = coordinator else { throw ShortcutQueueError.retryStored }
        await sync.wake()
        do {
            if let recovery = try await prepared.queue.recovery(prepared.snapshot.context, event: event.id) {
                if let failure = ReturnRecoveryPolicy.shortcutFailure(recovery) { throw failure }
                if sync.diagnostic == .storageFailure || sync.diagnostic == .taskConflict { throw ShortcutQueueError.recoveryBlocked }
            }
        } catch let failure as ShortcutQueueError { throw failure }
        catch { throw ShortcutQueueError.retryStored } // The event is already durably committed.
    }

    func recordShortcut(selection: String, kind: QueuedVehicleEvent.Kind, time: Date, location: VehicleLocationEvidence?) async throws {
        let permit = recordingPermit
        guard let vehicle = try await shortcutVehicles()[selection], let session = sessions.session else { throw AuthFailure.stale }
        let c = try context(session)
        let directory = try VehicleEventQueue.applicationDirectory()
        let queue = try VehicleEventQueue(directory: directory)
        let transport = try attach(c, queue: queue)
        guard let sync = coordinator, transport.identifier == VehicleSyncCoordinator.sessionIdentifier(environment: environment, context: c)
        else { throw AuthFailure.stale }
        guard let namespace = session.shortcutNamespace else { throw AuthFailure.stale }
        let event = try await queue.recordAuthorizedShortcut(c, vehicle: vehicle, kind: kind, time: time, location: location, namespace: namespace, permit: permit)
        // Let the coordinator register eligible work before Shortcuts releases the process.
        await sync.wake()
        if kind == .returning, let recovery = try await queue.recovery(c, event: event.id) {
            if let failure = ReturnRecoveryPolicy.shortcutFailure(recovery) { throw failure }
            if sync.diagnostic == .storageFailure || sync.diagnostic == .taskConflict {
                throw ShortcutQueueError.recoveryBlocked
            }
        }
    }

    private func context(_ s: AuthSession) throws -> VehicleQueueContext {
        guard let scope = s.vehicleScope else { throw AuthFailure.stale }
        return try VehicleQueueContext(environment: environment,
            identity: .init(owner: s.owner, user: scope.user, family: scope.family, generation: sessions.generation, version: 0),
            device: scope.device)
    }
    func restore(_ identifier: String) async throws -> VehicleBackgroundUploadTransport {
        guard !authorizationStorageFailed else { throw VehicleQueueError.storage }
        try sessions.restore()
        guard let s = sessions.session else { throw AuthFailure.stale }
        try await validateInstallation(s)
        let c = try context(s)
        guard authentication.permits(c), identifier == VehicleSyncCoordinator.sessionIdentifier(environment: environment, context: c)
        else { throw AuthFailure.stale }
        return try attach(c, queue: VehicleEventQueue(directory: VehicleEventQueue.applicationDirectory()))
    }
    private func attach(_ c: VehicleQueueContext, queue: VehicleEventQueue) throws -> VehicleBackgroundUploadTransport {
        let id = VehicleSyncCoordinator.sessionIdentifier(environment: environment, context: c)
        if let transport {
            guard transport.identifier == id else { throw AuthFailure.stale }
            return transport
        }
        let t = try VehicleBackgroundUploadTransport(identifier: id)
        do {
            let sync = try VehicleSyncCoordinator(environment: environment, context: c, queue: queue,
                authentication: authentication, transport: t, directory: VehicleEventQueue.applicationDirectory(),
                metadataTransport: HTTPMetadataTransport(environment: environment))
            t.onCompletion = { [weak sync] in await sync?.receive($0) }
            transport = t; coordinator = sync
            return t
        } catch { t.invalidate(); throw error }
    }
    private func invalidate(_ old: AuthSession?) {
        invalidateRecording()
        identityEpoch += 1
        if let old, let c = try? context(old) {
            do { try VehicleEventQueue.revokeAuthorization(directory: VehicleEventQueue.applicationDirectory(), context: c) }
            catch { authorizationStorageFailed = true }
        }
        coordinator?.fence()
        if let transport { transport.invalidate() }
        else if let old, let c = try? context(old) {
            // The daemon can still own tasks even when this process has not attached.
            let id = VehicleSyncCoordinator.sessionIdentifier(environment: environment, context: c)
            (try? VehicleBackgroundUploadTransport(identifier: id))?.invalidate()
        }
        coordinator = nil; transport = nil
    }
}
#endif
