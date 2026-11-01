import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

actor ChatSessionBackend: BackendTransport, ChatTransport {
    var chats = 0
    var unauthorizedOnce = true
    var paused = false
    var continuation: CheckedContinuation<Void, Never>?
    var ids: [UUID?] = []
    var texts: [String?] = []
    func pause() { paused = true }
    func release() { paused = false; continuation?.resume(); continuation = nil }
    func backend<T: Decodable & Sendable>(_ type: T.Type, path: String, token: String, fields: [String: Field]?) async throws -> T {
        guard path == "/api/me" else { throw AuthFailure.invalidResponse }
        return try JSONDecoder().decode(type, from: Data(#"{"user_id":1,"family_id":2,"name":"Mock"}"#.utf8))
    }
    func chat(token: String, id: UUID?, message: String?) async throws -> Data {
        chats += 1; ids.append(id); texts.append(message)
        if unauthorizedOnce { unauthorizedOnce = false; throw ChatFailure(kind: .auth, status: 401) }
        if paused { await withCheckedContinuation { continuation = $0 } }
        if let id {
            return Data("{\"request_id\":\"\(id)\",\"status\":\"completed\",\"assistant_message\":{\"role\":\"assistant\",\"content\":\"Mock\",\"created_at\":\"2026-10-30T10:00:00Z\"}}".utf8)
        }
        return Data(#"{"messages":[]}"#.utf8)
    }
}

@MainActor func runChatSessionChecks() async throws {
    try await runStartupPresentationChecks()
    let api = try AuthAPI(environment: .development, publicKey: "sb_publishable_synthetic")
    let historyRequest = try api.makeChatRequest(token: "synthetic", id: nil, message: nil)
    AuthCheck.check(historyRequest.url?.path == "/api/chat/history" && historyRequest.url?.query == "limit=30" && historyRequest.httpMethod == "GET", "history query encoded independently from path")
    let requestID = UUID()
    let sendRequest = try api.makeChatRequest(token: "synthetic", id: requestID, message: "שלום")
    let body = try JSONSerialization.jsonObject(with: sendRequest.httpBody!) as? [String: String]
    AuthCheck.check(sendRequest.url?.path == "/api/chat" && sendRequest.url?.query == nil && sendRequest.httpMethod == "POST", "send fixed endpoint")
    AuthCheck.check(body == ["request_id": requestID.uuidString.lowercased(), "message": "שלום"], "send JSON contract")
    AuthCheck.check(sendRequest.value(forHTTPHeaderField: "apikey") == nil && sendRequest.value(forHTTPHeaderField: "Authorization") == "Bearer synthetic", "backend bearer only")
    let configuration = AuthAPI.chatConfiguration()
    AuthCheck.check(sendRequest.timeoutInterval == 90 && configuration.timeoutIntervalForRequest == 90 && configuration.timeoutIntervalForResource == 90 && historyRequest.timeoutInterval == 15, "chat timeout budgets")
    AuthCheck.check(configuration.httpCookieStorage == nil && configuration.urlCache == nil, "chat no shared cache or cookies")
    do { _ = try api.makeChatRequest(token: "synthetic", id: requestID, message: nil); preconditionFailure("invalid operation") }
    catch { AuthCheck.check(error as? AuthFailure == .configuration, "incomplete operation rejected before network") }
    let vault = TestVault()
    let session = AuthSession(owner: UUID(), accessToken: "synthetic", refreshToken: "synthetic", expires: Date().addingTimeInterval(3600))
    let auth = TestTransport(session)
    let manager = SessionManager(vault: vault, transport: auth)
    let backend = ChatSessionBackend()
    let entry = EntryModel(sessions: manager, api: backend, providers: TestProvider())
    AuthCheck.check(entry.chatIdentity == nil, "chat unavailable before activated account")
    await entry.login(apple: false)
    guard let identity = entry.chatIdentity else { preconditionFailure("ready identity") }
    AuthCheck.check(identity.owner == session.owner && identity.user == 1 && identity.family == 2, "chat bound to authenticated account and family")
    let id = UUID()
    let reply = try await entry.chatSend(identity: identity, id: id, message: "Synthetic")
    let ids = await backend.ids; let texts = await backend.texts; let refreshes = await auth.calls
    AuthCheck.check(reply.requestID == id && ids == [id, id] && texts == ["Synthetic", "Synthetic"], "401 retry retains request id and payload")
    AuthCheck.check(refreshes == 2, "chat uses existing session refresh exactly once")
    let history = try await entry.chatHistory(identity: identity)
    AuthCheck.check(history.isEmpty, "authenticated history")
    await backend.pause()
    let late = Task { try await entry.chatHistory(identity: identity) }
    while await backend.continuation == nil { await Task.yield() }
    entry.logout()
    await backend.release()
    do { _ = try await late.value; preconditionFailure("late history accepted") }
    catch { AuthCheck.check(error as? AuthFailure == .stale, "late session result rejected") }
    let before = await backend.chats
    do { _ = try await entry.chatSend(identity: identity, id: UUID(), message: "Synthetic"); preconditionFailure("old identity sent") }
    catch { AuthCheck.check(error as? AuthFailure == .stale, "old identity cannot send") }
    let after = await backend.chats
    AuthCheck.check(before == after && entry.chatIdentity == nil, "logout makes no stale network request")
}

@MainActor private func runStartupPresentationChecks() async throws {
    let vault = TestVault()
    let session = AuthSession(owner: UUID(), accessToken: "synthetic", refreshToken: "synthetic",
                              expires: Date().addingTimeInterval(3600), activated: true, appleUser: "synthetic")
    vault.value = session
    let backend = TestBackend(); let provider = TestProvider()
    let manager = SessionManager(vault: vault, transport: TestTransport(session))
    let entry = EntryModel(sessions: manager, api: backend, providers: provider)
    AuthCheck.check(entry.restoring && entry.me == nil && entry.chatIdentity == nil, "cold start exposes no account before restore")
    await backend.reply("/api/me", #"{"user_id":1,"family_id":2,"name":"Mock"}"#)
    await backend.pause()
    let startup = Task { await entry.start() }
    while await backend.continuation == nil { await Task.yield() }
    AuthCheck.check(entry.restoring && entry.busy && entry.screen == .bootstrap && entry.me == nil && entry.chatIdentity == nil,
                    "pending bootstrap never exposes saved user data")
    await entry.start() // A second lifecycle event must not start another bootstrap.
    let initialPaths = await backend.paths
    AuthCheck.check(initialPaths == ["/api/me"], "startup is single flight")
    await backend.release(); await startup.value
    let identity = entry.chatIdentity
    AuthCheck.check(!entry.restoring && !entry.busy && entry.screen == .ready && identity != nil, "verified startup goes directly ready")
    await entry.resume()
    let resumedPaths = await backend.paths
    AuthCheck.check(entry.screen == .ready && !entry.busy && entry.chatIdentity == identity && resumedPaths == initialPaths,
                    "foreground preserves verified shell without bootstrap")
    provider.valid = false
    await entry.resume()
    AuthCheck.check(entry.screen == .intro && entry.me == nil && entry.chatIdentity == nil && vault.value == nil, "revoked Apple account clears shell safely")

    let retryVault = TestVault(); retryVault.value = session
    let retryBackend = TestBackend()
    let retryEntry = EntryModel(sessions: SessionManager(vault: retryVault, transport: TestTransport(session)),
                               api: retryBackend, providers: TestProvider())
    await retryBackend.fail("/api/me", .network)
    await retryEntry.start()
    AuthCheck.check(!retryEntry.restoring && !retryEntry.busy && retryEntry.screen == .bootstrap && retryEntry.error != nil && retryEntry.me == nil,
                    "temporary startup failure permits retry without private account content")
    await retryBackend.reply("/api/me", #"{"user_id":1,"family_id":2,"name":"Mock"}"#)
    await retryEntry.retry()
    AuthCheck.check(retryEntry.screen == .ready && retryEntry.error == nil, "bootstrap retry succeeds")

    let invalidVault = TestVault(); invalidVault.value = session
    let invalidBackend = TestBackend()
    let invalidEntry = EntryModel(sessions: SessionManager(vault: invalidVault, transport: TestTransport(session)),
                                 api: invalidBackend, providers: TestProvider())
    await invalidBackend.fail("/api/me", .rejected(403, "ACCOUNT_UNAVAILABLE"))
    await invalidEntry.start()
    AuthCheck.check(!invalidEntry.restoring && invalidEntry.screen == .intro && invalidEntry.me == nil && invalidVault.value == nil,
                    "invalid account returns safely to entry")
    let emptyEntry = EntryModel(sessions: SessionManager(vault: TestVault(), transport: TestTransport(session)),
                               api: TestBackend(), providers: TestProvider())
    await emptyEntry.start()
    AuthCheck.check(!emptyEntry.restoring && emptyEntry.screen == .intro && emptyEntry.chatIdentity == nil, "no saved session enters intro")

    let foregroundVault = TestVault(); foregroundVault.value = session
    let foregroundBackend = TestBackend(); let foregroundProvider = PausedForegroundProvider()
    let foregroundEntry = EntryModel(sessions: SessionManager(vault: foregroundVault, transport: TestTransport(session)),
                                    api: foregroundBackend, providers: foregroundProvider)
    await foregroundBackend.reply("/api/me", #"{"user_id":1,"family_id":2,"name":"Mock"}"#)
    await foregroundEntry.start()
    let foregroundIdentity = foregroundEntry.chatIdentity
    foregroundProvider.paused = true
    let resume = Task { await foregroundEntry.resume() }
    while foregroundProvider.continuation == nil { await Task.yield() }
    AuthCheck.check(foregroundEntry.screen == .ready && !foregroundEntry.busy && !foregroundEntry.restoring && foregroundEntry.chatIdentity == foregroundIdentity,
                    "verified shell remains visible during foreground validation")
    foregroundProvider.continuation?.resume(throwing: AuthFailure.network)
    foregroundProvider.continuation = nil
    await resume.value
    AuthCheck.check(foregroundEntry.screen == .ready && foregroundEntry.chatIdentity == foregroundIdentity,
                    "credential lookup network error is not treated as revocation")
}

@MainActor private final class PausedForegroundProvider: NativeAuthProvider {
    var paused = false
    var continuation: CheckedContinuation<Bool, Error>?
    func authorize(apple: Bool) async throws -> ProviderResult { throw AuthFailure.cancelled }
    func cancel() {}
    func credentialValid(_ user: String) async throws -> Bool {
        if paused { return try await withCheckedThrowingContinuation { continuation = $0 } }
        return true
    }
}
