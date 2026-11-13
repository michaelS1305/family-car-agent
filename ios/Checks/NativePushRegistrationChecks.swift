import Foundation

@MainActor final class PushTestVault: SessionVault {
    var value: AuthSession?
    func read() throws -> AuthSession? { value }
    func write(_ value: AuthSession) throws { self.value = value }
    func clear() throws { value = nil }
}
actor PushTestAuth: AuthTransport {
    let value: AuthSession
    init(_ value: AuthSession) { self.value = value }
    func exchange(grant: String, fields: [String:String]) async throws -> AuthSession { value }
}
@MainActor final class PushTestStore: NativePushStore {
    var records: [NativePushRegistration.Record] = []
    var fail = false
    func read() throws -> [NativePushRegistration.Record] { records }
    func write(_ records: [NativePushRegistration.Record]) throws {
        if fail { throw AuthFailure.storage }; self.records = records
    }
    func newSecret() throws -> String { String(repeating:"a",count:64) }
}
actor PushTestAPI: NativePushTransport {
    var requests: [(String,[String:String],String?)] = []
    var challenge = UUID()
    var offline = false
    var gate: CheckedContinuation<Void,Never>?
    var pauseBegin = false
    var rejectBeginOnce = false
    func rejectOnce() { rejectBeginOnce = true }
    func beginRequests() -> [[String:String]] { requests.filter { $0.0.hasSuffix("/registrations") }.map { $0.1 } }
    func setOffline(_ value: Bool) { offline = value }
    func pause() { pauseBegin = true }
    func release() { pauseBegin = false; gate?.resume(); gate = nil }
    func count() -> Int { requests.count }
    func waiting() -> Bool { gate != nil }
    func reply(_ code: String, challenge: UUID? = nil, generation: Int? = nil) -> NativePushReply {
        NativePushReply(code:code,challenge_ref:challenge,expected_generation:challenge == nil ? nil : 1,
                        generation:generation,status:nil)
    }
    func nativePush(path: String, fields: [String:String], token: String?) async throws -> NativePushReply {
        requests.append((path,fields,token))
        if offline { throw AuthFailure.network }
        if path.hasSuffix("/prepare") { return reply("PREPARED") }
        if path.hasSuffix("/cancel") {
            precondition(token == nil && fields.keys.sorted() == ["secret"])
            return reply("REVOKED")
        }
        if path.hasSuffix("/confirm") { return reply("ACTIVE",generation:2) }
        if rejectBeginOnce { rejectBeginOnce = false; throw AuthFailure.rejected(401,"expired") }
        if pauseBegin { await withCheckedContinuation { gate = $0 } }
        return reply("CHALLENGE_PENDING",challenge:challenge)
    }
    func revokeNativePush(ref: UUID, generation: Int, token: String) async throws -> NativePushReply {
        if offline { throw AuthFailure.network }; return reply("REVOKED")
    }
}

