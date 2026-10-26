import Foundation

#if FCA_PRODUCTION
#error("Production authentication is disabled pending explicit configuration review.")
#endif

/// Public client configuration. Production must be added explicitly as a separate case.
/// Build optimization (Debug/Release) never selects a server environment.
enum AppEnvironment: Sendable {
    case development

    enum ConfigurationError: Error {
        case unsupportedBundleIdentifier
    }

    /// Fail closed rather than silently using Dev services from another application.
    static func current(bundleIdentifier: String? = Bundle.main.bundleIdentifier) throws -> Self {
        guard bundleIdentifier == Self.development.bundleIdentifier
            || bundleIdentifier == "XTL-255E706B.com.familycaragent.app.dev" else {
            throw ConfigurationError.unsupportedBundleIdentifier
        }
        return .development
    }

    var backendURL: URL {
        switch self {
        case .development: URL(string: "https://family-car-agent-dev.onrender.com")!
        }
    }

    var supabaseURL: URL {
        switch self {
        case .development: URL(string: "https://jouhqvbxhsvkluwkqmdg.supabase.co")!
        }
    }

    var bundleIdentifier: String {
        switch self {
        case .development: "com.familycaragent.app.dev"
        }
    }

    var applicationName: String {
        switch self {
        case .development: "Family Car Agent Dev"
        }
    }

    /// Registered locally. Operator must verify the Supabase Dev redirect allowlist.
    var proposedOAuthCallbackURL: URL {
        switch self {
        case .development: URL(string: "com.familycaragent.app.dev://auth/callback")!
        }
    }
}
