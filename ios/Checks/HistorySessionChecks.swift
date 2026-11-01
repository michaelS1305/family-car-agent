import Foundation

actor HistorySessionBackend: BackendTransport, HistoryTransport {
    var calls = 0
    var unauthorized = true
    var paused = false
    var continuation: CheckedContinuation<Void, Never>?
    func pause() { paused = true }
    func release() { paused = false; continuation?.resume(); continuation = nil }
    func backend<T: Decodable & Sendable>(_ type: T.Type, path: String, token: String, fields: [String: Field]?) async throws -> T {
        guard path == "/api/me" else { throw AuthFailure.invalidResponse }
        return try JSONDecoder().decode(type, from: Data(#"{"user_id":1,"family_id":2,"name":"Synthetic"}"#.utf8))
    }
    func history(token: String, operation: HistoryOperation) async throws -> HistoryReply {
        calls += 1
        if unauthorized { unauthorized = false; throw AuthFailure.rejected(401, "") }
        if paused { await withCheckedContinuation { continuation = $0 } }
        return .current([])
    }
}
@MainActor func runHistorySessionChecks() async throws {
    let session = AuthSession(owner: UUID(), accessToken: "synthetic", refreshToken: "synthetic", expires: Date().addingTimeInterval(3600))
    let auth = TestTransport(session), backend = HistorySessionBackend()
    let entry = EntryModel(sessions: SessionManager(vault: TestVault(), transport: auth), api: backend, providers: TestProvider())
    AuthCheck.check(entry.chatIdentity == nil, "History gated before activation")
    await entry.login(apple: false)
    let identity = entry.chatIdentity!
    _ = try await entry.historyRequest(identity: identity, operation: .current)
    AuthCheck.check(await backend.calls == 2, "History retries only explicit 401")
    AuthCheck.check(await auth.calls == 2, "History uses existing token refresh")
    await backend.pause()
    let late = Task { try await entry.historyRequest(identity: identity, operation: .current) }
    while await backend.continuation == nil { await Task.yield() }
    entry.logout(); await backend.release()
    do { _ = try await late.value; preconditionFailure("late History accepted") }
    catch { AuthCheck.check(error as? AuthFailure == .stale, "History response fenced after logout") }
    let before = await backend.calls
    do { _ = try await entry.historyRequest(identity: identity, operation: .current); preconditionFailure("stale request") }
    catch { AuthCheck.check(error as? AuthFailure == .stale, "History stale request rejected") }
    AuthCheck.check(await backend.calls == before, "History stale request never sent")
}
