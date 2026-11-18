// Run on macOS: Apple CryptoKit/Security are not executable on the Linux WSL host.
import Foundation

@main struct CryptoCheck {
    static func main() throws {
        // RFC 7636 Appendix B
        precondition(AuthCrypto.challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")
        precondition(AuthCrypto.appleNonce("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        let values = try (0..<128).map { _ in try AuthCrypto.random() }
        precondition(Set(values).count == values.count)
        precondition(values.allSatisfy { $0.count == 43 && $0.range(of: "^[A-Za-z0-9_-]+$", options: .regularExpression) != nil })
        print("Apple-platform crypto checks passed")
    }
}
