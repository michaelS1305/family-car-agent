import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
#if DEBUG
#if canImport(OSLog)
import OSLog
#endif

/// Fixed labels and allowlisted domains only. Never format NSError/userInfo wholesale.
enum AppleAuthDiagnostics {
    static func event(_ label: StaticString) { emit(String(describing: label)) }
    static func flag(_ label: StaticString, _ value: Bool) { emit("\(label)=\(value)") }
    static func status(_ value: Int) { emit("exchange_http_status=\(value)") }
    static func error(_ error: Error) {
        for line in errorSummaries(error as NSError) { emit(line) }
    }
    static func errorSummaries(_ error: NSError) -> [String] {
        let allowed: Set<String> = ["com.apple.AuthenticationServices.AuthorizationError", "ASAuthorizationErrorDomain",
            "AKAuthenticationError", "AKErrorDomain", "AKSQLError", "NSURLErrorDomain", "NSCocoaErrorDomain",
            "com.apple.AuthKit", "com.apple.AppleIDAuthSupport", "AppleIDAuthSupport"]
        var seen = Set<ObjectIdentifier>()
        var result: [String] = []
        func visit(_ value: NSError, depth: Int) {
            guard depth < 4, result.count < 8, seen.insert(ObjectIdentifier(value)).inserted else { return }
            let domain = allowed.contains(value.domain) ? value.domain : "redacted_unrecognized_domain"
            result.append("error_depth=\(depth) domain=\(domain) code=\(value.code)")
            if let underlying = value.userInfo[NSUnderlyingErrorKey] as? NSError { visit(underlying, depth: depth + 1) }
            if let nested = value.userInfo["NSMultipleUnderlyingErrors"] as? [NSError] {
                for child in nested.prefix(8) { visit(child, depth: depth + 1) }
            }
        }
        visit(error, depth: 0)
        return result
    }
    private static func emit(_ safeMessage: String) {
        #if canImport(OSLog)
        Logger(subsystem: "com.familycaragent.auth.diagnostics", category: "AppleSignIn")
            .notice("FCA_APPLE_AUTH_DIAG \(safeMessage, privacy: .public)")
        #else
        print("FCA_APPLE_AUTH_DIAG \(safeMessage)")
        #endif
    }
}
#endif

enum Field: Encodable, Sendable {
    case text(String), flag(Bool)
    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self { case .text(let v): try c.encode(v); case .flag(let v): try c.encode(v) }
    }
}

struct Me: Decodable, Sendable {
    let user_id: Int64
    let name: String
    let family_id: Int64
}
struct JoinState: Decodable, Sendable {
    let step: String
    let family_name: String?
    let normalized_address: String?
    let resolved_address: String?
}
struct AddressResult: Decodable, Sendable {
    let display_address: String
    let normalized_address: String
    let resolution_token: String
}
struct CreatedResult: Decodable, Sendable { let created: Bool }
struct FamilyCode: Decodable, Sendable { let family_code: String }

struct SupabaseTokenResponse: Decodable, Sendable {
    struct User: Decodable, Sendable { let id: UUID }
    let access_token: String
    let refresh_token: String
    let expires_in: Double
    let user: User
}

protocol BackendTransport: Sendable {
    func backend<T: Decodable & Sendable>(_ type: T.Type, path: String, token: String,
                                          fields: [String: Field]?) async throws -> T
}

private final class NoRedirect: NSObject, URLSessionTaskDelegate, Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping @Sendable (URLRequest?) -> Void) { completionHandler(nil) }
}

