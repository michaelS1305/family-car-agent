import Foundation

@main struct NativePushEnvironmentChecks {
    static func main() throws {
        #if FCA_PRODUCTION
        let selected = AppEnvironment.production
        let rejected = AppEnvironment.development
        #else
        let selected = AppEnvironment.development
        let rejected = AppEnvironment.production
        #endif
        let actual = try AppEnvironment.current(bundleIdentifier: selected.bundleIdentifier)
        precondition(actual == selected)
        for identifier: String? in [nil, "", rejected.bundleIdentifier, "other.app"] {
            do {
                _ = try AppEnvironment.current(bundleIdentifier: identifier)
                preconditionFailure("Unexpected environment fallback")
            } catch AppEnvironment.ConfigurationError.unsupportedBundleIdentifier { }
        }
        let prod = AppEnvironment.production
        precondition(prod.firebaseProject == "family-car-agent")
        precondition(prod.firebaseSender == "249909620080")
        precondition(prod.acceptsFirebaseApp("1:249909620080:ios:12c8182ee0db3d93ee33b5"))
        precondition(!prod.acceptsFirebaseApp("1:249909620080:ios:abcdef"))
        precondition(!prod.acceptsFirebaseApp("1:452367109329:ios:abcdef"))
        precondition(prod.backendURL.absoluteString == "https://family-car-agent.onrender.com")
        precondition(prod.supabaseURL.absoluteString == "https://xrgijytfigcuxmdktvmd.supabase.co")
        precondition(prod.proposedOAuthCallbackURL.scheme == prod.bundleIdentifier)
        precondition(AppEnvironment.development.acceptsFirebaseApp("1:452367109329:ios:abcdef"))
        print("Push environment checks passed: \(selected.configurationName)")
    }
}
