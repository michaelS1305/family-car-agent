import Foundation

/// Uses synthetic secrets only; output must never contain the sentinel.
@main struct GoogleAuthDiagnosticsCheck {
    @MainActor static func main() throws {
        let secret = "PRIVATE_GOOGLE_SENTINEL"
        let now = Date(timeIntervalSince1970: 1000)
        let base = URL(string: "example.dev://auth/callback")!
        let pending = PendingAuthorization(verifier: secret, nonce: secret, started: now, callbackURL: base)
        #if DEBUG
        func observe(_ suffix: String) -> [Bool] {
            let url = URL(string: base.absoluteString + suffix)!
            GoogleAuthDiagnostics.inspectStructure(url, expected: base, expectedNonce: secret)
            return GoogleAuthDiagnostics.observations(URLComponents(url: url, resolvingAgainstBaseURL: false)!, expectedNonce: secret).map { $0.1 }
        }
        let valid = "?code=\(secret)&nonce=\(secret)"
        precondition(observe(valid) == [false, false, false, true, true, true])
        precondition(observe(valid + "#") == [true, false, false, true, true, true])
        precondition(observe(valid + "#sb=") == [false, true, false, true, true, true])
        for fragment in ["unknown=\(secret)", "sb", "sb=x", "sb=&sb=", "sb=&unknown=x", "s%62=", "error=\(secret)"] {
            precondition(observe(valid + "#" + fragment) == [false, false, false, true, true, true])
        }
        for key in ["access_token", "refresh_token", "id_token", "provider_token", "provider_refresh_token", "access%5Ftoken"] {
            precondition(observe(valid + "#" + key + "=" + secret) == [false, false, true, true, true, true])
        }
        precondition(observe("?code=&nonce=wrong") == [false, false, false, false, true, false])
        precondition(observe("?code=x&code=y&nonce=\(secret)&nonce=\(secret)") == [false, false, false, false, false, false])
        precondition(observe("") == [false, false, false, false, false, false])
        precondition(observe("?code&nonce") == [false, false, false, false, true, false])
        #endif
        func check(_ suffix: String, age: Double = 0, expected: AuthFailure?) {
            do {
                _ = try pending.code(from: URL(string: base.absoluteString + suffix)!, now: now.addingTimeInterval(age))
                precondition(expected == nil)
            } catch { precondition(error as? AuthFailure == expected) }
        }
        check("?nonce=\(secret)&code=\(secret)", expected: nil)
        check("?code=x&nonce=\(secret)", expected: nil)
        check("?nonce=\(secret)&code=x&extra=y", expected: nil)
        check("?nonce=PRIVATE%5FGOOGLE%5FSENTINEL&code=x%2By", expected: nil)
        check("?nonce=PRIVATE%255FGOOGLE%255FSENTINEL&code=x", expected: .callback)
        check("?nonce=\(secret)&error_code=denied&error_description=\(secret)", expected: .callback)
        check("?nonce=\(secret)#error=denied&error_description=\(secret)", expected: .callback)
        check("?nonce=\(secret)&code=x#", expected: nil)
        for fragment in ["sb=", "unknown", "%20", "access_token=\(secret)", "error=denied"] {
            check("?nonce=\(secret)&code=x#" + fragment, expected: .callback)
        }
        check("?nonce=wrong&code=x#", expected: .callback)
        check("?nonce=\(secret)&code=x#", age: 600, expected: .expired)
        check("?nonce=\(secret)&code=#", expected: .callback)
        check("?nonce=\(secret)&code=x&code=y#", expected: .callback)
        check("?nonce=\(secret)&error=denied#", expected: .cancelled)
        for prefix in ["other://auth/callback", "example.dev://other/callback", "example.dev://auth/other",
                       "example.dev://auth:123/callback", "example.dev://user:password@auth/callback"] {
            do {
                _ = try pending.code(from: URL(string: prefix + "?nonce=\(secret)&code=x")!, now: now)
                preconditionFailure("Unexpected structure accepted")
            } catch { precondition(error as? AuthFailure == .callback) }
        }
        check("?nonce=\(secret)&code=x", age: 600, expected: .expired)
        check("?nonce=\(secret)&code=x#fragment", expected: .callback)
        check("?code=x", expected: .callback)
        check("?nonce=wrong&code=x", expected: .callback)
        check("?nonce=\(secret)&nonce=\(secret)&code=x", expected: .callback)
        check("?nonce=\(secret)&error=\(secret)", expected: .cancelled)
        check("?nonce=\(secret)", expected: .callback)
        check("?nonce=\(secret)&code=", expected: .callback)
        check("?nonce=\(secret)&code=x&code=y", expected: .callback)
        let attempt = AuthorizationAttempt()
        do { _ = try attempt.consume(base, now: now); preconditionFailure("Missing attempt accepted") }
        catch { precondition(error as? AuthFailure == .expired) }
        attempt.begin(pending)
        let callback = URL(string: base.absoluteString + "?nonce=\(secret)&code=x")!
        _ = try attempt.consume(callback, now: now)
        do { _ = try attempt.consume(callback, now: now); preconditionFailure("Replay accepted") }
        catch { precondition(error as? AuthFailure == .expired) }
        attempt.begin(pending)
        let emptyFragmentCallback = URL(string: callback.absoluteString + "#")!
        let accepted = try attempt.consume(emptyFragmentCallback, now: now)
        precondition(accepted.0 == "x" && accepted.1 == secret)
        do { _ = try attempt.consume(emptyFragmentCallback, now: now); preconditionFailure("Empty fragment replay accepted") }
        catch { precondition(error as? AuthFailure == .expired) }
        print("PASS: Google callback validation and consumed-attempt regression checks")
    }
}
