#if canImport(UIKit)
import Foundation
import UIKit

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

    private init() throws {
        environment = try AppEnvironment.current()
        guard Bundle.main.object(forInfoDictionaryKey: "FCAEnvironment") as? String == "development",
              let key = Bundle.main.object(forInfoDictionaryKey: "FCASupabasePublishableKey") as? String else { throw AuthFailure.configuration }
        api = try AuthAPI(environment: environment, publicKey: key)
        sessions = SessionManager(vault: KeychainVault(environment: environment), transport: api)
        authentication = SessionVehicleAuthentication(environment: environment, sessions: sessions)
        sessions.onInvalidation = { [weak self] old in self?.invalidate(old) }
        sessions.onVehicleScopeRestored = { [weak self] in
            guard let self, let s = sessions.session, let c = try? context(s), authentication.permits(c) else { return }
            let id = VehicleSyncCoordinator.sessionIdentifier(environment: environment, context: c)
            guard (try? restore(id)) != nil, let coordinator else { return }
            Task { await coordinator.wake() }
        }
    }

    /// Future registration integration only: caller must supply the server-authorized device.
    /// A fresh login never inherits the previous login's scheduling scope.
    func enable(authorized c: VehicleQueueContext) async throws {
        let version = sessions.generation
        guard c.environment == environment.backendURL.absoluteString + "|" + environment.supabaseURL.absoluteString,
              sessions.session?.activated == true else { throw AuthFailure.stale }
        let token = try await sessions.access(owner: c.owner)
        let profile = try await api.backend(Me.self, path: "/api/me", token: token)
        guard profile.user_id == c.user, profile.family_id == c.family,
              try await api.permitsVehicleDevice(c.device, token: token) else { throw AuthFailure.stale }
        let bindings = try await api.usableVehicleBindings(device: c.device, token: token)
        let queue = try VehicleEventQueue(directory: VehicleEventQueue.applicationDirectory())
        try await queue.validateActiveContext(c)
        try sessions.authorizeVehicleScope(authentication.scope(c), owner: c.owner, generation: version, bindings: bindings)
        _ = try attach(c, queue: queue)
        await coordinator?.wake()
    }

    func shortcutVehicles() throws -> [String: UUID] {
        try sessions.restore()
        guard let session = sessions.session else { throw AuthFailure.stale }
        return authentication.shortcutVehicles(try context(session))
    }

    func recordShortcut(selection: String, kind: QueuedVehicleEvent.Kind, time: Date, location: VehicleLocationEvidence?) async throws {
        guard let vehicle = try shortcutVehicles()[selection], let session = sessions.session else { throw AuthFailure.stale }
        let c = try context(session)
        let directory = try VehicleEventQueue.applicationDirectory()
        let queue = try VehicleEventQueue(directory: directory)
        let transport = try attach(c, queue: queue)
        guard let sync = coordinator, transport.identifier == VehicleSyncCoordinator.sessionIdentifier(environment: environment, context: c)
        else { throw AuthFailure.stale }
        _ = try await queue.recordShortcut(c, vehicle: vehicle, kind: kind, time: time, location: location)
        // Let the coordinator register eligible work before Shortcuts releases the process.
        await sync.wake()
    }

    private func context(_ s: AuthSession) throws -> VehicleQueueContext {
        guard let scope = s.vehicleScope else { throw AuthFailure.stale }
        return try VehicleQueueContext(environment: environment,
            identity: .init(owner: s.owner, user: scope.user, family: scope.family, generation: sessions.generation, version: 0),
            device: scope.device)
    }
    func restore(_ identifier: String) throws -> VehicleBackgroundUploadTransport {
        try sessions.restore()
        guard let s = sessions.session else { throw AuthFailure.stale }
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
                authentication: authentication, transport: t, directory: VehicleEventQueue.applicationDirectory())
            t.onCompletion = { [weak sync] in await sync?.receive($0) }
            transport = t; coordinator = sync
            return t
        } catch { t.invalidate(); throw error }
    }
    private func invalidate(_ old: AuthSession?) {
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
