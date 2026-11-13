#if os(iOS)
import Foundation
import Security

@MainActor final class NativePushKeychainStore: NativePushStore {
    private let service: String
    init(environment: AppEnvironment) {
        service = environment.bundleIdentifier + "." + environment.backendURL.host! + ".push.v1"
    }
    private var query: [String:Any] {
        [kSecClass as String:kSecClassGenericPassword,kSecAttrService as String:service,
         kSecAttrAccount as String:"registrations",kSecAttrSynchronizable as String:false]
    }
    func read() throws -> [NativePushRegistration.Record] {
        var q = query; q[kSecReturnData as String] = true; q[kSecMatchLimit as String] = kSecMatchLimitOne
        var value: CFTypeRef?
        let status = SecItemCopyMatching(q as CFDictionary,&value)
        if status == errSecItemNotFound { return [] }
        guard status == errSecSuccess, let data = value as? Data else { throw AuthFailure.storage }
        return try JSONDecoder().decode([NativePushRegistration.Record].self,from:data)
    }
    func write(_ records: [NativePushRegistration.Record]) throws {
        let data = try JSONEncoder().encode(records)
        let attributes: [String:Any] = [kSecValueData as String:data]
        var status = SecItemUpdate(query as CFDictionary,attributes as CFDictionary)
        if status == errSecItemNotFound {
            var q = query; q[kSecValueData as String] = data
            q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            status = SecItemAdd(q as CFDictionary,nil)
        }
        guard status == errSecSuccess else { throw AuthFailure.storage }
    }
    func newSecret() throws -> String {
        var bytes = [UInt8](repeating:0,count:32)
        guard SecRandomCopyBytes(kSecRandomDefault,bytes.count,&bytes) == errSecSuccess else { throw AuthFailure.storage }
        return bytes.map { String(format:"%02x",$0) }.joined()
    }
}
#endif