/// No shared cookies/cache, redirects, raw errors, token logging, or arbitrary destinations.
final class AuthAPI: AuthTransport, BackendTransport, Sendable {
    let environment: AppEnvironment
    private let publicKey: String
    private let http: URLSession
    init(environment: AppEnvironment, publicKey: String) throws {
        guard Self.validPublicKey(publicKey) else { throw AuthFailure.configuration }
        self.environment = environment; self.publicKey = publicKey
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil; configuration.urlCache = nil
        configuration.timeoutIntervalForRequest = 20; configuration.timeoutIntervalForResource = 30
        self.http = URLSession(configuration: configuration, delegate: NoRedirect(), delegateQueue: nil)
    }
    static func validPublicKey(_ key: String) -> Bool {
        // Publishable only: never accept service-role, secret keys or arbitrary JWTs.
        key.range(of: "^sb_publishable_[A-Za-z0-9_-]+$", options: .regularExpression) != nil
    }
    private func send<T: Decodable & Sendable>(_ type: T.Type, url: URL, method: String,
                                               body: Data?, token: String?, auth: Bool, appleDiagnostic: Bool = false) async throws -> T {
        var request = URLRequest(url: url)
        request.httpMethod = method; request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if body != nil { request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        if auth { request.setValue(publicKey, forHTTPHeaderField: "apikey") }
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        let data: Data; let response: URLResponse
        do { (data, response) = try await http.data(for: request) }
        catch is CancellationError {
            #if DEBUG
            if appleDiagnostic { AppleAuthDiagnostics.event("exchange_transport_cancelled") }
            #endif
            throw AuthFailure.cancelled
        }
        catch {
            #if DEBUG
            if appleDiagnostic { AppleAuthDiagnostics.error(error) }
            #endif
            throw AuthFailure.network
        }
        #if DEBUG
        if appleDiagnostic, let httpResponse = response as? HTTPURLResponse {
            AppleAuthDiagnostics.status(httpResponse.statusCode)
        }
        #endif
        guard let response = response as? HTTPURLResponse, data.count <= 1_048_576 else { throw AuthFailure.invalidResponse }
        guard (200..<300).contains(response.statusCode) else {
            throw Self.failure(status: response.statusCode, data: data, path: url.path)
        }
        do { return try JSONDecoder().decode(type, from: data) }
        catch { throw AuthFailure.invalidResponse }
    }
    static func failure(status: Int, data: Data, path: String) -> AuthFailure {
        guard data.count <= 8192, let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            return .rejected(status, "")
        }
        if path == "/api/me", status == 403, let text = json["detail"] as? String,
           ["Authenticated user is not registered in the application", "Authenticated user is not assigned to a family"].contains(text) {
            return .rejected(status, "MISSING_ACCOUNT")
        }
        let detail = json["detail"] as? [String: Any]
        let code = (detail?["code"] ?? json["error_code"] ?? json["error"]) as? String ?? ""
        let allowed = Set(["ACCOUNT_UNAVAILABLE", "AUTH_USER_ALREADY_MAPPED", "AUTH_SESSION_INVALID", "UNAUTHORIZED",
                           "INVALID_JOIN_STEP", "JOIN_LOCKED", "INVALID_FAMILY_NAME", "INVALID_USER_NAME",
                           "ADDRESS_RESOLUTION_EXPIRED", "FAMILY_ALREADY_EXISTS_AT_ADDRESS", "JOIN_FAMILY_NAME_NOT_FOUND",
                           "INVALID_FAMILY_CODE", "JOIN_FAMILY_ADDRESS_NOT_FOUND", "ADDRESS_NOT_FOUND", "INVALID_ADDRESS_FORMAT",
                           "ADDRESS_TOO_LONG", "refresh_token_not_found", "refresh_token_already_used", "invalid_grant",
                           "session_not_found", "user_not_found"])
        return .rejected(status, allowed.contains(code) ? code : "")
    }
    func exchange(grant: String, fields: [String: String]) async throws -> AuthSession {
        #if DEBUG
        let googleDiagnostic = grant == "pkce"
        if googleDiagnostic { GoogleAuthDiagnostics.event("session_exchange_started") }
        var googleSucceeded = false
        defer {
            if googleDiagnostic {
                if googleSucceeded { GoogleAuthDiagnostics.event("session_exchange_succeeded") }
                else { GoogleAuthDiagnostics.event("session_exchange_failed") }
            }
        }
        let appleDiagnostic = grant == "id_token" && fields["provider"] == "apple"
        if appleDiagnostic { AppleAuthDiagnostics.event("supabase_exchange_started") }
        var diagnosticSucceeded = false
        defer {
            if appleDiagnostic {
                if diagnosticSucceeded { AppleAuthDiagnostics.event("supabase_exchange_succeeded") }
                else { AppleAuthDiagnostics.event("supabase_exchange_failed") }
            }
        }
        #else
        let appleDiagnostic = false
        #endif
        guard ["pkce", "id_token", "refresh_token"].contains(grant) else { throw AuthFailure.configuration }
        let url = environment.supabaseURL.appendingPathComponent("auth/v1/token")
            .appending(queryItems: [URLQueryItem(name: "grant_type", value: grant)])
        let value = try await send(SupabaseTokenResponse.self, url: url, method: "POST", body: JSONEncoder().encode(fields), token: nil, auth: true, appleDiagnostic: appleDiagnostic)
        let session = try Self.session(from: value)
        #if DEBUG
        diagnosticSucceeded = true
        googleSucceeded = true
        #endif
        return session
    }
    static func session(from value: SupabaseTokenResponse, now: Date = Date()) throws -> AuthSession {
        guard !value.access_token.isEmpty, !value.refresh_token.isEmpty, value.expires_in > 0,
              value.expires_in <= 604800 else { throw AuthFailure.invalidResponse }
        return AuthSession(owner: value.user.id, accessToken: value.access_token, refreshToken: value.refresh_token,
                           expires: now.addingTimeInterval(value.expires_in))
    }
    func backend<T: Decodable & Sendable>(_ type: T.Type, path: String, token: String,
                                          fields: [String: Field]? = nil) async throws -> T {
        let paths: Set<String> = ["/api/me", "/api/family", "/api/onboarding/create-family/address", "/api/onboarding/create-family",
            "/api/onboarding/join-family/start", "/api/onboarding/join-family/family-name", "/api/onboarding/join-family/address",
            "/api/onboarding/join-family/address-confirmation", "/api/onboarding/join-family/code", "/api/onboarding/join-family/complete"]
        guard paths.contains(path) else { throw AuthFailure.configuration }
        return try await send(type, url: environment.backendURL.appendingPathComponent(String(path.dropFirst())),
                              method: fields == nil ? "GET" : "POST", body: try fields.map { try JSONEncoder().encode($0) }, token: token, auth: false)
    }
}
