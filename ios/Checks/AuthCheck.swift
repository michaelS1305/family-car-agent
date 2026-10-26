import Foundation

@MainActor final class TestVault: SessionVault {
    var value: AuthSession?
    var failWrite = false
    var failClear = false
    var writes = 0
    func read() throws -> AuthSession? { value }
    func write(_ value: AuthSession) throws {
        if failWrite { throw AuthFailure.storage }; self.value = value; writes += 1
    }
    func clear() throws { if failClear { throw AuthFailure.storage }; value = nil }
}

actor TestTransport: AuthTransport {
    var result: AuthSession
    var failure: AuthFailure?
    var calls = 0
    var paused = false
    var continuation: CheckedContinuation<Void, Never>?
    init(_ result: AuthSession) { self.result = result }
    func pause() { paused = true }
    func fail(_ value: AuthFailure) { failure = value }
    func release() { paused = false; continuation?.resume(); continuation = nil }
    func exchange(grant: String, fields: [String: String]) async throws -> AuthSession {
        calls += 1
        if paused { await withCheckedContinuation { continuation = $0 } }
        if let failure { throw failure }
        return result
    }
}

@main struct AuthCheck {
    @MainActor static var checks = 0
    @MainActor static func check(_ value: Bool, _ name: String) {
        precondition(value, "FAIL: " + name); checks += 1
    }
    @MainActor static func rejects(_ name: String, _ expected: AuthFailure, _ action: () async throws -> Void) async {
        do { try await action(); preconditionFailure("Expected rejection: " + name) }
        catch { check(error as? AuthFailure == expected, name) }
    }
    @MainActor static func main() async throws {
        let env = AppEnvironment.development
        let now = Date(timeIntervalSince1970: 1000)
        let pending = PendingAuthorization(verifier: "test-verifier", nonce: "test-nonce", started: now, callbackURL: env.proposedOAuthCallbackURL)
        let valid = URL(string: env.proposedOAuthCallbackURL.absoluteString + "?nonce=test-nonce&code=code")!
        check(try pending.code(from: valid, now: now) == "code", "callback accepted")
        for url in ["other://auth/callback?nonce=test-nonce&code=code",
                    "com.familycaragent.app.dev://other/callback?nonce=test-nonce&code=code",
                    "com.familycaragent.app.dev://auth/wrong?nonce=test-nonce&code=code",
                    valid.absoluteString + "&nonce=test-nonce", valid.absoluteString + "&code=second",
                    valid.absoluteString + "#token=bad",
                    "com.familycaragent.app.dev://auth:443/callback?nonce=test-nonce&code=code",
                    "com.familycaragent.app.dev://user@auth/callback?nonce=test-nonce&code=code",
                    "com.familycaragent.app.dev://auth/callback?nonce=wrong&code=code"] {
            await rejects("strict callback", .callback) { _ = try pending.code(from: URL(string: url)!, now: now) }
        }
        await rejects("expired", .expired) { _ = try pending.code(from: valid, now: now.addingTimeInterval(600)) }
        await rejects("clock backwards", .expired) { _ = try pending.code(from: valid, now: now.addingTimeInterval(-1)) }
        let attempts = AuthorizationAttempt(); attempts.begin(pending)
        _ = try attempts.consume(valid, now: now)
        await rejects("single use", .expired) { _ = try attempts.consume(valid, now: now) }
        attempts.begin(pending); attempts.cancel()
        await rejects("cancelled attempt", .expired) { _ = try attempts.consume(valid, now: now) }
        let authorization = try pending.authorizeURL(base: env.supabaseURL, challenge: "test-challenge")
        let query = URLComponents(url: authorization, resolvingAgainstBaseURL: false)!.queryItems!
        check(query.first(where: { $0.name == "code_challenge_method" })?.value == "s256", "PKCE method")
        check(query.first(where: { $0.name == "code_challenge" })?.value == "test-challenge", "PKCE challenge forwarded")
        check(!authorization.absoluteString.contains("test-verifier"), "verifier never in authorize URL")
        let redirect = query.filter { $0.name == "redirect_to" }
        check(redirect.count == 1, "one explicit native redirect")
        let native = URLComponents(string: redirect[0].value!)!
        check(native.scheme == env.proposedOAuthCallbackURL.scheme && native.host == "auth" && native.path == "/callback",
              "Google redirects to native Dev, never Web/PWA")
        check(native.queryItems == [URLQueryItem(name: "nonce", value: pending.nonce)], "per-attempt callback binding retained")
        check(query.first(where: { $0.name == "provider" })?.value == "google", "Google provider unchanged")
        check(authorization.host == env.supabaseURL.host && authorization.path == "/auth/v1/authorize", "Dev Supabase authorization endpoint")

        let owner = UUID(); let other = UUID()
        let original = AuthSession(owner: owner, accessToken: "test-access", refreshToken: "test-refresh", expires: now, activated: true)
        let refreshed = AuthSession(owner: owner, accessToken: "new-access", refreshToken: "new-refresh", expires: Date().addingTimeInterval(3600))
        let vault = TestVault(); vault.value = original
        let transport = TestTransport(refreshed)
        let manager = SessionManager(vault: vault, transport: transport)
        try manager.restore()
        check(manager.session == original, "restoration")
        await transport.pause()
        let a = Task { try await manager.access(owner: owner) }
        while await transport.calls == 0 { await Task.yield() }
        let b = Task { try await manager.access(owner: owner) }
        for _ in 0..<20 { await Task.yield() }
        await transport.release()
        check(try await a.value == "new-access", "refresh result")
        check(try await b.value == "new-access", "coalesced result")
        check(await transport.calls == 1 && vault.writes == 1, "one refresh/write")
        check(vault.value?.activated == true, "activation retained")
        _ = try await manager.access(owner: owner)
        check(await transport.calls == 1, "valid token reused")
        await rejects("wrong account access", .signedOut) { _ = try await manager.access(owner: other) }
        try manager.clear()
        check(manager.session == nil && vault.value == nil, "logout erases")
        try await manager.login(grant: "id_token", fields: [:], appleUser: "apple-subject")
        check(manager.session?.owner == owner, "same Supabase ID is same FCA account across providers")
        check(manager.session?.activated == false, "provider success is not FCA activation")
        try manager.activate(owner: owner)
        check(vault.value?.activated == true, "explicit bootstrap activation")
        try manager.clear()

        let relay = AuthSession(owner: other, accessToken: "relay-access", refreshToken: "relay-refresh", expires: Date().addingTimeInterval(3600))
        let relayManager = SessionManager(vault: vault, transport: TestTransport(relay))
        try await relayManager.login(grant: "id_token", fields: [:], appleUser: "relay-apple-subject")
        check(relayManager.session?.owner == other, "different Apple/relay ID stays separate")
        await rejects("old owner denied", .signedOut) { _ = try await relayManager.access(owner: owner) }
        let restoredUnactivated = SessionManager(vault: vault, transport: transport)
        try restoredUnactivated.restore()
        check(restoredUnactivated.session == nil && vault.value == nil, "unfinished onboarding cannot activate on restart")

        let staleVault = TestVault(); staleVault.value = original
        let staleTransport = TestTransport(refreshed); await staleTransport.pause()
        let stale = SessionManager(vault: staleVault, transport: staleTransport); try stale.restore()
        let flight = Task { try await stale.access(owner: owner) }
        while await staleTransport.calls == 0 { await Task.yield() }
        try stale.clear(); await staleTransport.release()
        await rejects("logout fences in-flight refresh", .stale) { _ = try await flight.value }
        check(staleVault.value == nil && stale.session == nil, "late result cannot resurrect")

        let wrongVault = TestVault(); wrongVault.value = original
        let wrong = SessionManager(vault: wrongVault, transport: TestTransport(relay)); try wrong.restore()
        await rejects("refresh owner mismatch", .signedOut) { _ = try await wrong.access(owner: owner) }
        check(wrongVault.value == nil, "owner mismatch clears storage")
        let deniedVault = TestVault(); deniedVault.failWrite = true
        let denied = SessionManager(vault: deniedVault, transport: transport)
        await rejects("Keychain write failure", .storage) { try await denied.login(grant: "pkce", fields: [:]) }
        check(denied.session == nil, "no memory session after failed persistence")
        let revokedVault = TestVault(); revokedVault.value = original
        let revokedTransport = TestTransport(refreshed); await revokedTransport.fail(.rejected(400, "refresh_token_not_found"))
        let revoked = SessionManager(vault: revokedVault, transport: revokedTransport); try revoked.restore()
        await rejects("revoked refresh", .signedOut) { _ = try await revoked.access(owner: owner) }
        check(revokedVault.value == nil, "revoked session cleared")

        check(AuthAPI.validPublicKey("sb_publishable_test"), "public key accepted")
        check(!AuthAPI.validPublicKey("sb_secret_test") && !AuthAPI.validPublicKey(""), "secret/missing key rejected")
        let missing = Data(#"{"detail":"Authenticated user is not assigned to a family"}"#.utf8)
        check(AuthAPI.failure(status: 403, data: missing, path: "/api/me") == .rejected(403, "MISSING_ACCOUNT"), "exact missing account")
        check(AuthAPI.failure(status: 500, data: missing, path: "/api/me") == .rejected(500, ""), "not status-only classification")
        check(AuthAPI.failure(status: 400, data: Data(#"{"message":"secret raw text"}"#.utf8), path: "/api/me").message.contains("secret") == false, "raw errors not exposed")
        check(OnboardingValidation.validName("  משפחת כהן  ") && OnboardingValidation.validName("O’Neil"), "name normalization")
        check(!OnboardingValidation.validName("משפחה1") && !OnboardingValidation.validName("-name"), "name validation")
        let parsed = try JSONDecoder().decode(Me.self, from: Data(#"{"user_id":1,"family_id":2,"name":"Test","carplay_setup_status":"pending"}"#.utf8))
        check(parsed.family_id == 2, "current backend me contract")
        check((try? JSONDecoder().decode(Me.self, from: Data(#"{"user_id":1,"family_id":null,"name":"Test"}"#.utf8))) == nil, "null family not ready")
        func response(_ id: UUID, _ email: String) throws -> AuthSession {
            let json = "{\"access_token\":\"fake\",\"refresh_token\":\"fake\",\"expires_in\":3600,\"provider_token\":\"discard-me\",\"user\":{\"id\":\"\(id)\",\"email\":\"\(email)\"}}"
            return try AuthAPI.session(from: JSONDecoder().decode(SupabaseTokenResponse.self, from: Data(json.utf8)), now: now)
        }
        let google = try response(owner, "same@example.invalid")
        let appleSame = try response(owner, "same@example.invalid")
        let appleRelay = try response(other, "private@privaterelay.appleid.com")
        let sameEmailDifferentID = try response(other, "same@example.invalid")
        check(google.owner == appleSame.owner, "parsed shared Supabase ID converges")
        check(google.owner != appleRelay.owner, "parsed relay separate ID remains separate")
        check(google.owner != sameEmailDifferentID.owner, "matching email cannot override Supabase ID")
        let serialized = String(data: try JSONEncoder().encode(appleRelay), encoding: .utf8)!
        check(!serialized.contains("provider_token") && !serialized.contains("privaterelay") && !serialized.contains("discard-me"), "only session credentials persisted")
        let networkVault = TestVault(); networkVault.value = original
        let networkTransport = TestTransport(refreshed); await networkTransport.fail(.network)
        let network = SessionManager(vault: networkVault, transport: networkTransport); try network.restore()
        await rejects("network failure is not revocation", .network) { _ = try await network.access(owner: owner) }
        check(networkVault.value == original, "retryable refresh preserves credentials")
        let loginVault = TestVault(); let loginTransport = TestTransport(refreshed); await loginTransport.pause()
        let login = SessionManager(vault: loginVault, transport: loginTransport)
        let signingIn = Task { try await login.login(grant: "pkce", fields: [:]) }
        while await loginTransport.calls == 0 { await Task.yield() }
        try login.clear(); await loginTransport.release()
        await rejects("cancel fences in-flight login", .stale) { try await signingIn.value }
        check(loginVault.value == nil, "late exchange cannot persist")
        try await runEntryChecks()
        try await runEntryUIChecks()
        print("Auth checks passed: \(checks). Mock identities only; no provider/device claims.")
    }
}
