import Foundation

/// Shared deterministic state machine. No networking, UI, clock or credentials in diagnostics.
@MainActor enum AccountDeletionLifecycle {
    struct Record: Codable, Equatable {
        let owner: UUID
        let environment: String
        let operation: UUID
        var secret: String?
        var submitted = false
        var completed = false
        var cleaned = false
    }
    struct Reply: Decodable, Sendable {
        let operation_id: UUID
        let status: String
        let completed_at: String?
        let expires_at: String?
    }
    enum Failure: Error { case invalidConfirmation, statusUnavailable, cancellationFailed }
    static func confirmation(record: Record, reply: Reply?, save: (Record) throws -> Void) throws -> Record? {
        var value=record
        if value.cleaned { return value }
        if !value.completed {
            guard let reply, reply.operation_id == value.operation else { throw Failure.invalidConfirmation }
            if reply.status == "pending" { return nil }
            func date(_ text: String?) -> Date? {
                guard let text else { return nil }
                let formatter=ISO8601DateFormatter()
                formatter.formatOptions=[.withInternetDateTime,.withFractionalSeconds]
                if let value=formatter.date(from:text) { return value }
                formatter.formatOptions=[.withInternetDateTime]
                return formatter.date(from:text)
            }
            guard reply.status == "completed", let end=date(reply.completed_at), let expiry=date(reply.expires_at),
                  abs(expiry.timeIntervalSince(end)-180*86400)<0.001 else { throw Failure.invalidConfirmation }
            value.completed=true; value.secret=nil
            try save(value) // No cleanup unless durable confirmation succeeds.
        }
        return value
    }
    /// Used by the actual app and executable orchestration checks.
    static func begin(record: Record, markPending: () throws -> Void, save: (Record) throws -> Void,
                      send: (Record) async throws -> Void) async throws {
        try markPending()
        var armed=record; armed.submitted=true
        try save(armed) // Failure leaves an unarmed record; only explicit user retry can proceed.
        try await send(armed)
    }
    static func resume(record: Record, status: () async throws -> Reply,
                       replayInitiation: () async throws -> Void, save: (Record) throws -> Void,
                       cancel: (Record) async throws -> Void, cleanup: (Record) throws -> Void) async throws -> Bool {
        if record.cleaned { return true }
        if !record.submitted && !record.completed { return false }
        var confirmed=record
        if !record.completed {
            let reply: Reply
            do { reply=try await status() }
            catch Failure.statusUnavailable { try await replayInitiation(); return false }
            guard let value=try confirmation(record:record,reply:reply,save:save) else { return false }
            confirmed=value
        }
        try await cancel(confirmed)
        return try apply(record:confirmed,reply:nil,save:save,cleanup:cleanup)
    }
    static func apply(record: Record, reply: Reply?, save: (Record) throws -> Void,
                      cleanup: (Record) throws -> Void) throws -> Bool {
        guard var value=try confirmation(record:record,reply:reply,save:save) else { return false }
        if value.cleaned { return true }
        try cleanup(value)
        value.cleaned=true
        try save(value) // Storage failure retains a retryable completion record.
        return true
    }
}

/// The production URLSession delegate drives this exact completion gate.
@MainActor final class DeletionUploadCancellation {
    private var result: Bool?
    private var waiters: [UUID:CheckedContinuation<Void,Error>] = [:]
    func wait(invalidate: () -> Void,
              timeout: @escaping @Sendable () async -> Void = { try? await Task.sleep(for:.seconds(15)) }) async throws {
        if let result { if !result { throw AccountDeletionLifecycle.Failure.cancellationFailed }; return }
        let id=UUID()
        try await withCheckedThrowingContinuation { (continuation:CheckedContinuation<Void,Error>) in
            waiters[id]=continuation
            invalidate()
            Task { @MainActor [weak self] in
                await timeout()
                self?.waiters.removeValue(forKey:id)?.resume(throwing:AccountDeletionLifecycle.Failure.cancellationFailed)
            }
        }
    }
    func finish(failed: Bool) {
        guard result == nil else { return } // Late/duplicate callbacks cannot change the outcome.
        result = !failed
        let pending=waiters; waiters.removeAll()
        for waiter in pending.values {
            if failed { waiter.resume(throwing:AccountDeletionLifecycle.Failure.cancellationFailed) }
            else { waiter.resume() }
        }
    }
}

#if os(iOS) || FCA_DELETION_APPLE_CHECKS
import Foundation
import Security

