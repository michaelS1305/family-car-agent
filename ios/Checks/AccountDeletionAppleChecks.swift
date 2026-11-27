// Real Apple Keychain + SQLite + production AuthAPI/cleanup. Network and OS daemon are fakes.
import Foundation
import Security
enum DeletionAppleDiagnostics {
    static func status(_ stage: StaticString, _ code: OSStatus) {
        FileHandle.standardError.write(Data("FCA_DELETION_APPLE_CHECK stage=\(stage) osstatus=\(code)\n".utf8))
    }
    static func stage(_ value: StaticString) { FileHandle.standardError.write(Data("FCA_DELETION_APPLE_CHECK stage=\(value)\n".utf8)) }
}
private func check(_ condition: Bool) { precondition(condition) }

final class DeletionHTTP: URLProtocol, @unchecked Sendable {
    nonisolated(unsafe) static var respond: @Sendable (URLRequest) -> (Int,Data) = { _ in (500,Data()) }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let (code,data)=Self.respond(request)
        client?.urlProtocol(self,didReceive:HTTPURLResponse(url:request.url!,statusCode:code,httpVersion:nil,headerFields:["Cache-Control":"no-store"])!,cacheStoragePolicy:.notAllowed)
        client?.urlProtocol(self,didLoad:data); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
// Composition seams only. The production cleanup, Keychain, SQLite and HTTP client are compiled unchanged.
@MainActor final class VehicleSessionRuntime {
    static var shared: Result<VehicleSessionRuntime,Error> = .success(VehicleSessionRuntime())
    func fenceDeletedAccount(_ owner: UUID) {}
}
@MainActor final class VehicleBackgroundUploadTransport {
    static var fail=false
    static func cancelForDeletion(_ id: String) async throws { if fail { throw AuthFailure.storage } }
}
@MainActor final class NativePushService {
    static let shared=NativePushService()
    func forgetDeletedAccount(_ owner: UUID) throws {}
}
@main struct AccountDeletionAppleChecks {
    @MainActor static func main() async throws {
        let dataProtection=CommandLine.arguments.contains("--data-protection")
        if dataProtection {
            let probe: [String:Any] = [kSecClass as String:kSecClassGenericPassword,
                kSecAttrService as String:"fca.deletion.probe."+UUID().uuidString,
                kSecAttrAccount as String:"probe",kSecValueData as String:Data([0]),
                kSecUseDataProtectionKeychain as String:true,
                kSecAttrAccessible as String:kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
            let status=SecItemAdd(probe as CFDictionary,nil)
            if status == errSecMissingEntitlement {
                print("NOT RUN: Data Protection Keychain runtime unavailable: missing entitlement (-34018); file-based tests are not iOS runtime verification")
                return
            }
            DeletionAppleDiagnostics.status("data_protection_probe",status)
            check(status==errSecSuccess)
            var removal=probe; removal.removeValue(forKey:kSecValueData as String)
            removal.removeValue(forKey:kSecAttrAccessible as String)
            check(SecItemDelete(removal as CFDictionary)==errSecSuccess)
        }
        AccountDeletionCleanup.testDataProtection=dataProtection
        let root=FileManager.default.temporaryDirectory.appendingPathComponent("fca-apple-deletion-"+UUID().uuidString)
        VehicleEventQueue.testDirectory=root.appendingPathComponent("VehicleEventQueue")
        let config=URLSessionConfiguration.ephemeral; config.protocolClasses=[DeletionHTTP.self]
        let http=URLSession(configuration:config)
        let api=AuthAPI(environment:.development,testingHTTP:http)
        let vault=KeychainVault(environment:.development)
        let cleanup=AccountDeletionCleanup(environment:.development)
        defer { KeychainVault.failClear=false; try? vault.clear(); cleanup.testErase(); http.invalidateAndCancel(); try? FileManager.default.removeItem(at:root) }
        var assertions=0
        let reference=Data([1,2,3])
        let query=AccountDeletionCleanup.referenceQuery(reference)
        var expectedKeys=Set([kSecValuePersistentRef,kSecReturnData,kSecReturnAttributes,kSecMatchLimit].map { $0 as String })
        if dataProtection { expectedKeys.insert(kSecUseDataProtectionKeychain as String) }
        check(Set(query.keys)==expectedKeys && query[kSecValuePersistentRef as String] as? Data==reference); assertions += 1
        // Real Keychain enumeration and exact-reference retrieval, isolated from lifecycle fixtures.
        check(try cleanup.testRecords().isEmpty); assertions += 1
        cleanup.failEnumeration=true
        do { _ = try cleanup.testRecords(); fatalError("enumeration failure treated as empty") } catch {}
        cleanup.failEnumeration=false; assertions += 1
        let probeA=UUID(), probeB=UUID()
        let first=try cleanup.prepare(owner:probeA)
        check(try cleanup.testRecords()==[first]); assertions += 1
        let attributes: [String:Any] = [kSecAttrService as String:cleanup.testService,
            kSecAttrAccount as String:probeA.uuidString,kSecValueData as String:try JSONEncoder().encode(first)]
        check(try cleanup.testDecode(attributes)==first); assertions += 1
        for key in [kSecAttrService as String,kSecAttrAccount as String] {
            var invalid=attributes; invalid[key]="unrelated"
            do { _ = try cleanup.testDecode(invalid); fatalError("identity mismatch accepted") } catch {}
            assertions += 1
        }
        let wrongEnvironment=AccountDeletionLifecycle.Record(owner:probeA,environment:"unrelated",operation:first.operation,secret:first.secret)
        var invalid=attributes; invalid[kSecValueData as String]=try JSONEncoder().encode(wrongEnvironment)
        do { _ = try cleanup.testDecode(invalid); fatalError("environment mismatch accepted") } catch {}
        assertions += 1
        let secondProbe=try cleanup.prepare(owner:probeB)
        check(try Set(cleanup.testRecords().map(\.owner))==Set([probeA,probeB])); assertions += 1
        check(try cleanup.prepare(owner:probeA)==first && cleanup.prepare(owner:probeB)==secondProbe); assertions += 1
        cleanup.failRecordRead=true
        do { _ = try cleanup.testRecords(); fatalError("individual read failure ignored") } catch {}
        cleanup.failRecordRead=false; assertions += 1
        let production=AccountDeletionCleanup(environment:.production)
        defer { production.testErase() }
        check(try production.testRecords().isEmpty); assertions += 1
        _ = try production.prepare(owner:probeA)
        check(try production.testRecords().count==1 && cleanup.testRecords().count==2); assertions += 1
        cleanup.testErase()
        check(try cleanup.testRecords().isEmpty && production.testRecords().count==1); assertions += 1
        let owner=UUID(), other=UUID()
        let login=AuthSession(owner:owner,accessToken:"local-test",refreshToken:"local-test",expires:Date().addingTimeInterval(3600),activated:true)
        DeletionAppleDiagnostics.stage("initial_session_write")
        try vault.write(login)
        DeletionAppleDiagnostics.stage("initial_session_restore")
        let sessions=SessionManager(vault:vault,transport:api); try sessions.restore()
        // Capability missing: actual production API refuses old Backend.
        DeletionHTTP.respond={ _ in (404,Data()) }
        do { try await cleanup.support(api:api); fatalError("unsupported backend") } catch {}
        check(try cleanup.testRecords().isEmpty); assertions += 1
        let capability=Data(#"{"protocol":"deletion-status-v1","retention_days":180}"#.utf8)
        DeletionHTTP.respond={ request in
            check(request.url!.path != "/api/account/deletion") // No destructive legacy fallback.
            return request.url!.path.hasSuffix("capabilities") ? (200,capability) : (404,Data())
        }
        try await cleanup.support(api:api)
        DeletionAppleDiagnostics.stage("receipt_prepare")
        let record=try cleanup.prepare(owner:owner)
        check(try AccountDeletionCleanup(environment:.development).testRecords().first==record); assertions += 1
        // Real SessionManager pending write succeeds, submitted Keychain write fails.
        cleanup.failSubmittedWrite=true
        do { try await cleanup.begin(record,sessions:sessions,api:api); fatalError("save failure") } catch {}
        let unarmed=try cleanup.testRecords().first
        check(sessions.session?.deletionPending==true && unarmed?.submitted==false); assertions += 1
        cleanup.failSubmittedWrite=false
        // Mixed fleet: capability succeeds, dedicated request hits old Backend. No legacy request fallback.
        do { try await cleanup.begin(record,sessions:sessions,api:api); fatalError("mixed version") } catch {}
        check(try cleanup.testRecords().first?.submitted==true); assertions += 1
        let context=try VehicleQueueContext(environment:.development,identity:.init(owner:owner,user:1,family:1,generation:0,version:0),device:UUID())
        DeletionAppleDiagnostics.stage("queue_prepare")
        let queue=try VehicleEventQueue(directory:VehicleEventQueue.testDirectory!)
        try await queue.initializeFreshDevice(context)
        let completion=try JSONSerialization.data(withJSONObject:["operation_id":record.operation.uuidString,"status":"completed","completed_at":"2026-01-01T00:00:00Z","expires_at":"2026-06-30T00:00:00Z"])
        DeletionHTTP.respond={ request in
            check(request.url!.path.hasSuffix("status"))
            check(request.value(forHTTPHeaderField:"Authorization")?.hasPrefix("DeletionStatus ")==true)
            return (200,completion)
        }
        let expired=AuthSession(owner:owner,accessToken:"expired-test",refreshToken:"expired-test",expires:.distantPast,deletionPending:true,activated:true)
        try vault.write(expired)
        let expiredSessions=SessionManager(vault:vault,transport:api); try expiredSessions.restore()
        DeletionAppleDiagnostics.stage("confirmed_cancellation_failure")
        VehicleBackgroundUploadTransport.fail=true
        do { _ = try await cleanup.resume(api:api,sessions:expiredSessions); fatalError("cancel failure") } catch {}
        check(try cleanup.testRecords().first?.completed==true); assertions += 1
        VehicleBackgroundUploadTransport.fail=false
        DeletionAppleDiagnostics.stage("confirmed_keychain_failure")
        KeychainVault.failClear=true
        do { _ = try await cleanup.resume(api:api,sessions:expiredSessions); fatalError("Keychain failure") } catch {}
        check(try cleanup.testRecords().first?.completed==true); assertions += 1
        let db=try VehicleQueueDatabase(directory:VehicleEventQueue.testDirectory!)
        check(try db.rows("SELECT * FROM devices").isEmpty); assertions += 1
        // Restart, JWT absent, B active: cleanup must not clear B's actual Keychain session.
        KeychainVault.failClear=false
        let second=AuthSession(owner:other,accessToken:"other-test",refreshToken:"other-test",expires:Date().addingTimeInterval(3600),activated:true)
        try vault.write(second)
        DeletionAppleDiagnostics.stage("restart_other_account")
        let restarted=SessionManager(vault:vault,transport:api); try restarted.restore()
        DeletionHTTP.respond={ _ in fatalError("durable completion must not need network") }
        check(try await AccountDeletionCleanup(environment:.development).resume(api:api,sessions:restarted)); assertions += 1
        check(try vault.read()?.owner==other); assertions += 1
        do { try vault.write(login); fatalError("deleted owner recreated") } catch {}
        check(try cleanup.testRecords().isEmpty); assertions += 1
        // Independent pre-upgrade record: same persisted format, already submitted, no JWT.
        let legacyOwner=UUID(), legacyOperation=UUID()
        let legacySecret=String(repeating:"a",count:43)
        let environment=AppEnvironment.development.backendURL.absoluteString+"|"+AppEnvironment.development.supabaseURL.absoluteString
        let fixture=try JSONSerialization.data(withJSONObject:["owner":legacyOwner.uuidString,"environment":environment,
            "operation":legacyOperation.uuidString,"secret":legacySecret,"submitted":true,"completed":false,"cleaned":false])
        try cleanup.testSeed(legacyOwner,data:fixture)
        let restoredCleanup=AccountDeletionCleanup(environment:.development)
        let persisted=try restoredCleanup.testRecords().first!
        check(persisted.operation==legacyOperation && persisted.secret==legacySecret && persisted.submitted); assertions += 1
        // Expired/absent authentication never becomes proof of deletion.
        try vault.clear()
        let noJWT=SessionManager(vault:vault,transport:api); try noJWT.restore()
        for code in [401,500,200] {
            DeletionHTTP.respond={ request in
                check(request.url!.path.hasSuffix("status"))
                check(request.value(forHTTPHeaderField:"Authorization")=="DeletionStatus "+legacyOperation.uuidString.lowercased()+"."+legacySecret)
                return (code,Data("{}".utf8))
            }
            do { _ = try await restoredCleanup.resume(api:api,sessions:noJWT) } catch {}
            check(try restoredCleanup.testRecords()==[persisted]); assertions += 1
        }
        let legacyReply=try JSONSerialization.data(withJSONObject:["operation_id":legacyOperation.uuidString,"status":"completed",
            "completed_at":"2026-11-27T00:00:00Z","expires_at":"2027-05-26T00:00:00Z"])
        DeletionHTTP.respond={ request in
            check(request.url!.path.hasSuffix("status"))
            check(request.value(forHTTPHeaderField:"Authorization")=="DeletionStatus "+legacyOperation.uuidString.lowercased()+"."+legacySecret)
            return (200,legacyReply)
        }
        check(try await restoredCleanup.resume(api:api,sessions:noJWT)); assertions += 1
        check(try restoredCleanup.testRecords().isEmpty); assertions += 1
        print("PASS: \(assertions) Apple integration assertions; Keychain mode=\(dataProtection ? "data-protection" : "macOS-file-based"); real Keychain/SQLite/production orchestration, mocked HTTP and daemon")
    }
}
