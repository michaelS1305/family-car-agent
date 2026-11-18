import Foundation

struct ChatIdentity: Equatable, Sendable {
    let owner: UUID
    let user: Int64
    let family: Int64
    let generation: Int
    let version: Int
}

struct ChatMessage: Identifiable, Equatable, Sendable {
    enum Role: String, Sendable { case user, assistant }
    enum Delivery: Sendable { case pending, completed, failed }
    let requestID: UUID
    let role: Role
    let content: String
    let timestamp: Date
    var delivery: Delivery
    var id: String { requestID.uuidString + ":" + role.rawValue }
}

enum ChatCodec {
    private struct Row: Decodable {
        let request_id: UUID?
        let role: String
        let content: String
        let created_at: String
        let request_status: String?
    }
    private struct History: Decodable { let messages: [Row] }
    private struct Reply: Decodable { let request_id: UUID; let status: String; let assistant_message: Row }
    private static func message(_ row: Row, id: UUID, status: String) throws -> ChatMessage {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let fractional = formatter.date(from: row.created_at)
        formatter.formatOptions = [.withInternetDateTime]
        guard let date = fractional ?? formatter.date(from: row.created_at),
              let role = ChatMessage.Role(rawValue: row.role), ["completed", "failed"].contains(status) else {
            throw ChatFailure.uncertain
        }
        return ChatMessage(requestID: id, role: role, content: row.content, timestamp: date,
                           delivery: status == "failed" ? .failed : .completed)
    }
    static func history(_ data: Data) throws -> [ChatMessage] {
        do {
            let rows = try JSONDecoder().decode(History.self, from: data).messages.map { row in
                guard let id = row.request_id, let status = row.request_status else { throw ChatFailure.uncertain }
                return try message(row, id: id, status: status)
            }
            guard Set(rows.map(\.id)).count == rows.count else { throw ChatFailure.uncertain }
            return rows // Preserve server ordering, including equal timestamps.
        } catch { throw ChatFailure.uncertain }
    }
    static func reply(_ data: Data, expected: UUID) throws -> ChatMessage {
        do {
            let reply = try JSONDecoder().decode(Reply.self, from: data)
            guard reply.request_id == expected, reply.status == "completed",
                  reply.assistant_message.role == "assistant",
                  reply.assistant_message.request_id == nil || reply.assistant_message.request_id == expected else {
                throw ChatFailure.uncertain
            }
            return try message(reply.assistant_message, id: expected, status: reply.status)
        } catch { throw ChatFailure.uncertain }
    }
    static func validInput(_ text: String) -> Bool { (1...4000).contains(text.unicodeScalars.count) }
}

/// No raw response, server message, token or request text is retained in errors.
struct ChatFailure: Error, Equatable, Sendable {
    enum Kind: Sendable { case auth, validation, conflict, terminal, inProgress, rateLimited, uncertain, unknown }
    let kind: Kind
    var status: Int? = nil
    var retryAfter: TimeInterval = 0
    var retryable = false
    static let uncertain = ChatFailure(kind: .uncertain, retryable: true)
    static func parse(status: Int, data: Data, retryHeader: String?, now: Date = Date()) -> Self {
        let json = data.count <= 16384 ? (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] : nil
        let detail = json?["detail"] as? [String: Any]
        let rawCode = detail?["code"] as? String ?? ""
        let code = rawCode.count <= 128 ? rawCode : ""
        let bodyDelay = detail?["retry_after_seconds"] as? Double
        func bounded(_ value: Double?) -> Double {
            guard let value, value.isFinite, value >= 0, value <= Double(Int32.max) else { return 0 }
            return ceil(value)
        }
        var headerDelay: Double = 0
        if let retryHeader {
            if let seconds = Int64(retryHeader) { headerDelay = bounded(Double(seconds)) }
            else {
                let formatter = DateFormatter()
                formatter.locale = Locale(identifier: "en_US_POSIX")
                formatter.timeZone = TimeZone(secondsFromGMT: 0)
                formatter.dateFormat = "EEE, dd MMM yyyy HH:mm:ss zzz"
                if let date = formatter.date(from: retryHeader) {
                    headerDelay = min(Double(Int32.max), max(0, ceil(date.timeIntervalSince(now))))
                }
            }
        }
        let kind: Kind
        if status == 401 || status == 403 { kind = .auth }
        else if status == 400 || status == 422 { kind = .validation }
        else if ["IDEMPOTENCY_KEY_REUSED", "REQUEST_CONTEXT_CHANGED"].contains(code) { kind = .conflict }
        else if ["AI_UNAVAILABLE", "CHAT_ATTEMPTS_EXHAUSTED"].contains(code) { kind = .terminal }
        else if ["CHAT_IN_PROGRESS", "CHAT_CONCURRENCY_LIMITED", "CHAT_LEASE_LOST"].contains(code) { kind = .inProgress }
        else if status == 429 { kind = .rateLimited }
        else if ["CHAT_RECOVERY_REQUIRED", "GEMINI_CAPACITY_UNAVAILABLE"].contains(code) { kind = .uncertain }
        else { kind = .unknown }
        return Self(kind: kind, status: status, retryAfter: max(bounded(bodyDelay), headerDelay),
                    retryable: [.inProgress, .rateLimited, .uncertain].contains(kind) || (status >= 500 && kind == .unknown))
    }
}

struct ChatScrollPolicy {
    private(set) var following = true
    private var initialized = false
    private var keys: [String] = []
    mutating func userScrolled(distance: Double) { following = distance <= 48 }
    mutating func sent() { following = true }
    mutating func update(_ next: [String], ready: Bool) -> Bool {
        guard ready else { return false }
        let prepended = initialized && !keys.isEmpty && next.count > keys.count && Array(next.suffix(keys.count)) == keys
        initialized = true; keys = next
        return following && !prepended
    }
}

@MainActor protocol ChatGateway: AnyObject {
    var chatIdentity: ChatIdentity? { get }
    func chatHistory(identity: ChatIdentity) async throws -> [ChatMessage]
    func chatSend(identity: ChatIdentity, id: UUID, message: String) async throws -> ChatMessage
}

protocol ChatTransport: Sendable {
    func chat(token: String, id: UUID?, message: String?) async throws -> Data
}
