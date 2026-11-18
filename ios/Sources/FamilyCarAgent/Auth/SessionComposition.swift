import Foundation

/// Shared authentication composition used by the foreground app and background runtime.
/// Validation precedes vault construction; initialization performs no registration or HTTP.
@MainActor struct SessionComposition {
    let environment: AppEnvironment
    let api: AuthAPI
    let sessions: SessionManager

    init(bundleIdentifier: String?, configurationName: String?, publicKey: String?,
         vault: (AppEnvironment) -> any SessionVault) throws {
        let selected = try AppEnvironment.current(bundleIdentifier: bundleIdentifier)
        guard configurationName == selected.configurationName, let publicKey,
              AuthAPI.validPublicKey(publicKey) else { throw AuthFailure.configuration }
        environment = selected
        api = try AuthAPI(environment: selected, publicKey: publicKey)
        sessions = SessionManager(vault: vault(selected), transport: api)
    }
}