@main enum NativePushRegistrationChecks {
    @MainActor static func main() async throws {
        let owner = UUID()
        var session = AuthSession(owner:owner,accessToken:"synthetic-access",refreshToken:"synthetic-refresh",expires:Date().addingTimeInterval(3600))
        session.activated = true
        let vault = PushTestVault(); vault.value = session
        let sessions = SessionManager(vault:vault,transport:PushTestAuth(session)); try sessions.restore()
        let identity = ChatIdentity(owner:owner,user:1,family:10,generation:0,version:0)
        let store = PushTestStore(); let api = PushTestAPI()
        let registration = NativePushRegistration(sessions:sessions,api:api,store:store)
        try await registration.register(token:"synthetic-fcm",digest:"digest-one",identity:identity)
        precondition(store.records.count == 1 && store.records[0].challenge != nil)
        let record = store.records[0]
        let signal = ["kind":"registration_challenge","installation_ref":record.ref.uuidString,
                      "challenge_ref":record.challenge!.uuidString,"generation":"1","nonce":String(repeating:"n",count:43)]
        try await registration.confirm(signal,identity:identity)
        precondition(registration.permitsPresentation(record.ref.uuidString,identity:identity))
        let before = await api.count()
        try await registration.register(token:"synthetic-fcm",digest:"digest-one",identity:identity)
        let after = await api.count()
        precondition(after == before + 1) // preparation is idempotent; no duplicate begin
        try await registration.register(token:"synthetic-new-fcm",digest:"digest-two",identity:identity)
        precondition(store.records[0].generation == nil && store.records[0].digest == "digest-two")
        let serialized = String(decoding:try JSONEncoder().encode(store.records),as:UTF8.self)
        precondition(!serialized.contains("synthetic-access") && !serialized.contains("synthetic-refresh") && !serialized.contains("synthetic-new-fcm"))
        await api.setOffline(true)
        try registration.retire(); try sessions.clear()
        do { try await registration.reconcile(); preconditionFailure("offline cancel must fail") } catch {}
        precondition(store.records[0].retired)
        let restored = NativePushRegistration(sessions:sessions,api:api,store:store)
        await api.setOffline(false)
        try await restored.reconcile(); precondition(store.records.isEmpty)
        do { try await restored.confirm(signal,identity:identity); preconditionFailure("old identity") } catch {}

        vault.value = session; try sessions.restore()
        let next = ChatIdentity(owner:owner,user:1,family:10,generation:sessions.generation,version:1)
        let raceStore = PushTestStore(); let raceAPI = PushTestAPI()
        let racing = NativePushRegistration(sessions:sessions,api:raceAPI,store:raceStore)
        await raceAPI.pause()
        let task = Task { try await racing.register(token:"synthetic",digest:"race",identity:next) }
        while !(await raceAPI.waiting()) { await Task.yield() }
        let calls = await raceAPI.count()
        try await racing.register(token:"duplicate",digest:"duplicate",identity:next)
        let afterDuplicate = await raceAPI.count()
        precondition(afterDuplicate == calls)
        try racing.retire(); try sessions.clear(); await raceAPI.release()
        do { try await task.value; preconditionFailure("stale begin accepted") } catch {}
        precondition(raceStore.records.allSatisfy(\.retired))

        vault.value = session; try sessions.restore()
        let failStore = PushTestStore(); failStore.fail = true
        let failAPI = PushTestAPI()
        let failed = NativePushRegistration(sessions:sessions,api:failAPI,store:failStore)
        let current = ChatIdentity(owner:owner,user:1,family:10,generation:sessions.generation,version:2)
        do { try await failed.register(token:"synthetic",digest:"x",identity:current); preconditionFailure("storage failure") } catch {}
        let failedCalls = await failAPI.count()
        precondition(failedCalls == 0)
        // Caller clears credentials only after prepareLogout succeeds.
        let logoutStore = PushTestStore(); let logoutAPI = PushTestAPI()
        let logoutRegistration = NativePushRegistration(sessions:sessions,api:logoutAPI,store:logoutStore)
        try await logoutRegistration.register(token:"synthetic",digest:"logout",identity:current)
        logoutStore.fail = true; await logoutAPI.setOffline(true)
        do {
            try await logoutRegistration.prepareLogout()
            try sessions.clear()
            preconditionFailure("double failure must block logout")
        } catch {}
        precondition(sessions.session?.owner == owner && vault.value?.owner == owner)
        // Retry with reliable local storage: offline logout is allowed and durable.
        logoutStore.fail = false
        try await logoutRegistration.prepareLogout()
        precondition(logoutStore.records.allSatisfy(\.retired))
        try sessions.clear()
        precondition(sessions.session == nil && vault.value == nil)
        await logoutAPI.setOffline(false)
        let afterLogout = NativePushRegistration(sessions:sessions,api:logoutAPI,store:logoutStore)
        try await afterLogout.reconcile()
        precondition(logoutStore.records.isEmpty)

        // A confirmed server cancellation also permits logout if local writes fail.
        vault.value = session; try sessions.restore()
        let onlineIdentity = ChatIdentity(owner:owner,user:1,family:10,generation:sessions.generation,version:3)
        let onlineStore = PushTestStore(); let onlineAPI = PushTestAPI()
        let online = NativePushRegistration(sessions:sessions,api:onlineAPI,store:onlineStore)
        try await online.register(token:"synthetic",digest:"online",identity:onlineIdentity)
        onlineStore.fail = true
        try await online.prepareLogout()
        try sessions.clear()
        precondition(sessions.session == nil)
        vault.value = session; try sessions.restore()
        let refreshIdentity = ChatIdentity(owner:owner,user:1,family:10,generation:sessions.generation,version:4)
        let refreshAPI = PushTestAPI(); await refreshAPI.rejectOnce()
        let refreshRegistration = NativePushRegistration(sessions:sessions,api:refreshAPI,store:PushTestStore())
        try await refreshRegistration.register(token:"synthetic",digest:"refresh",identity:refreshIdentity)
        let attempts = await refreshAPI.beginRequests()
        precondition(attempts.count == 2 && attempts[0] == attempts[1])
        // Forced invalidation never retains credentials, even if retirement cannot
        // be persisted. In-process capability retry remains possible without JWT.
        let forcedStore = PushTestStore(); let forcedAPI = PushTestAPI()
        let forced = NativePushRegistration(sessions:sessions,api:forcedAPI,store:forcedStore)
        try await forced.register(token:"synthetic",digest:"forced",identity:refreshIdentity)
        forcedStore.fail = true; await forcedAPI.setOffline(true)
        sessions.onInvalidation = { _ in try? forced.retire() }
        try sessions.clear()
        precondition(sessions.session == nil && vault.value == nil)
        do { _ = try await sessions.access(owner:owner); preconditionFailure("revoked account accessible") } catch {}
        do { try await forced.reconcile(); preconditionFailure("offline cancellation reported success") } catch {}
        await forcedAPI.setOffline(false); forcedStore.fail = false
        try await forced.reconcile()
        precondition(forcedStore.records.isEmpty && sessions.session == nil)
        print("Native Push registration checks passed: confirmation, duplicate callbacks, rotation, offline retirement, restart, stale responses and storage failure. Synthetic only.")
    }
}
