// Real Apple Keychain + SQLite + production AuthAPI/cleanup. Network and OS daemon are fakes.
import Foundation
import Security
enum DeletionAppleDiagnostics {
    static func status(_ stage: StaticString, _ code: OSStatus) {
        print("FCA_DELETION_APPLE_CHECK stage=\(stage) osstatus=\(code)")
    }
    static func stage(_ value: StaticString) { print("FCA_DELETION_APPLE_CHECK stage=\(value)") }
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
        let root=FileManager.default.temporaryDirectory.appendingPathComponent("fca-apple-deletion-"+UUID().uuidString)
        VehicleEventQueue.testDirectory=root.appendingPathComponent("VehicleEventQueue")
        let config=URLSessionConfiguration.ephemeral; config.protocolClasses=[DeletionHTTP.self]
        let http=URLSession(configuration:config)
        let api=AuthAPI(environment:.development,testingHTTP:http)
        let vault=KeychainVault(environment:.development)
        let cleanup=AccountDeletionCleanup(environment:.development)
        defer { KeychainVault.failClear=false; try? vault.clear(); cleanup.testErase(); http.invalidateAndCancel(); try? FileManager.default.removeItem(at:root) }
        var assertions=0
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
        print("PASS: \(assertions) Apple integration assertions; real Keychain/SQLite/production orchestration, mocked HTTP and daemon")
    }
}
