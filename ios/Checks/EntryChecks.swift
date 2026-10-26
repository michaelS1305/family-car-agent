import Foundation
#if !canImport(Combine)
// Linux checks exercise the actual EntryModel. These shims have no UI/rendering claims.
protocol ObservableObject: AnyObject {}
@propertyWrapper struct Published<Value> {
    var wrappedValue: Value
    init(wrappedValue: Value) { self.wrappedValue = wrappedValue }
}
#endif

actor TestBackend: BackendTransport {
    var replies: [String: [Result<Data, AuthFailure>]] = [:]
    var paths: [String] = []
    var paused = false
    var continuation: CheckedContinuation<Void, Never>?
    func pause() { paused = true }
    func release() { paused = false; continuation?.resume(); continuation = nil }
    func reply(_ path: String, _ json: String) { replies[path, default: []].append(.success(Data(json.utf8))) }
    func fail(_ path: String, _ error: AuthFailure) { replies[path, default: []].append(.failure(error)) }
    func backend<T: Decodable & Sendable>(_ type: T.Type, path: String, token: String, fields: [String: Field]?) async throws -> T {
        paths.append(path)
        guard var queue = replies[path], !queue.isEmpty else { throw AuthFailure.invalidResponse }
        let item = queue.removeFirst(); replies[path] = queue
        if paused { await withCheckedContinuation { continuation = $0 } }
        return try JSONDecoder().decode(type, from: item.get())
    }
}
@MainActor final class TestProvider: NativeAuthProvider {
    var valid = true
    var failure: AuthFailure?
    func authorize(apple: Bool) async throws -> ProviderResult {
        if let failure { throw failure }
        return ProviderResult(grant: apple ? "id_token" : "pkce", fields: [:], appleUser: apple ? "test-apple" : nil)
    }
    func cancel() {}
    func credentialValid(_ user: String) async throws -> Bool { valid }
}

@MainActor func runEntryChecks() async throws {
    let owner = UUID()
    let session = AuthSession(owner: owner, accessToken: "fake", refreshToken: "fake-refresh", expires: Date().addingTimeInterval(3600))
    let profile = #"{"user_id":1,"family_id":2,"name":"Test"}"#
    let vault = TestVault(); let backend = TestBackend(); let provider = TestProvider()
    let manager = SessionManager(vault: vault, transport: TestTransport(session))
    let model = EntryModel(sessions: manager, api: backend, providers: provider)
    await backend.reply("/api/me", profile)
    await model.login(apple: false)
    AuthCheck.check(model.screen == .ready && model.me?.family_id == 2 && vault.value?.activated == true, "existing account bootstrap activates")
    let calls = await backend.paths.count
    await model.resume()
    let afterResume = await backend.paths.count
    AuthCheck.check(model.screen == .ready && calls == afterResume, "ordinary resume preserves ready screen")
    model.logout()
    AuthCheck.check(model.me == nil && model.screen == .intro && vault.value == nil, "logout clears screen identity")
    await backend.fail("/api/me", .rejected(403, "MISSING_ACCOUNT"))
    await model.login(apple: true)
    AuthCheck.check(model.screen == .intro && model.me == nil && vault.value == nil, "unmapped existing-account login clears session")
    await backend.fail("/api/me", .network)
    await model.login(apple: false)
    AuthCheck.check(model.screen == .bootstrap && vault.value != nil && model.me == nil, "transient bootstrap preserves credentials but not ready state")
    await backend.reply("/api/me", profile)
    await model.retry()
    AuthCheck.check(model.screen == .ready, "bootstrap retry")
    model.logout()
    provider.failure = .cancelled
    await model.login(apple: true)
    AuthCheck.check(model.screen == .intro && vault.value == nil, "provider cancellation")
    provider.failure = nil

    model.route = .create
    await model.login(apple: true)
    AuthCheck.check(model.screen == .onboarding && model.step == 1 && vault.value?.activated == false, "create route does not auto-associate")
    model.familyName = "כהן"; await model.next()
    AuthCheck.check(model.step == 2, "family name local step")
    model.address = "עיר, רחוב, 1"
    await backend.reply("/api/onboarding/create-family/address", #"{"normalized_address":"address","display_address":"address","resolution_token":"test-confirmation"}"#)
    await model.next()
    AuthCheck.check(model.step == 3 && model.resolvedAddress == "address", "current address contract without fabricated coordinates")
    await model.next(); model.userName = "מיכאל"
    let beforeConsent = await backend.paths.count
    await model.next()
    let afterConsent = await backend.paths.count
    AuthCheck.check(beforeConsent == afterConsent && model.screen == .onboarding, "explicit consent required")
    model.consent = true
    await backend.reply("/api/onboarding/create-family", #"{"created":true}"#)
    await backend.fail("/api/me", .network)
    await model.next()
    AuthCheck.check(model.screen == .onboarding && vault.value?.activated == false, "create success requires bootstrap")
    await backend.reply("/api/me", profile)
    await backend.reply("/api/family", #"{"family_code":"abc123"}"#)
    await model.next()
    AuthCheck.check(model.screen == .success && model.createdCode == "abc123", "create completion")
    AuthCheck.check(await backend.paths.filter { $0 == "/api/onboarding/create-family" }.count == 1, "bootstrap retry never repeats completed create")
    model.enter(); AuthCheck.check(model.screen == .ready, "success continues to app")
    provider.valid = false; await model.resume()
    AuthCheck.check(model.screen == .intro && vault.value == nil, "Apple revocation clears identity")
    provider.valid = true

    model.route = .join
    await backend.reply("/api/onboarding/join-family/start", #"{"step":"family_code","family_name":"Family","normalized_address":"address","resolved_address":"address"}"#)
    await model.login(apple: false)
    AuthCheck.check(model.step == 4 && model.screen == .onboarding, "join resumes authoritative server step")
    model.familyCode = "invalid"
    await backend.fail("/api/onboarding/join-family/code", .rejected(429, "JOIN_LOCKED"))
    await model.next()
    AuthCheck.check(model.screen == .onboarding && model.error == AuthFailure.rejected(429, "JOIN_LOCKED").message && vault.value?.activated == false, "server lock not bypassed")
    await backend.fail("/api/onboarding/join-family/code", .rejected(409, "INVALID_JOIN_STEP"))
    await backend.reply("/api/onboarding/join-family/start", #"{"step":"user_name"}"#)
    await model.next()
    AuthCheck.check(model.step == 5, "invalid step reconciled by server")
    model.userName = "מיכאל"; model.consent = true
    await backend.reply("/api/onboarding/join-family/complete", #"{"created":true}"#)
    await backend.reply("/api/me", profile)
    await model.next()
    AuthCheck.check(model.screen == .success && model.me?.family_id == 2, "join requires me before activation")
    model.logout()
    model.route = .existing
    await backend.fail("/api/me", .rejected(403, "ACCOUNT_UNAVAILABLE"))
    await model.login(apple: false)
    AuthCheck.check(model.screen == .intro && vault.value == nil && model.me == nil, "deleting account cannot activate")
    let oldCalls = await backend.paths.count
    await backend.reply("/api/me", profile); await backend.pause()
    let loading = Task { await model.login(apple: false) }
    while await backend.paths.count == oldCalls { await Task.yield() }
    model.logout(); await backend.release(); await loading.value
    AuthCheck.check(model.screen == .intro && model.me == nil && vault.value == nil, "logout fences late bootstrap profile")
}
