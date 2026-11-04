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
    let location: VerifiedLocation?
    private enum CodingKeys: String, CodingKey { case step, family_name, normalized_address, resolved_address }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        step = try c.decode(String.self, forKey: .step)
        family_name = try c.decodeIfPresent(String.self, forKey: .family_name)
        normalized_address = try c.decodeIfPresent(String.self, forKey: .normalized_address)
        resolved_address = try c.decodeIfPresent(String.self, forKey: .resolved_address)
        location = VerifiedLocation.decode(from: decoder)
    }
}
struct AddressResult: Decodable, Sendable {
    let display_address: String
    let normalized_address: String
    let resolution_token: String
    let location: VerifiedLocation?
    private enum CodingKeys: String, CodingKey { case display_address, normalized_address, resolution_token }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        display_address = try c.decode(String.self, forKey: .display_address)
        normalized_address = try c.decode(String.self, forKey: .normalized_address)
        resolution_token = try c.decode(String.self, forKey: .resolution_token)
        location = VerifiedLocation.decode(from: decoder)
    }
}
/// Optional presentation data only: never authorizes address confirmation or saving.
struct VerifiedLocation: Equatable, Hashable, Sendable {
    let latitude: Double
    let longitude: Double
    private enum CodingKeys: String, CodingKey { case latitude, longitude }
    static func decode(from decoder: Decoder) -> Self? {
        guard let c = try? decoder.container(keyedBy: CodingKeys.self),
              let lat = try? c.decode(Double.self, forKey: .latitude),
              let lon = try? c.decode(Double.self, forKey: .longitude),
              lat.isFinite, lon.isFinite, (-90...90).contains(lat), (-180...180).contains(lon) else { return nil }
        return Self(latitude: lat, longitude: lon)
    }
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
final class AuthAPI: AuthTransport, BackendTransport, ChatTransport, FamilyTransport, VehiclesTransport, VehicleDetailsTransport, HistoryTransport, Sendable {
    let environment: AppEnvironment
    private let publicKey: String
    private let http: URLSession
    private let chatHTTP: URLSession
    init(environment: AppEnvironment, publicKey: String) throws {
        guard Self.validPublicKey(publicKey) else { throw AuthFailure.configuration }
        self.environment = environment; self.publicKey = publicKey
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil; configuration.urlCache = nil
        configuration.timeoutIntervalForRequest = 20; configuration.timeoutIntervalForResource = 30
        self.http = URLSession(configuration: configuration, delegate: NoRedirect(), delegateQueue: nil)
        self.chatHTTP = URLSession(configuration: Self.chatConfiguration(), delegate: NoRedirect(), delegateQueue: nil)
    }
    static func chatConfiguration() -> URLSessionConfiguration {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil; configuration.urlCache = nil
        configuration.timeoutIntervalForRequest = 90
        configuration.timeoutIntervalForResource = 90
        return configuration
    }
    /// Fixed destinations only; never use the Supabase public key on Backend requests.
    func makeChatRequest(token: String, id: UUID?, message: String?) throws -> URLRequest {
        guard (id == nil) == (message == nil) else { throw AuthFailure.configuration }
        var components = URLComponents(url: environment.backendURL.appendingPathComponent(
            id == nil ? "api/chat/history" : "api/chat"), resolvingAgainstBaseURL: false)!
        if id == nil { components.queryItems = [URLQueryItem(name: "limit", value: "30")] }
        guard let url = components.url else { throw AuthFailure.configuration }
        var request = URLRequest(url: url)
        request.httpMethod = id == nil ? "GET" : "POST"
        request.timeoutInterval = id == nil ? 15 : 90
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if let id, let message {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(["request_id": id.uuidString.lowercased(), "message": message])
        }
        return request
    }
    func chat(token: String, id: UUID?, message: String?) async throws -> Data {
        let request = try makeChatRequest(token: token, id: id, message: message)
        let data: Data; let response: URLResponse
        do { (data, response) = try await chatHTTP.data(for: request) }
        catch { throw ChatFailure.uncertain } // Cancellation cannot establish server-side cancellation.
        guard let response = response as? HTTPURLResponse else { throw ChatFailure.uncertain }
        guard (200..<300).contains(response.statusCode) else {
            throw ChatFailure.parse(status: response.statusCode, data: data,
                                    retryHeader: response.value(forHTTPHeaderField: "Retry-After"))
        }
        guard data.count <= 1_048_576 else { throw ChatFailure.uncertain }
        return data
    }
    func family(token: String, operation: FamilyOperation) async throws -> FamilyReply {
        let url = environment.backendURL.appendingPathComponent(String(operation.path.dropFirst()))
        let body = try operation.body()
        func load<T: Decodable & Sendable>(_ type: T.Type) async throws -> T {
            try await send(type, url: url, method: operation.method, body: body, token: token, auth: false)
        }
        switch operation {
        case .profile: return .profile(try await load(FamilyProfile.self).validated())
        case .role(let id, _):
            let member = try await load(FamilyMember.self)
            guard member.id == id else { throw AuthFailure.invalidResponse }
            return .member(member)
        case .resolve:
            let value = try await load(AddressResult.self)
            guard [value.display_address, value.normalized_address, value.resolution_token].allSatisfy({ !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) else { throw AuthFailure.invalidResponse }
            return .candidate(value)
        case .address:
            let value = try await load(FamilyAddressUpdate.self)
            guard !value.home_address.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw AuthFailure.invalidResponse }
            return .address(value.home_address)
        case .regenerate:
            let value = try await load(FamilyCode.self)
            guard FamilyInvitation.validCode(value.family_code) else { throw AuthFailure.invalidResponse }
            return .code(value.family_code)
        }
    }
    func history(token: String, operation: HistoryOperation) async throws -> HistoryReply {
        if case .page(let filters, _) = operation, !filters.valid { throw AuthFailure.configuration }
        var components = URLComponents(url: environment.backendURL.appendingPathComponent(String(operation.path.dropFirst())), resolvingAgainstBaseURL: false)!
        components.queryItems = operation.query.isEmpty ? nil : operation.query
        guard let url = components.url else { throw AuthFailure.configuration }
        func load<T: Decodable & Sendable>(_ type: T.Type) async throws -> T {
            try await send(type, url: url, method: "GET", body: nil, token: token, auth: false)
        }
        switch operation {
        case .page: return .page(try await load(HistoryPage.self))
        case .current:
            let values = try await load([HistoryVehicle].self)
            guard Set(values.map(\.id)).count == values.count else { throw AuthFailure.invalidResponse }
            return .current(values)
        case .members:
            let values = try await load(HistoryMembers.self).members
            guard Set(values.map(\.id)).count == values.count else { throw AuthFailure.invalidResponse }
            return .members(values)
        }
    }
    func vehiclesURL(_ operation: VehiclesOperation) -> URL {
        environment.backendURL.appendingPathComponent(String(operation.path.dropFirst())).appending(queryItems: operation.query)
    }
    func vehicles(token: String, operation: VehiclesOperation) async throws -> VehiclesReply {
        let body = try operation.body()
        func load<T: Decodable & Sendable>(_ type: T.Type) async throws -> T {
            try await send(type, url: vehiclesURL(operation), method: operation.method, body: body, token: token, auth: false)
        }
        switch operation {
        case .list:
            let rows = try await load([ManagedVehicle].self)
            guard Set(rows.map(\.id)).count == rows.count else { throw AuthFailure.invalidResponse }
            return .list(rows)
        case .permission: return .permission(try await load(VehiclePermission.self).can_edit_roles)
        case .manufacturers:
            let rows = try await load([VehicleManufacturer].self)
            guard rows.allSatisfy({ $0.id > 0 }), Set(rows.map(\.id)).count == rows.count else { throw AuthFailure.invalidResponse }
            return .manufacturers(rows)
        case .create: return .created(try await load(ManagedVehicle.self))
        }
    }
    func vehicleDetails(token: String, id: UUID, operation: VehicleDetailsOperation) async throws -> VehicleDetailsReply {
        let url = environment.backendURL.appendingPathComponent(String(operation.path(id).dropFirst()))
        let body = try operation.body()
        func load<T: Decodable & Sendable>(_ type: T.Type) async throws -> T {
            try await send(type, url: url, method: operation.method, body: body, token: token, auth: false)
        }
        switch operation {
        case .detail:
            let value = try await load(VehicleDetail.self)
            guard value.vehicle.id == id else { throw AuthFailure.invalidResponse }
            return .detail(value)
        case .maintenance:
            let values = try await load([VehicleMaintenance].self)
            guard Set(values.map(\.id)).count == values.count else { throw AuthFailure.invalidResponse }
            return .maintenance(values)
        case .edit, .retire:
            let value = try await load(ManagedVehicle.self)
            guard value.id == id else { throw AuthFailure.invalidResponse }
        case .add: _ = try await load(VehicleMaintenance.self)
        case .update(let item, _), .complete(let item):
            guard try await load(VehicleMaintenance.self).id == item else { throw AuthFailure.invalidResponse }
        case .delete: _ = try await load(VehicleDeletionReceipt.self)
        }
        return .saved
    }
    static func validPublicKey(_ key: String) -> Bool {
        // Publishable only: never accept service-role, secret keys or arbitrary JWTs.
        key.range(of: "^sb_publishable_[A-Za-z0-9_-]+$", options: .regularExpression) != nil
    }
    func usableVehicleBindings(device: UUID, token: String) async throws -> [UUID: String] {
        struct Binding: Decodable { let vehicle_ref: UUID; let display_name: String; let usable: Bool }
        let url = environment.backendURL.appendingPathComponent("api/devices/\(device.uuidString)/vehicle-bindings")
        let bindings = try await send([Binding].self, url: url, method: "GET", body: nil, token: token, auth: false)
        var result: [UUID: String] = [:]
        for binding in bindings where binding.usable { result[binding.vehicle_ref] = binding.display_name }
        return result
    }

    /// Read-only ownership check at explicit opt-in, never on offline enqueue.
    func permitsVehicleDevice(_ id: UUID, token: String) async throws -> Bool {
        struct Device: Decodable, Sendable { let device_ref: UUID; let platform: String; let revoked_at: String? }
        var parts = URLComponents(url: environment.backendURL.appendingPathComponent("api/devices"), resolvingAgainstBaseURL: false)
        parts?.queryItems = [URLQueryItem(name: "platform", value: "ios")]
        guard let url = parts?.url else { throw AuthFailure.configuration }
        let rows = try await send([Device].self, url: url, method: "GET", body: nil, token: token, auth: false)
        return rows.contains { $0.device_ref == id && $0.platform == "ios" && $0.revoked_at == nil }
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
        // Only the maintenance DELETE contract accepts an empty 204 response.
        if type == VehicleDeletionReceipt.self {
            guard method == "DELETE", response.statusCode == 204, data.isEmpty else { throw AuthFailure.invalidResponse }
            return VehicleDeletionReceipt() as! T
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
