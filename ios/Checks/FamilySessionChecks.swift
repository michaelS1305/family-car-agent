import Foundation

actor FamilySessionBackend: BackendTransport, FamilyTransport {
    var calls = 0
    var unauthorized = true
    var paused = false
    var continuation: CheckedContinuation<Void, Never>?
    var paths: [String] = []
    var bodies: [Data?] = []
    func pause() { paused = true }
    func release() { paused = false; continuation?.resume(); continuation = nil }
    func backend<T: Decodable & Sendable>(_ type: T.Type, path: String, token: String, fields: [String: Field]?) async throws -> T {
        guard path == "/api/me" else { throw AuthFailure.invalidResponse }
        return try JSONDecoder().decode(type, from: Data(#"{"user_id":1,"family_id":2,"name":"Mock"}"#.utf8))
    }
    func family(token: String, operation: FamilyOperation) async throws -> FamilyReply {
        calls += 1; paths.append(operation.path); bodies.append(try operation.body())
        if unauthorized { unauthorized = false; throw AuthFailure.rejected(401, "") }
        if paused { await withCheckedContinuation { continuation = $0 } }
        return .code("abc123")
    }
}

@MainActor func runFamilySessionChecks() async throws {
    let session = AuthSession(owner: UUID(), accessToken: "synthetic", refreshToken: "synthetic", expires: Date().addingTimeInterval(3600))
    let auth = TestTransport(session)
    let manager = SessionManager(vault: TestVault(), transport: auth)
    let backend = FamilySessionBackend()
    let entry = EntryModel(sessions: manager, api: backend, providers: TestProvider())
    AuthCheck.check(entry.familyIdentity == nil, "Family blocked before activation")
    await entry.login(apple: false)
    guard let identity = entry.familyIdentity else { preconditionFailure("Family identity missing") }
    _ = try await entry.familyRequest(identity: identity, operation: .address("synthetic"))
    let paths = await backend.paths; let bodies = await backend.bodies
    AuthCheck.check(paths == ["/api/family/address", "/api/family/address"] && bodies[0] == bodies[1], "401 retries same operation only")
    AuthCheck.check(await auth.calls == 2, "Family shares existing refresh mechanism")
    await backend.pause()
    let late = Task { try await entry.familyRequest(identity: identity, operation: .profile) }
    while await backend.continuation == nil { await Task.yield() }
    entry.logout(); await backend.release()
    do { _ = try await late.value; preconditionFailure("old Family reply accepted") }
    catch { AuthCheck.check(error as? AuthFailure == .stale, "Family logout rejects late reply") }
    let before = await backend.calls
    do { _ = try await entry.familyRequest(identity: identity, operation: .regenerate); preconditionFailure("old identity sent") }
    catch { AuthCheck.check(error as? AuthFailure == .stale, "Family old identity rejected before send") }
    AuthCheck.check(await backend.calls == before, "Family stale action makes no request")
    await entry.login(apple: false)
    guard let next = entry.familyIdentity else { preconditionFailure("new Family identity missing") }
    let cancelled = Task { try await entry.familyRequest(identity: next, operation: .profile) }
    cancelled.cancel()
    do { _ = try await cancelled.value; preconditionFailure("cancelled request sent") }
    catch { AuthCheck.check(error is CancellationError, "Family cancellation before network") }
    AuthCheck.check(await backend.calls == before, "cancelled action makes no request")
    entry.logout()
}
