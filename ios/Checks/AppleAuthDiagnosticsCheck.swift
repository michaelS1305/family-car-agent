import Foundation

@main struct AppleAuthDiagnosticsCheck {
    static func main() {
        #if DEBUG
        let secret = "PRIVATE_SENTINEL_email_token_nonce"
        let nested = NSError(domain: "AKAuthenticationError", code: -7027,
                             userInfo: [NSLocalizedDescriptionKey: secret])
        let outer = NSError(domain: "com.apple.AuthenticationServices.AuthorizationError", code: 1001,
                            userInfo: [NSUnderlyingErrorKey: nested, "email": secret])
        let lines = AppleAuthDiagnostics.errorSummaries(outer)
        precondition(lines.count == 2)
        precondition(lines[0].contains("code=1001"))
        precondition(lines[1].contains("domain=AKAuthenticationError code=-7027"))
        precondition(!lines.joined().contains(secret))
        let unknown = NSError(domain: secret, code: 7, userInfo: [:])
        precondition(AppleAuthDiagnostics.errorSummaries(unknown)[0].contains("redacted_unrecognized_domain"))
        var deep = nested
        for _ in 0..<20 { deep = NSError(domain: "AKErrorDomain", code: 1, userInfo: [NSUnderlyingErrorKey: deep]) }
        precondition(AppleAuthDiagnostics.errorSummaries(deep).count == 4)
        let multiple = NSError(domain: "AKErrorDomain", code: 1,
                               userInfo: ["NSMultipleUnderlyingErrors": [nested, nested, unknown]])
        precondition(AppleAuthDiagnostics.errorSummaries(multiple).count == 3)
        print("PASS: Apple diagnostics domain/code extraction, privacy, nesting limits and deduplication")
        #else
        print("PASS: Release check contains no diagnostic API references")
        #endif
    }
}
