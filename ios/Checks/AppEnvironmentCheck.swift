import Foundation

/// Standalone checks: compile alongside AppEnvironment.swift on Linux or macOS.
/// Kept outside Sources so this executable is never included in the iOS app target.
@main
struct AppEnvironmentCheck {
    static func main() throws {
        let dev = try AppEnvironment.current(bundleIdentifier: "com.familycaragent.app.dev")
        precondition(dev == .development)
        let managedDev = try AppEnvironment.current(bundleIdentifier: "XTL-255E706B.com.familycaragent.app.dev")
        precondition(managedDev == dev)
        precondition(managedDev.bundleIdentifier == dev.bundleIdentifier)
        precondition(managedDev.proposedOAuthCallbackURL == dev.proposedOAuthCallbackURL)
        precondition(dev.backendURL.absoluteString == "https://family-car-agent-dev.onrender.com")
        precondition(dev.supabaseURL.absoluteString == "https://jouhqvbxhsvkluwkqmdg.supabase.co")
        precondition(dev.bundleIdentifier == "com.familycaragent.app.dev")
        precondition(dev.applicationName == "Family Car Agent Dev")
        for endpoint in [dev.backendURL, dev.supabaseURL] {
            precondition(endpoint.scheme == "https" && endpoint.host != nil)
            precondition(endpoint.user == nil && endpoint.password == nil)
            precondition(endpoint.query == nil && endpoint.fragment == nil)
        }
        precondition(dev.proposedOAuthCallbackURL.absoluteString == "com.familycaragent.app.dev://auth/callback")
        precondition(dev.proposedOAuthCallbackURL.scheme == dev.bundleIdentifier)
        precondition(dev.proposedOAuthCallbackURL.host == "auth")
        precondition(dev.proposedOAuthCallbackURL.path == "/callback")
        for identifier: String? in [nil, "", "com.familycaragent.app", "other.app", "COM.FAMILYCARAGENT.APP.DEV",
                                   "XTL-255E706B.com.familycaragent.app", "XTL-OTHER.com.familycaragent.app.dev",
                                   "XTL-255E706B.com.familycaragent.app.dev.extra"] {
            do {
                _ = try AppEnvironment.current(bundleIdentifier: identifier)
                preconditionFailure("An unsupported bundle identifier was accepted")
            } catch AppEnvironment.ConfigurationError.unsupportedBundleIdentifier {
                // Expected. No fallback to Dev for an unknown/Production bundle.
            }
        }
        print("AppEnvironment checks passed")
    }
}