/// Separate device-only item per owner. JWT expiry cannot erase this operation.
@MainActor final class AccountDeletionCleanup {
    typealias Record = AccountDeletionLifecycle.Record
    typealias Reply = AccountDeletionLifecycle.Reply
    private let environment: AppEnvironment
    private let service: String
    init(environment: AppEnvironment) {
        self.environment = environment
        #if FCA_DELETION_APPLE_CHECKS
        service = "fca.deletion.checks." + String(ProcessInfo.processInfo.processIdentifier) + environment.configurationName
        #else
        service = environment.bundleIdentifier + "." + environment.supabaseURL.host! + ".deletion.v1"
        #endif
    }
    private var name: String { environment.backendURL.absoluteString + "|" + environment.supabaseURL.absoluteString }
    private var base: [String: Any] { [kSecClass as String:kSecClassGenericPassword,kSecAttrService as String:service,kSecAttrSynchronizable as String:false] }
    private func records() throws -> [Record] {
        // Enumerate references only; never request all password data in one query.
        var q=base; q[kSecReturnPersistentRef as String]=true; q[kSecMatchLimit as String]=kSecMatchLimitAll
        var value: CFTypeRef?
        #if FCA_DELETION_APPLE_CHECKS
        if failEnumeration { throw AuthFailure.storage }
        #endif
        let result=SecItemCopyMatching(q as CFDictionary,&value)
        #if FCA_DELETION_APPLE_CHECKS
        DeletionAppleDiagnostics.status("receipt_enumerate",result)
        #endif
        if result == errSecItemNotFound { return [] }
        guard result == errSecSuccess, let references=value as? [Data] else { throw AuthFailure.storage }
        let resultRecords=try references.map { reference -> Record in
            var itemQuery=base
            itemQuery[kSecValuePersistentRef as String]=reference
            itemQuery[kSecReturnData as String]=true
            itemQuery[kSecReturnAttributes as String]=true
            itemQuery[kSecMatchLimit as String]=kSecMatchLimitOne
            var itemValue: CFTypeRef?
            #if FCA_DELETION_APPLE_CHECKS
            if failRecordRead { throw AuthFailure.storage }
            #endif
            let status=SecItemCopyMatching(itemQuery as CFDictionary,&itemValue)
            #if FCA_DELETION_APPLE_CHECKS
            DeletionAppleDiagnostics.status("receipt_read",status)
            #endif
            // A missing individual item is an error, including concurrent deletion.
            guard status == errSecSuccess, let item=itemValue as? [String:Any],
                  item[kSecAttrService as String] as? String == service,
                  let data=item[kSecValueData as String] as? Data else { throw AuthFailure.storage }
            let record=try JSONDecoder().decode(Record.self,from:data)
            guard item[kSecAttrAccount as String] as? String == record.owner.uuidString else { throw AuthFailure.storage }
            return record
        }
        guard resultRecords.allSatisfy({ $0.environment == name }) else { throw AuthFailure.storage }
        return resultRecords
    }
    #if FCA_DELETION_APPLE_CHECKS
    var failEnumeration=false
    var failRecordRead=false
    var failSubmittedWrite=false
    func testRecords() throws -> [Record] { try records() }
    func testErase() { SecItemDelete(base as CFDictionary) }
    #endif
    private func save(_ record: Record) throws {
        #if FCA_DELETION_APPLE_CHECKS
        if failSubmittedWrite && record.submitted { throw AuthFailure.storage }
        #endif
        guard record.environment == name else { throw AuthFailure.storage }
        var q=base; q[kSecAttrAccount as String]=record.owner.uuidString
        if record.cleaned {
            let status=SecItemDelete(q as CFDictionary)
        #if FCA_DELETION_APPLE_CHECKS
        DeletionAppleDiagnostics.status("receipt_delete",status)
        #endif
            guard status == errSecSuccess || status == errSecItemNotFound else { throw AuthFailure.storage }
            return
        }
        let data=try JSONEncoder().encode(record)
        let status=SecItemUpdate(q as CFDictionary,[kSecValueData as String:data] as CFDictionary)
        #if FCA_DELETION_APPLE_CHECKS
        DeletionAppleDiagnostics.status("receipt_update",status)
        #endif
        if status == errSecItemNotFound {
            q[kSecValueData as String]=data; q[kSecAttrAccessible as String]=kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            let inserted=SecItemAdd(q as CFDictionary,nil)
            #if FCA_DELETION_APPLE_CHECKS
            DeletionAppleDiagnostics.status("receipt_add",inserted)
            #endif
            guard inserted == errSecSuccess else { throw AuthFailure.storage }
        } else if status != errSecSuccess { throw AuthFailure.storage }
    }
    func pending(owner: UUID?) throws -> Bool { try records().contains { !$0.cleaned && ($0.submitted || $0.completed) && (owner == nil || $0.owner == owner) } }
    func needsExplicitRetry(owner: UUID?) throws -> Bool { try records().contains { !$0.submitted && !$0.completed && $0.owner == owner } }
    func begin(_ record: Record, sessions: SessionManager, api: AuthAPI) async throws {
        try await AccountDeletionLifecycle.begin(record:record,markPending:{ try sessions.markDeletionPending() },save:save) { armed in
            let token=try await sessions.access(owner:armed.owner,forDeletion:true)
            try await self.initiate(armed,api:api,token:token)
        }
    }
    func hasPending() throws -> Bool { try records().contains { !$0.cleaned } }
    func prepare(owner: UUID) throws -> Record {
        if let old=try records().first(where: { $0.owner == owner }) { return old }
        var bytes=[UInt8](repeating:0,count:32)
        guard SecRandomCopyBytes(kSecRandomDefault,bytes.count,&bytes) == errSecSuccess else { throw AuthFailure.storage }
        let secret=Data(bytes).base64EncodedString().replacingOccurrences(of:"+",with:"-").replacingOccurrences(of:"/",with:"_").replacingOccurrences(of:"=",with:"")
        let record=Record(owner:owner,environment:name,operation:UUID(),secret:secret)
        try save(record) // MUST precede the first deletion request.
        return record
    }
    func support(api: AuthAPI) async throws {
        struct Capabilities: Decodable, Sendable { let `protocol`: String; let retention_days: Int }
        let value: Capabilities = try await api.deletionProtocol(Capabilities.self, path:"capabilities")
        guard value.protocol == "deletion-status-v1", value.retention_days == 180 else { throw AuthFailure.invalidResponse }
    }
    func initiate(_ record: Record, api: AuthAPI, token: String) async throws {
        guard let secret=record.secret, record.submitted, !record.completed else { throw AuthFailure.stale }
        let body=try JSONSerialization.data(withJSONObject:["confirmation":"DELETE_MY_ACCOUNT","status_credential":["operation_id":record.operation.uuidString.lowercased(),"secret":secret]])
        let reply: Reply = try await api.deletionProtocol(Reply.self,path:"request",authorization:"Bearer " + token,body:body)
        guard reply.operation_id == record.operation, reply.status == "pending" else { throw AuthFailure.invalidResponse }
    }
    func resume(api: AuthAPI, sessions: SessionManager) async throws -> Bool {
        var allCleaned=true
        var failed=false
        for record in try records() where !record.cleaned {
            do {
            let complete=try await AccountDeletionLifecycle.resume(record:record,status:{
                guard let secret=record.secret else { throw AuthFailure.storage }
                do { return try await api.deletionProtocol(Reply.self,path:"status",authorization:"DeletionStatus " + record.operation.uuidString.lowercased() + "." + secret,body:Data()) }
                catch AuthFailure.rejected(401, _) { throw AccountDeletionLifecycle.Failure.statusUnavailable }
            },replayInitiation:{
                if sessions.session?.owner == record.owner {
                    try await self.support(api:api)
                    let token=try await sessions.access(owner:record.owner,forDeletion:true)
                    try await self.initiate(record,api:api,token:token)
                }
            },save:save,cancel:cancelUploads,cleanup:{ try self.cleanup($0,sessions:sessions) })
            if !complete { allCleaned=false }
            } catch { failed=true; allCleaned=false }
        }
        if failed { throw AuthFailure.storage }
        return allCleaned
    }
    private func cancelUploads(_ record: Record) async throws {
        guard record.completed, record.environment == name else { throw AuthFailure.storage }
        try VehicleSessionRuntime.shared.get().fenceDeletedAccount(record.owner)
        let directory=try VehicleEventQueue.applicationDirectory()
        let identifiers=try VehicleEventQueue.fenceDeletionUploads(directory:directory,environment:name,owner:record.owner,bundle:environment.bundleIdentifier)
        for identifier in identifiers { try await VehicleBackgroundUploadTransport.cancelForDeletion(identifier) }
    }
    private func cleanup(_ record: Record, sessions: SessionManager) throws {
        guard record.completed, record.environment == name else { throw AuthFailure.storage }
        let runtime=try VehicleSessionRuntime.shared.get()
        runtime.fenceDeletedAccount(record.owner)
        let directory=try VehicleEventQueue.applicationDirectory()
        try VehicleEventQueue.cleanupDeletedAccount(directory:directory,environment:name,owner:record.owner) {
            let fm=FileManager.default
            let prefix=environment.bundleIdentifier + ".vehicle-sync.v1." + record.owner.uuidString + "."
            // Exact owner component; never follow symlink directories or infer owners from payloads.
            for url in try fm.contentsOfDirectory(at:directory,includingPropertiesForKeys:[.isSymbolicLinkKey]) where url.lastPathComponent.hasPrefix(prefix) {
                let values=try url.resourceValues(forKeys:[.isSymbolicLinkKey])
                guard values.isSymbolicLink != true else { throw AuthFailure.storage }
                try fm.removeItem(at:url)
            }
            let journal=directory.deletingLastPathComponent().appendingPathComponent("NativeDeviceRegistration").appendingPathComponent(record.owner.uuidString + ".json")
            if fm.fileExists(atPath:journal.path) { try fm.removeItem(at:journal) }
            if fm.fileExists(atPath:journal.deletingLastPathComponent().path) {
                try VehicleEventQueue.synchronizeDirectory(journal.deletingLastPathComponent())
            }
            try VehicleEventQueue.synchronizeDirectory(directory)
        }
        try NativePushService.shared.forgetDeletedAccount(record.owner)
        // Re-read persistent Keychain session; never clear another owner's session.
        let vault=KeychainVault(environment:environment)
        try VehicleEventQueue.withCleanupLock(directory:directory) {
            if try vault.read()?.owner == record.owner { try vault.clear() }
        }
        sessions.forgetDeletedSession(record.owner)
    }
}
#endif
