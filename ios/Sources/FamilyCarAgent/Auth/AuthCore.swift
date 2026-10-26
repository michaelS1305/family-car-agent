import Foundation
#if DEBUG
#if canImport(OSLog)
import OSLog
#endif

/// Only compile-time labels and booleans. Never accepts callback contents or errors.
enum GoogleAuthDiagnostics {
    static func inspectStructure(_ url: URL, expected: URL, expectedNonce: String) {
        guard let c = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            event("callback_components_unavailable"); return
        }
        flag("callback_scheme_matches", c.scheme == expected.scheme)
        flag("callback_host_matches", c.host == expected.host)
        flag("callback_path_matches", c.path == expected.path)
        flag("callback_user_present", c.user != nil)
        flag("callback_password_present", c.password != nil)
        flag("callback_port_present", c.port != nil)
        flag("callback_fragment_present", c.fragment != nil)
        let errorKeys: Set<String> = ["error", "error_code", "error_description"]
        flag("callback_query_error_field_present", (c.queryItems ?? []).contains { errorKeys.contains($0.name) })
        // Observe key presence only; neither values nor arbitrary key names are emitted.
        var fragment = URLComponents()
        fragment.percentEncodedQuery = c.percentEncodedFragment
        flag("callback_fragment_error_field_present", (fragment.queryItems ?? []).contains { errorKeys.contains($0.name) })
        for observation in observations(c, expectedNonce: expectedNonce) { flag(observation.0, observation.1) }
    }
    static func observations(_ c: URLComponents, expectedNonce: String) -> [(StaticString, Bool)] {
        var fragment = URLComponents()
        fragment.percentEncodedQuery = c.percentEncodedFragment
        let tokenKeys: Set<String> = ["access_token", "refresh_token", "id_token", "provider_token", "provider_refresh_token"]
        let codes = (c.queryItems ?? []).filter { $0.name == "code" }
        let nonces = (c.queryItems ?? []).filter { $0.name == "nonce" }
        // Supabase external.go redirectErrors encodes hq.Set("sb", "") as sb=.
        // Exact raw marker only; this is NOT a trust or acceptance decision.
        return [
            ("callback_fragment_empty", c.percentEncodedFragment == ""),
            ("callback_fragment_known_marker_only", c.percentEncodedFragment == "sb="),
            ("callback_fragment_token_field_present", (fragment.queryItems ?? []).contains { tokenKeys.contains($0.name) }),
            ("callback_query_code_unique_nonempty", codes.count == 1 && codes.first?.value?.isEmpty == false),
            ("callback_query_nonce_unique", nonces.count == 1),
            ("callback_query_nonce_matches", nonces.count == 1 && nonces.first?.value == expectedNonce)
        ]
    }
    static func event(_ label: StaticString) { emit(String(describing: label)) }
    static func flag(_ label: StaticString, _ value: Bool) { emit("\(label)=\(value)") }
    private static func emit(_ message: String) {
        #if canImport(OSLog)
        Logger(subsystem: "com.familycaragent.auth.diagnostics", category: "GoogleSignIn")
            .notice("FCA_GOOGLE_AUTH_DIAG \(message, privacy: .public)")
        #else
        print("FCA_GOOGLE_AUTH_DIAG \(message)")
        #endif
    }
}
#endif

enum AuthFailure: Error, Equatable {
    case configuration, storage, cancelled, expired, callback, invalidResponse, signedOut, stale, network
    case rejected(Int, String)

