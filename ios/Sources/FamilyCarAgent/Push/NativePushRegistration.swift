import Foundation

@MainActor protocol NativePushStore {
    func read() throws -> [NativePushRegistration.Record]
    func write(_ records: [NativePushRegistration.Record]) throws
    func newSecret() throws -> String
}

/// Dedicated device-only item. Never stores a JWT or a raw FCM token.
@MainActor final class NativePushRegistration {
    struct Record: Codable {
        let owner: UUID
        let family: Int64
        let ref: UUID
        let secret: String
        var retired = false
        var request = UUID()
        var digest = ""
        var challenge: UUID?
        var expected: Int?
        var generation: Int?
    }
    private var records: [Record] = []
    private var loaded = false
    private var blocked = false
    private var epoch = 0
    private var working = false
    private var reconciling = false
    private let sessions: SessionManager
    private let api: any NativePushTransport
    private let store: any NativePushStore
    init(sessions: SessionManager, api: any NativePushTransport, store: any NativePushStore) {
        self.sessions = sessions; self.api = api; self.store = store
    }
    private func load() throws {
        guard !blocked else { throw AuthFailure.storage }
        guard !loaded else { return }
        records = try store.read(); loaded = true
    }
    private func save() throws {
        do { try store.write(records); blocked = false }
        catch { blocked = true; throw AuthFailure.storage }
    }
    func retire() throws {
        epoch += 1
        if !loaded { try load() }
        for index in records.indices { records[index].retired = true }
        try save()
    }
    /// Logout may clear the login only after durable local retirement or confirmed
    /// server cancellation of every known authority. Network failure alone is OK.
    func prepareLogout() async throws {
        do { try retire(); return }
        catch {
            guard loaded else { throw AuthFailure.storage }
            for record in records {
                let reply = try await api.nativePush(path:"/api/native-push/ios/installations/\(record.ref)/cancel",
                                                    fields:["secret":record.secret],token:nil)
                guard reply.code == "REVOKED" else { throw AuthFailure.storage }
            }
            records.removeAll()
            try? save() // Server cancellation is terminal even if cleanup fails.
        }
    }
    func reconcile() async throws {
        guard !reconciling else { return }
        reconciling = true; defer { reconciling = false }
        // Even after a failed local retirement write, attempt cancellation using
        // already-loaded authority. Never allow registration through this path.
        if !loaded { try load() }
        for record in records.filter(\.retired).prefix(20) {
            let reply = try await api.nativePush(path:"/api/native-push/ios/installations/\(record.ref)/cancel",
                                                        fields:["secret":record.secret],token:nil)
            if reply.code == "REVOKED" {
                records.removeAll { $0.ref == record.ref && $0.retired }; try save()
            }
        }
    }
    func revokeOnline() async throws {
        if !loaded { try load() }
        guard let session = sessions.session,
              session.expires > Date(),
              let record = records.first(where: { $0.owner == session.owner && $0.retired && $0.generation != nil }),
              let generation = record.generation else { return }
        // No refresh solely to prolong logout; capability reconciliation handles expiry.
        let reply = try await api.revokeNativePush(ref:record.ref,generation:generation,token:session.accessToken)
        guard reply.code == "REVOKED" else { throw AuthFailure.invalidResponse }
        records.removeAll { $0.ref == record.ref && $0.retired }; try save()
    }
    private func check(_ identity: ChatIdentity, _ ticket: Int) throws {
        guard !blocked, ticket == epoch, sessions.session?.owner == identity.owner,
              sessions.session?.activated == true, sessions.generation == identity.generation else { throw AuthFailure.stale }
    }
    private func authenticated(path: String, fields: [String:String], identity: ChatIdentity,
                               ticket: Int) async throws -> NativePushReply {
        for attempt in 0...1 {
            let access = try await sessions.access(owner:identity.owner,force:attempt == 1)
            try check(identity,ticket)
            do { return try await api.nativePush(path:path,fields:fields,token:access) }
            catch AuthFailure.rejected(let status, _) where status == 401 && attempt == 0 {
                try check(identity,ticket)
            }
        }
        throw AuthFailure.signedOut
    }
    func register(token: String, digest: String, identity: ChatIdentity) async throws {
        guard !working else { return }
        working = true; defer { working = false }
        try load()
        let ticket = epoch
        try check(identity,ticket)
        // Reconcile outgoing identities before claiming the same FCM token.
        for index in records.indices where records[index].owner != identity.owner || records[index].family != identity.family {
            records[index].retired = true
        }
        try save(); try await reconcile(); try check(identity,ticket)
        // Old authorities may precede a prepare request that never reached the server.
        // Backend token uniqueness, not another account's credentials, arbitrates ownership.
        if !records.contains(where: { !$0.retired && $0.owner == identity.owner && $0.family == identity.family }) {
            records.append(Record(owner:identity.owner,family:identity.family,ref:UUID(),
                                  secret:try store.newSecret()))
            try save() // cancellation authority exists locally BEFORE any request
        }
        guard let index = records.firstIndex(where: { !$0.retired && $0.owner == identity.owner && $0.family == identity.family }) else { throw AuthFailure.stale }
        let ref = records[index].ref
        let secret = records[index].secret
        let prepared = try await authenticated(path:"/api/native-push/ios/installations/\(ref)/prepare",
                                                fields:["secret":secret],identity:identity,ticket:ticket)
        try check(identity,ticket)
        guard prepared.code == "PREPARED" else { throw AuthFailure.invalidResponse }
        guard let index = records.firstIndex(where: { $0.ref == ref && !$0.retired }) else { throw AuthFailure.stale }
        if records[index].digest == digest && records[index].generation != nil { return }
        if records[index].digest != digest {
            records[index].digest = digest; records[index].request = UUID()
            records[index].challenge = nil; records[index].expected = nil; records[index].generation = nil
            try save()
        }
        let reply = try await authenticated(path:"/api/native-push/registrations",
            fields:["installation_ref":ref.uuidString,"request_id":records[index].request.uuidString,"platform":"ios","token":token],identity:identity,ticket:ticket)
        try check(identity,ticket)
        guard let index = records.firstIndex(where: { $0.ref == ref && !$0.retired }) else { throw AuthFailure.stale }
        guard let challenge = reply.challenge_ref else { throw AuthFailure.invalidResponse }
        records[index].challenge = challenge
        if let expected = reply.expected_generation { records[index].expected = expected }
        if reply.status == "expired" || reply.status == "cancelled" || reply.status == "consumed" {
            records[index].request = UUID(); records[index].challenge = nil; records[index].expected = nil
        }
        try save()
    }
    func confirm(_ data: [String:String], identity: ChatIdentity) async throws {
        try load()
        let ticket = epoch
        try check(identity,ticket)
        guard data["kind"] == "registration_challenge", let ref = UUID(uuidString:data["installation_ref"] ?? ""),
              let challenge = UUID(uuidString:data["challenge_ref"] ?? ""),
              let expected = Int(data["generation"] ?? ""), let nonce = data["nonce"], nonce.count == 43,
              let index = records.firstIndex(where: { $0.ref == ref && !$0.retired && $0.owner == identity.owner && $0.family == identity.family }),
              records[index].challenge == challenge,
              records[index].expected == nil || records[index].expected == expected else { return }
        let reply = try await authenticated(path:"/api/native-push/installations/\(ref)/confirm",
            fields:["challenge_ref":challenge.uuidString,"nonce":nonce],identity:identity,ticket:ticket)
        try check(identity,ticket)
        guard reply.code == "ACTIVE", reply.generation == expected + 1,
              let index = records.firstIndex(where: { $0.ref == ref && !$0.retired }),
              records[index].challenge == challenge else { throw AuthFailure.stale }
        records[index].generation = reply.generation; try save()
    }
    func permitsPresentation(_ ref: String, identity: ChatIdentity) -> Bool {
        guard !blocked, loaded else { return false }
        return records.contains { !$0.retired && $0.ref.uuidString.lowercased() == ref.lowercased()
            && $0.owner == identity.owner && $0.family == identity.family && $0.generation != nil }
    }
}
