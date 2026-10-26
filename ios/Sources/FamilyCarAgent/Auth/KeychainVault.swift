import Foundation
import Security

@MainActor final class KeychainVault: SessionVault {
    private let service: String
    init(environment: AppEnvironment) {
        service = environment.bundleIdentifier + "." + environment.supabaseURL.host! + ".auth.v1"
    }
    private var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
         kSecAttrAccount as String: "session", kSecAttrSynchronizable as String: false]
    }
    func read() throws -> AuthSession? {
        var q = query; q[kSecReturnData as String] = true; q[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(q as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data else { throw AuthFailure.storage }
        guard let session = try? JSONDecoder().decode(AuthSession.self, from: data),
              !session.accessToken.isEmpty, !session.refreshToken.isEmpty else {
            try clear(); throw AuthFailure.signedOut
        }
        return session
    }
    func write(_ session: AuthSession) throws {
        let attributes: [String: Any] = [kSecValueData as String: try JSONEncoder().encode(session),
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            guard SecItemAdd(query.merging(attributes) { _, new in new } as CFDictionary, nil) == errSecSuccess else { throw AuthFailure.storage }
        } else if status != errSecSuccess { throw AuthFailure.storage }
    }
    func clear() throws {
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw AuthFailure.storage }
    }
}