    var message: String {
        switch self {
        case .configuration: "ההתחברות ב־Dev עדיין לא הוגדרה. יש לבדוק את הגדרות הבנייה."
        case .storage: "לא ניתן לגשת לאחסון המאובטח. יש לפתוח את נעילת המכשיר ולנסות שוב."
        case .cancelled: "ההתחברות בוטלה. אפשר לנסות שוב."
        case .expired, .callback: "תוקף ההתחברות פג או שהקישור אינו תקין. יש להתחיל מחדש."
        case .signedOut, .stale: "יש להתחבר מחדש כדי להמשיך."
        case .rejected(_, let code):
            switch code {
            case "MISSING_ACCOUNT": "לא נמצא חשבון FCA פעיל. אפשר ליצור משפחה או להצטרף למשפחה."
            case "ACCOUNT_UNAVAILABLE": "החשבון אינו זמין או נמצא בתהליך מחיקה."
            case "AUTH_USER_ALREADY_MAPPED": "החשבון כבר משויך למשתמש. יש לחזור ולהיכנס לחשבון הקיים."
            case "JOIN_LOCKED": "ההצטרפות נעולה ל־15 דקות לאחר שלושה ניסיונות. בדקו את הפרטים עם מנהל המשפחה."
            case "INVALID_FAMILY_NAME": "יש להזין שם משפחה תקין, ללא ספרות."
            case "INVALID_USER_NAME": "יש להזין שם פרטי תקין, ללא ספרות."
            case "FAMILY_ALREADY_EXISTS_AT_ADDRESS": "כבר קיימת משפחה בכתובת הזו. ניתן לבחור הצטרפות למשפחה."
            case "ADDRESS_RESOLUTION_EXPIRED": "תוקף אישור הכתובת פג. יש לבדוק ולאשר אותה שוב."
            case "JOIN_FAMILY_NAME_NOT_FOUND": "שם המשפחה לא נמצא. בדקו את הפרטים לפני ניסיון נוסף."
            case "INVALID_FAMILY_CODE": "קוד המשפחה אינו תקין. בדקו אותו עם מנהל המשפחה לפני ניסיון נוסף."
            case "JOIN_FAMILY_ADDRESS_NOT_FOUND", "ADDRESS_NOT_FOUND", "INVALID_ADDRESS_FORMAT", "ADDRESS_TOO_LONG":
                "לא ניתן לאמת את הכתובת. יש להזין עיר, רחוב ומספר בית."
            default: "לא ניתן להשלים את הפעולה כרגע. בדקו את החיבור ונסו שוב."
            }
        default: "לא ניתן להשלים את הפעולה כרגע. בדקו את החיבור ונסו שוב."
        }
    }
}

enum LoginRoute: String, CaseIterable, Codable, Sendable {
    case existing, create, join
    var title: String {
        switch self { case .existing: "חשבון קיים"; case .create: "יצירת משפחה"; case .join: "הצטרפות למשפחה" }
    }
}

struct ProviderResult {
    let grant: String
    let fields: [String: String]
    var appleUser: String? = nil
}

@MainActor protocol NativeAuthProvider: AnyObject {
    func authorize(apple: Bool) async throws -> ProviderResult
    func cancel()
    func credentialValid(_ user: String) async throws -> Bool
}

/// One in-memory authorization attempt. No callback can resurrect an interrupted process.
struct PendingAuthorization {
    let verifier: String
    let nonce: String
    let started: Date
    let callbackURL: URL

    func code(from url: URL, now: Date) throws -> String {
        guard (0..<600).contains(now.timeIntervalSince(started)) else {
            #if DEBUG
            GoogleAuthDiagnostics.event("callback_age_invalid")
            #endif
            throw AuthFailure.expired
        }
        guard let c = URLComponents(url: url, resolvingAgainstBaseURL: false),
              c.scheme == callbackURL.scheme, c.host == callbackURL.host, c.path == callbackURL.path,
              c.user == nil, c.password == nil, c.port == nil, (c.fragment == nil || c.fragment == "") else {
            #if DEBUG
            GoogleAuthDiagnostics.event("callback_structure_invalid")
            GoogleAuthDiagnostics.inspectStructure(url, expected: callbackURL, expectedNonce: nonce)
            #endif
            throw AuthFailure.callback
        }
        #if DEBUG
        GoogleAuthDiagnostics.event("callback_structure_valid")
        #endif
        let items = c.queryItems ?? []
        guard items.filter({ $0.name == "nonce" }).count == 1,
              items.first(where: { $0.name == "nonce" })?.value == nonce else {
            #if DEBUG
            GoogleAuthDiagnostics.flag("nonce_present", items.contains(where: { $0.name == "nonce" }))
            GoogleAuthDiagnostics.flag("nonce_unique", items.filter({ $0.name == "nonce" }).count == 1)
            GoogleAuthDiagnostics.event("nonce_validation_failed")
            #endif
            throw AuthFailure.callback
        }
        #if DEBUG
        GoogleAuthDiagnostics.event("nonce_validation_passed")
        #endif
        if items.contains(where: { $0.name == "error" }) {
            #if DEBUG
            GoogleAuthDiagnostics.event("callback_provider_error_present")
            #endif
            throw AuthFailure.cancelled
        }
        guard items.filter({ $0.name == "code" }).count == 1,
              let code = items.first(where: { $0.name == "code" })?.value,
              !code.isEmpty, code.count <= 4096 else {
            #if DEBUG
            GoogleAuthDiagnostics.event("callback_code_invalid")
            #endif
            throw AuthFailure.callback
        }
        #if DEBUG
        GoogleAuthDiagnostics.event("callback_validation_passed")
        #endif
        return code
    }

