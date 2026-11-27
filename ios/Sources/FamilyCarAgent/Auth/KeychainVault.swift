import Foundation
import Security

@MainActor final class KeychainVault: SessionVault {
    private let service: String
    private let environment: AppEnvironment
    init(environment: AppEnvironment) {
        self.environment = environment
        #if FCA_DELETION_APPLE_CHECKS
        service = "fca.auth.checks." + String(ProcessInfo.processInfo.processIdentifier) + environment.configurationName
        #else
        service = environment.bundleIdentifier + "." + environment.supabaseURL.host! + ".auth.v1"
        #endif
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
        #if FCA_DELETION_APPLE_CHECKS
        DeletionAppleDiagnostics.status("session_read",status)
        #endif
            if status == errSecItemNotFound { return nil }
            guard status == errSecSuccess, let item = result as? [String: Any],
                  let data = item[kSecValueData as String] as? Data else { throw AuthFailure.storage }
            return (data, item[kSecAttrAccessible as String] as? String == kSecAttrAccessibleWhenUnlockedThisDeviceOnly as String)
        }, upgrade: {
            let attributes = [kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
            let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        #if FCA_DELETION_APPLE_CHECKS
        DeletionAppleDiagnostics.status("session_update",status)
        #endif
            guard status == errSecSuccess else { throw AuthFailure.storage }
        }, clearCorrupt: clear)
    }
    func write(_ session: AuthSession) throws {
        let name=environment.backendURL.absoluteString + "|" + environment.supabaseURL.absoluteString
        try VehicleEventQueue.withAccount(directory:VehicleEventQueue.applicationDirectory(),environment:name,owner:session.owner) {
            try writeAuthorized(session)
        }
    }
    private func writeAuthorized(_ session: AuthSession) throws {
        let attributes: [String: Any] = [kSecValueData as String: try JSONEncoder().encode(session)]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        #if FCA_DELETION_APPLE_CHECKS
        DeletionAppleDiagnostics.status("session_update",status)
        #endif
        if status == errSecItemNotFound {
            var insertion = attributes
            insertion[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            let inserted=SecItemAdd(query.merging(insertion) { _, new in new } as CFDictionary, nil)
            #if FCA_DELETION_APPLE_CHECKS
            DeletionAppleDiagnostics.status("session_add",inserted)
            #endif
            guard inserted == errSecSuccess else { throw AuthFailure.storage }
        } else if status != errSecSuccess { throw AuthFailure.storage }
    }
    #if FCA_DELETION_APPLE_CHECKS
    static var failClear=false
    #endif
    func clear() throws {
        #if FCA_DELETION_APPLE_CHECKS
        if Self.failClear { throw AuthFailure.storage }
        #endif
        let status = SecItemDelete(query as CFDictionary)
        #if FCA_DELETION_APPLE_CHECKS
        DeletionAppleDiagnostics.status("session_delete",status)
        #endif
        guard status == errSecSuccess || status == errSecItemNotFound else { throw AuthFailure.storage }
    }
}
