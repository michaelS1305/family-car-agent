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
    var bodies: [Data?] = []
    var paused = false
    var continuation: CheckedContinuation<Void, Never>?
    func pause() { paused = true }
    func release() { paused = false; continuation?.resume(); continuation = nil }
    func reply(_ path: String, _ json: String) { replies[path, default: []].append(.success(Data(json.utf8))) }
    func fail(_ path: String, _ error: AuthFailure) { replies[path, default: []].append(.failure(error)) }
    func backend<T: Decodable & Sendable>(_ type: T.Type, path: String, token: String, fields: [String: Field]?) async throws -> T {
        paths.append(path)
        bodies.append(try fields.map { try JSONEncoder().encode($0) })
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
    try await runOnboardingChecks()
    let owner = UUID()
    let session = AuthSession(owner: owner, accessToken: "fake", refreshToken: "fake-refresh", expires: Date().addingTimeInterval(3600))
    let profile = #"{"user_id":1,"family_id":2,"name":"Test"}"#
    let vault = TestVault(); let backend = TestBackend(); let provider = TestProvider()
    let manager = SessionManager(vault: vault, transport: TestTransport(session))
    var invalidations = 0
    manager.onInvalidation = { _ in invalidations += 1 }
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
    await backend.reply("/api/me", profile)
    await model.login(apple: false)
    let beforeInvalidation = invalidations
    try manager.clear()
    AuthCheck.check(invalidations == beforeInvalidation + 1, "Entry preserves existing invalidation callback")
    AuthCheck.check(model.screen == .intro && model.me == nil && manager.session == nil,
                    "external session invalidation immediately removes authenticated screen and cached profile")
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

@MainActor private func runOnboardingChecks() async throws {
    let addressJSON = #"{"display_address":"Test address","normalized_address":"Test address","resolution_token":"synthetic-token","latitude":31.07,"longitude":35.03}"#
    let decoder = JSONDecoder()
    let parsed = try decoder.decode(AddressResult.self, from: Data(addressJSON.utf8))
    AuthCheck.check(parsed.location == VerifiedLocation(latitude: 31.07, longitude: 35.03), "authoritative coordinates decoded")
    for fields in ["", #", "latitude":null,"longitude":35"#, #", "latitude":"private","longitude":35"#, #", "latitude":91,"longitude":35"#, #", "latitude":31,"longitude":181"#, #", "latitude":31"#] {
        let json = #"{"display_address":"Test","normalized_address":"Test","resolution_token":"synthetic""# + fields + "}"
        let value = try decoder.decode(AddressResult.self, from: Data(json.utf8))
        AuthCheck.check(value.location == nil && !value.resolution_token.isEmpty, "invalid or absent coordinates only disable map")
    }
    let vault = TestVault(); let backend = TestBackend()
    let transport = TestTransport(AuthSession(owner: UUID(), accessToken: "mock", refreshToken: "mock", expires: Date().addingTimeInterval(3600)))
    let model = EntryModel(sessions: SessionManager(vault: vault, transport: transport), api: backend, providers: TestProvider())
    model.selectRoute(.create); await model.login(apple: false)
    model.familyName = "כהן"; await model.next(from: 1)
    await model.next(from: 1)
    AuthCheck.check(model.step == 2 && model.error == nil, "queued old step action cannot submit address")
    await model.backOnboarding(); AuthCheck.check(model.step == 1, "create address back to name")
    await model.next(); model.address = ""
    await model.next(); AuthCheck.check(model.step == 2 && model.error != nil, "empty address rejected")
    model.address = "Test address"
    await backend.fail("/api/onboarding/create-family/address", .rejected(404, "ADDRESS_NOT_FOUND"))
    await model.next(); AuthCheck.check(model.step == 2 && model.addressLocation == nil, "failed resolution has no map")
    await backend.reply("/api/onboarding/create-family/address", addressJSON)
    await model.next(); AuthCheck.check(model.step == 3 && model.addressLocation == parsed.location, "create confirmation uses server location")
    await model.next(); await model.backOnboarding()
    AuthCheck.check(model.step == 3 && model.addressLocation == parsed.location, "create name back preserves confirmed candidate")
    await model.changeAddress()
    AuthCheck.check(model.step == 2 && model.addressLocation == nil && model.resolvedAddress.isEmpty, "change address clears candidate")
    await backend.reply("/api/onboarding/create-family/address", addressJSON)
    await model.next(); await model.backOnboarding()
    AuthCheck.check(model.step == 2 && model.addressLocation == nil, "confirmation back invalidates candidate")
    await backend.reply("/api/onboarding/create-family/address", addressJSON)
    await model.next(); await model.next(); model.userName = "דנה"
    let beforeConsent = await backend.paths.count
    await model.next(); let afterConsent = await backend.paths.count
    AuthCheck.check(beforeConsent == afterConsent && model.step == 4, "create requires consent")
    model.consent = true
    await backend.fail("/api/onboarding/create-family", .rejected(409, "ADDRESS_RESOLUTION_EXPIRED"))
    await model.next(); AuthCheck.check(model.step == 2 && model.addressLocation == nil, "expired token clears candidate")
    await backend.reply("/api/onboarding/create-family/address", addressJSON)
    await model.next(); await model.next()
    await backend.reply("/api/onboarding/create-family", #"{"created":true}"#)
    await backend.reply("/api/me", #"{"user_id":1,"family_id":2,"name":"Test"}"#)
    await backend.reply("/api/family", #"{"family_code":"ABC123"}"#)
    await model.next()
    AuthCheck.check(model.screen == .success && model.createdCode == "ABC123" && vault.value?.activated == true, "create success after account activation")
    let bodies = await backend.bodies
    let tokenBodies = bodies.compactMap { $0 }.compactMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
    AuthCheck.check(tokenBodies.contains { $0["address_resolution_token"] as? String == "synthetic-token" && $0["latitude"] == nil }, "final create sends token not coordinates")
    model.enter(); AuthCheck.check(model.screen == .ready, "success continues to existing app state")
    model.logout(); model.selectRoute(.join)
    await backend.reply("/api/onboarding/join-family/start", #"{"step":"family_name"}"#)
    await model.login(apple: false); model.familyName = "כהן"
    await backend.reply("/api/onboarding/join-family/family-name", #"{"step":"address","family_name":"כהן"}"#)
    await model.next(); await model.backOnboarding()
    AuthCheck.check(model.step == 2 && model.displayStep == 1, "editing join name never rewinds server step")
    await backend.reply("/api/onboarding/join-family/family-name", #"{"step":"address","family_name":"כהן"}"#)
    await model.next(); model.address = "Test address"
    let joinAddress = #"{"step":"address_confirmed","family_name":"כהן","resolved_address":"Test","latitude":31.07,"longitude":35.03}"#
    await backend.reply("/api/onboarding/join-family/address", joinAddress)
    await model.next(); AuthCheck.check(model.step == 3 && model.addressLocation == parsed.location, "join candidate map")
    await backend.reply("/api/onboarding/join-family/address-confirmation", #"{"step":"address","family_name":"כהן"}"#)
    await model.backOnboarding(); AuthCheck.check(model.step == 2 && model.addressLocation == nil, "join back uses server rollback")
    await backend.reply("/api/onboarding/join-family/address", joinAddress); await model.next()
    await backend.reply("/api/onboarding/join-family/address-confirmation", #"{"step":"family_code","family_name":"כהן","resolved_address":"Test"}"#)
    await model.next()
    await backend.reply("/api/onboarding/join-family/address-confirmation", #"{"step":"address","family_name":"כהן"}"#)
    await model.backOnboarding(); AuthCheck.check(model.step == 2, "join code back returns server-approved address step")
    await backend.reply("/api/onboarding/join-family/address", joinAddress); await model.next()
    await backend.reply("/api/onboarding/join-family/address-confirmation", #"{"step":"family_code"}"#); await model.next()
    model.familyCode = "BAD123"
    await backend.fail("/api/onboarding/join-family/code", .rejected(400, "INVALID_FAMILY_CODE"))
    await model.next(); AuthCheck.check(model.step == 4 && model.error != nil, "invalid code remains server-controlled")
    await backend.fail("/api/onboarding/join-family/code", .rejected(429, "JOIN_LOCKED"))
    await model.next(); AuthCheck.check(model.step == 4 && model.error == AuthFailure.rejected(429, "JOIN_LOCKED").message, "lock preserved")
    await backend.reply("/api/onboarding/join-family/code", #"{"step":"user_name"}"#); await model.next()
    let lockedCount = await backend.paths.count
    await model.backOnboarding(); await model.changeAddress()
    let afterLocked = await backend.paths.count
    AuthCheck.check(!model.canGoBack && model.step == 5 && lockedCount == afterLocked, "verified join cannot edit family or address")
    model.userName = "דנה"; await model.next()
    AuthCheck.check(model.step == 5 && vault.value?.activated == false, "join cannot complete without consent")
    model.consent = true
    await backend.reply("/api/onboarding/join-family/complete", #"{"created":true}"#)
    await backend.reply("/api/me", #"{"user_id":1,"family_id":2,"name":"Test"}"#)
    await backend.pause()
    let beforeCompletion = await backend.paths.count
    let completing = Task { await model.next() }
    while await backend.paths.count == beforeCompletion { await Task.yield() }
    await model.next()
    let duringCompletion = await backend.paths.count
    AuthCheck.check(duringCompletion == beforeCompletion + 1, "join completion is not submitted twice")
    await backend.release(); await completing.value
    AuthCheck.check(model.screen == .success && model.createdCode.isEmpty && vault.value?.activated == true, "join complete activates without exposing family code")
    model.logout(); model.selectRoute(.join)
    await backend.reply("/api/onboarding/join-family/start", #"{"step":"address_confirmed","resolved_address":"Test"}"#)
    await model.login(apple: false)
    AuthCheck.check(model.step == 3 && model.addressLocation == nil, "resumed join has fallback without coordinates")
    await backend.fail("/api/onboarding/join-family/address-confirmation", .rejected(409, "INVALID_JOIN_STEP"))
    await backend.reply("/api/onboarding/join-family/start", #"{"step":"user_name"}"#)
    await model.changeAddress(); AuthCheck.check(model.step == 5 && !model.canGoBack, "rollback mismatch reconciles authoritative locked step")
    model.logout(); model.selectRoute(.create); await model.login(apple: false)
    model.familyName = "כהן"; await model.next(); model.address = "Test"
    await backend.reply("/api/onboarding/create-family/address", addressJSON); await backend.pause()
    let oldCount = await backend.paths.count
    let pending = Task { await model.next() }
    while await backend.paths.count == oldCount { await Task.yield() }
    await model.next(); let during = await backend.paths.count
    AuthCheck.check(during == oldCount + 1, "no duplicate resolution during loading")
    model.logout(); await backend.release(); await pending.value
    AuthCheck.check(model.screen == .intro && model.addressLocation == nil && model.resolvedAddress.isEmpty, "late resolution cannot cross logout")
}