    func authorizeURL(base: URL, challenge: String) throws -> URL {
        var redirect = URLComponents(url: callbackURL, resolvingAgainstBaseURL: false)!
        redirect.queryItems = [URLQueryItem(name: "nonce", value: nonce)]
        var url = URLComponents(url: base.appendingPathComponent("auth/v1/authorize"), resolvingAgainstBaseURL: false)!
        url.queryItems = [URLQueryItem(name: "provider", value: "google"),
                         URLQueryItem(name: "redirect_to", value: redirect.url!.absoluteString),
                         URLQueryItem(name: "code_challenge", value: challenge),
                         URLQueryItem(name: "code_challenge_method", value: "s256")]
        guard let result = url.url else { throw AuthFailure.configuration }
        return result
    }
}

@MainActor final class AuthorizationAttempt {
    private var pending: PendingAuthorization?
    func begin(_ value: PendingAuthorization) { pending = value }
    func cancel() { pending = nil }
    func consume(_ url: URL, now: Date = Date()) throws -> (String, String) {
        #if DEBUG
        GoogleAuthDiagnostics.flag("pending_state_present", pending != nil)
        #endif
        guard let value = pending else { throw AuthFailure.expired }
        pending = nil // consume BEFORE validation or exchange; every retry needs a fresh attempt
        return (try value.code(from: url, now: now), value.verifier)
    }
}

struct AuthSession: Codable, Equatable, Sendable {
    let owner: UUID
    let accessToken: String
    let refreshToken: String
    let expires: Date
    var activated = false
    var appleUser: String? = nil // credential-state lookup only; not an FCA account identifier
}

@MainActor protocol SessionVault {
    func read() throws -> AuthSession?
    func write(_ session: AuthSession) throws
    func clear() throws
}

protocol AuthTransport: Sendable {
    func exchange(grant: String, fields: [String: String]) async throws -> AuthSession
}

/// One session owner and one refresh flight. Every async result is fenced by generation.
@MainActor final class SessionManager {
    private let vault: any SessionVault
    private let transport: any AuthTransport
    private(set) var session: AuthSession?
    private(set) var generation = 0
    private var refreshing: Task<AuthSession, Error>?

    init(vault: any SessionVault, transport: any AuthTransport) {
        self.vault = vault; self.transport = transport
    }
    func restore() throws {
        guard session == nil else { return }
        let saved = try vault.read()
        guard saved?.activated == true else { try vault.clear(); return }
        session = saved
    }
    func clear() throws {
        generation += 1; refreshing?.cancel(); refreshing = nil; session = nil
        try vault.clear() // caller must not begin another login if erasure fails
    }
    func login(grant: String, fields: [String: String], appleUser: String? = nil) async throws {
        let version = generation
        guard session == nil else { throw AuthFailure.stale }
        var result = try await transport.exchange(grant: grant, fields: fields)
        guard version == generation, session == nil else { throw AuthFailure.stale }
        result.appleUser = appleUser
        try vault.write(result); session = result
    }
    func activate(owner: UUID) throws {
        guard var value = session, value.owner == owner else { throw AuthFailure.stale }
        value.activated = true
        try vault.write(value); session = value
    }
    func access(owner: UUID, force: Bool = false, now: Date = Date()) async throws -> String {
        guard let current = session, current.owner == owner else { throw AuthFailure.signedOut }
        if let refreshing {
            let version = generation
            let value = try await refreshing.value
            guard version == generation, session?.owner == owner else { throw AuthFailure.stale }
            return value.accessToken
        }
        if !force && current.expires.timeIntervalSince(now) > 60 { return current.accessToken }
        let version = generation
        let flight = Task { @MainActor [self] () throws -> AuthSession in
            defer { if generation == version { refreshing = nil } }
            do {
                var result = try await transport.exchange(grant: "refresh_token", fields: ["refresh_token": current.refreshToken])
                guard generation == version, session?.owner == owner else { throw AuthFailure.stale }
                guard result.owner == owner else { try clear(); throw AuthFailure.signedOut }
                result.activated = current.activated; result.appleUser = current.appleUser
                try vault.write(result); session = result
                return result
            } catch {
                if generation == version, let failure = error as? AuthFailure,
                   case .rejected(let status, let code) = failure,
                   status == 401 || ["refresh_token_not_found", "refresh_token_already_used", "invalid_grant", "session_not_found", "user_not_found"].contains(code) {
                    try clear(); throw AuthFailure.signedOut
                }
                throw error
            }
        }
        refreshing = flight
        let value = try await flight.value
        guard version == generation, session?.owner == owner else { throw AuthFailure.stale }
        return value.accessToken
    }
}
