import Foundation

@MainActor final class CompositionVault: SessionVault {
    var reads = 0
    func read() throws -> AuthSession? { reads += 1; return nil }
    func write(_ value: AuthSession) throws { preconditionFailure("Unexpected session write") }
    func clear() throws { preconditionFailure("Unexpected session clear") }
}
@main struct SessionCompositionChecks {
    @MainActor static func main() throws {
        #if FCA_PRODUCTION
        let selected = AppEnvironment.production
        let other = AppEnvironment.development
        #else
        let selected = AppEnvironment.development
        let other = AppEnvironment.production
        #endif
        let vault = CompositionVault()
        var constructions = 0
        func make(_ id: String?, _ name: String?, _ key: String?) throws -> SessionComposition {
            try SessionComposition(bundleIdentifier: id, configurationName: name, publicKey: key) { environment in
                precondition(environment == selected); constructions += 1; return vault
            }
        }
        let root = try make(selected.bundleIdentifier, selected.configurationName, "sb_publishable_synthetic")
        precondition(root.environment == selected && root.api.environment == selected)
        precondition(root.sessions.session == nil && constructions == 1 && vault.reads == 0)
        for (id, name, key): (String?, String?, String?) in [
            (other.bundleIdentifier, other.configurationName, "sb_publishable_synthetic"),
            (selected.bundleIdentifier, other.configurationName, "sb_publishable_synthetic"),
            (nil, selected.configurationName, "sb_publishable_synthetic"),
            (selected.bundleIdentifier, nil, "sb_publishable_synthetic"),
            (selected.bundleIdentifier, selected.configurationName, nil),
            (selected.bundleIdentifier, selected.configurationName, "sb_secret_rejected")
        ] {
            do { _ = try make(id, name, key); preconditionFailure("Configuration accepted") } catch { }
        }
        precondition(constructions == 1 && vault.reads == 0)
        print("Session composition passed: \(selected.configurationName), no persistence or network operations")
    }
}
