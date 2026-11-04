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
        try SessionVaultRead.restore(item: {
            var q = query
            q[kSecReturnData as String] = true; q[kSecReturnAttributes as String] = true
            q[kSecMatchLimit as String] = kSecMatchLimitOne
            var result: CFTypeRef?
            let status = SecItemCopyMatching(q as CFDictionary, &result)
            if status == errSecItemNotFound { return nil }
            guard status == errSecSuccess, let item = result as? [String: Any],
                  let data = item[kSecValueData as String] as? Data else { throw AuthFailure.storage }
            return (data, item[kSecAttrAccessible as String] as? String == kSecAttrAccessibleWhenUnlockedThisDeviceOnly as String)
        }, upgrade: {
            let attributes = [kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
            let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
            #if DEBUG && os(iOS)
            UserDefaults.standard.set(status == errSecSuccess ? "legacy upgraded" : "upgrade deferred", forKey: "phase4.migration")
            #endif
            guard status == errSecSuccess else { throw AuthFailure.storage }
        }, clearCorrupt: clear)
    }
    #if DEBUG && os(iOS)
    /// Read the actual item, independently of SessionManager's in-memory cache.
    /// This observation does not migrate, erase, or refresh the item.
    func diagnosticRead() -> String {
        var q = query
        q[kSecReturnAttributes as String] = true; q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(q as CFDictionary, &result)
        if status == errSecInteractionNotAllowed { return "protected / unavailable" }
        if status == errSecItemNotFound { return "missing" }
        guard status == errSecSuccess, let item = result as? [String: Any],
              let bytes = item[kSecValueData as String] as? Data,
              let value = try? JSONDecoder().decode(AuthSession.self, from: bytes), value.activated,
              !value.accessToken.isEmpty, !value.refreshToken.isEmpty else { return "unreadable" }
        return item[kSecAttrAccessible as String] as? String == kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly as String
            ? "readable / after first unlock" : "readable / other class"
    }
    #endif
    func write(_ session: AuthSession) throws {
        let attributes: [String: Any] = [kSecValueData as String: try JSONEncoder().encode(session)]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            var insertion = attributes
            insertion[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            guard SecItemAdd(query.merging(insertion) { _, new in new } as CFDictionary, nil) == errSecSuccess else { throw AuthFailure.storage }
        } else if status != errSecSuccess { throw AuthFailure.storage }
    }
    func clear() throws {
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw AuthFailure.storage }
    }
}
