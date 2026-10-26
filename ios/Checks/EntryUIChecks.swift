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
