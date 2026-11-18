import Foundation


/// Public client configuration. Production requires an explicit compilation condition.
/// Build optimization (Debug/Release) never selects a server environment.
enum AppEnvironment: Sendable {
    case development
    case production

    enum ConfigurationError: Error {
        case unsupportedBundleIdentifier
    }

    /// Fail closed rather than silently using Dev services from another application.
    static func current(bundleIdentifier: String? = Bundle.main.bundleIdentifier) throws -> Self {
        #if FCA_PRODUCTION
        let selected = Self.production
        #else
        let selected = Self.development
        #endif
        guard bundleIdentifier == selected.bundleIdentifier else {
            throw ConfigurationError.unsupportedBundleIdentifier
        }
        return selected
    }

    var configurationName: String { self == .production ? "production" : "development" }
    var firebaseProject: String { self == .production ? "family-car-agent" : "family-car-agent-dev" }
    var firebaseSender: String { self == .production ? "249909620080" : "452367109329" }
    func acceptsFirebaseApp(_ app: String) -> Bool {
        if self == .production { return app == "1:249909620080:ios:12c8182ee0db3d93ee33b5" }
        return app.range(of: "^1:452367109329:ios:[0-9a-f]+$", options: .regularExpression) != nil
    }

    var backendURL: URL {
        switch self {
        case .development: URL(string: "https://family-car-agent-dev.onrender.com")!
        case .production: URL(string: "https://family-car-agent.onrender.com")!
        }
    }

    var supabaseURL: URL {
        switch self {
        case .development: URL(string: "https://jouhqvbxhsvkluwkqmdg.supabase.co")!
        case .production: URL(string: "https://xrgijytfigcuxmdktvmd.supabase.co")!
        }
    }

    var bundleIdentifier: String {
        switch self {
        case .development: "com.familycaragent.app.dev"
        case .production: "com.familycaragent.app"
        }
    }

    var applicationName: String {
        switch self {
        case .development: "Family Car Agent Dev"
        case .production: "Family Car Agent"
        }
    }

    /// Registered locally. Operator must verify the Supabase Dev redirect allowlist.
    var proposedOAuthCallbackURL: URL {
        switch self {
        case .development: URL(string: "com.familycaragent.app.dev://auth/callback")!
        case .production: URL(string: "com.familycaragent.app://auth/callback")!
        }
    }
}
