import Foundation

@MainActor private final class PausedEntryProvider: NativeAuthProvider {
    var entered = false
    var continuation: CheckedContinuation<ProviderResult, Error>?
    func authorize(apple: Bool) async throws -> ProviderResult {
        entered = true
        return try await withCheckedThrowingContinuation { continuation = $0 }
    }
    func cancel() { /* Deliberately leave a late callback to test generation fencing. */ }
    func credentialValid(_ user: String) async throws -> Bool { true }
    func complete() {
        continuation?.resume(returning: ProviderResult(grant: "pkce", fields: [:]))
        continuation = nil
    }
}

@MainActor func runEntryUIChecks() async throws {
    await runFamilyNameChecks()
    for route in LoginRoute.allCases {
        for apple in [false, true] {
            let vault = TestVault()
            let transport = TestTransport(AuthSession(owner: UUID(), accessToken: "mock", refreshToken: "mock",
                                                     expires: Date().addingTimeInterval(3600)))
            let backend = TestBackend()
            let model = EntryModel(sessions: SessionManager(vault: vault, transport: transport),
                                   api: backend, providers: TestProvider())
            model.selectRoute(route)
            AuthCheck.check(model.screen == .login && model.route == route, "intro preserves selected route")
            model.backFromEntry()
            AuthCheck.check(model.screen == .intro && model.route == route, "login back returns to intro")
            model.selectRoute(route)
            if route == .existing { await backend.reply("/api/me", #"{"user_id":1,"family_id":2,"name":"Mock"}"#) }
            await model.login(apple: apple, previewOnboarding: true)
            let paths = await backend.paths
            if route == .existing {
                AuthCheck.check(model.screen == .ready && paths == ["/api/me"] && vault.value?.activated == true,
                                "existing account bootstraps for either provider")
            } else {
                AuthCheck.check(model.screen == .onboarding && model.route == route && paths.isEmpty,
                                "placeholder performs no backend onboarding operations")
                AuthCheck.check(vault.value?.activated == false && model.me == nil, "placeholder never activates or fabricates membership")
                let saved = vault.value
                model.backFromEntry()
                AuthCheck.check(model.screen == .login && model.route == route && vault.value == saved,
                                "placeholder back preserves route and unactivated session")
            }
            model.logout()
            AuthCheck.check(vault.value == nil && model.screen == .intro, "placeholder/logout identity cleanup")
        }
    }
    let provider = PausedEntryProvider(); let vault = TestVault(); let backend = TestBackend()
    let transport = TestTransport(AuthSession(owner: UUID(), accessToken: "mock", refreshToken: "mock",
                                             expires: Date().addingTimeInterval(3600)))
    let model = EntryModel(sessions: SessionManager(vault: vault, transport: transport), api: backend, providers: provider)
    model.selectRoute(.join)
    let task = Task { await model.login(apple: false, previewOnboarding: true) }
    while !provider.entered { await Task.yield() }
    model.selectRoute(.create); model.backFromEntry()
    AuthCheck.check(model.route == .join && model.screen == .login && model.busy, "navigation cannot change in-flight route")
    model.logout(); provider.complete(); await task.value
    AuthCheck.check(model.screen == .intro && vault.value == nil, "late browser completion after cancel is rejected")
    let exchanges = await transport.calls
    let requests = await backend.paths
    AuthCheck.check(exchanges == 0 && requests.isEmpty, "cancelled callback never exchanges or onboards")
}

@MainActor private func runFamilyNameChecks() async {
    for route in [LoginRoute.create, .join] {
        for apple in [false, true] {
            let vault = TestVault(); let backend = TestBackend()
            let transport = TestTransport(AuthSession(owner: UUID(), accessToken: "mock", refreshToken: "mock",
                                                     expires: Date().addingTimeInterval(3600)))
            let model = EntryModel(sessions: SessionManager(vault: vault, transport: transport),
                                   api: backend, providers: TestProvider())
            model.selectRoute(route)
            if route == .join { await backend.reply("/api/onboarding/join-family/start", #"{"step":"family_name"}"#) }
            await model.login(apple: apple)
            let initial = await backend.paths
            AuthCheck.check(model.screen == .onboarding && model.step == 1, "real login enters family name")
            AuthCheck.check(model.totalSteps == (route == .create ? 4 : 5), "route-specific step indicator")
            AuthCheck.check(initial == (route == .join ? ["/api/onboarding/join-family/start"] : []), "join starts real server workflow")
            for invalid in ["", "   ", "כהן123"] {
                model.familyName = invalid; await model.next()
                let paths = await backend.paths
                AuthCheck.check(model.step == 1 && model.error == AuthFailure.rejected(400, "INVALID_FAMILY_NAME").message && paths == initial,
                                "invalid name never advances or calls backend")
            }
            model.familyName = "בן דוד"
            if route == .join {
                await backend.fail("/api/onboarding/join-family/family-name", .rejected(404, "JOIN_FAMILY_NAME_NOT_FOUND"))
                await model.next()
                AuthCheck.check(model.step == 1 && model.error == AuthFailure.rejected(404, "JOIN_FAMILY_NAME_NOT_FOUND").message,
                                "server rejection retains name step")
                await backend.reply("/api/onboarding/join-family/family-name", #"{"step":"address","family_name":"בן דוד"}"#)
                await backend.pause()
                let before = await backend.paths.count
                let pending = Task { await model.next() }
                while await backend.paths.count == before { await Task.yield() }
                await model.next(); model.backFromEntry()
                let during = await backend.paths.count
                AuthCheck.check(model.busy && model.screen == .onboarding && model.step == 1 && during == before + 1,
                                "pending name submission blocks duplicate and back")
                await backend.release(); await pending.value
            } else {
                await model.next()
                let paths = await backend.paths
                AuthCheck.check(paths.isEmpty, "create name step does not resolve or create anything")
            }
            AuthCheck.check(model.step == 2 && !model.busy && model.error == nil && vault.value?.activated == false,
                            "valid name advances without activating membership")
            model.logout(); model.selectRoute(route)
            if route == .join { await backend.reply("/api/onboarding/join-family/start", #"{"step":"family_name"}"#) }
            await model.login(apple: apple)
            model.backFromEntry()
            AuthCheck.check(model.screen == .login && model.route == route, "first-step back returns to login")
            model.logout()
        }
    }
}
