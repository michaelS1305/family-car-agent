import Foundation
#if canImport(Combine)
import Combine
#endif

@MainActor final class ChatModel: ObservableObject {
    enum Mode { case chat, dashboard }
    struct Pending { let identity: ChatIdentity; let id: UUID; let text: String }
    static let suggestions = ["מי משתמש ברכב כרגע?", "אילו רכבים פנויים עכשיו?", "אני צריך להזמין את הרכב"]
    @Published var mode = Mode.chat
    @Published var draft = ""
    @Published private(set) var messages: [ChatMessage] = []
    @Published private(set) var historyLoaded = false
    @Published private(set) var historyLoading = false
    @Published private(set) var historyError: ChatFailure?
    @Published private(set) var sending = false
    @Published private(set) var error: ChatFailure?
    @Published private(set) var pending: Pending?
    @Published private(set) var retryNotBefore: Date?
    @Published private(set) var scrollRequest = 0
    @Published private(set) var contextRevision = 0
    private var identity: ChatIdentity?
    private let gateway: any ChatGateway
    private let now: () -> Date
    private var operation: Task<Void, Never>?
    init(gateway: any ChatGateway, now: @escaping () -> Date = Date.init) { self.gateway = gateway; self.now = now }
    var canSend: Bool {
        identity != nil && identity == gateway.chatIdentity && historyLoaded && !historyLoading && !sending && pending == nil &&
        ChatCodec.validInput(draft.trimmingCharacters(in: .whitespacesAndNewlines))
    }
    var showSuggestions: Bool { historyLoaded && !historyLoading && messages.isEmpty }
    func canRetry(at date: Date) -> Bool {
        identity != nil && identity == gateway.chatIdentity && !sending && pending != nil && error?.retryable == true &&
        date >= (retryNotBefore ?? .distantPast)
    }
    func synchronize() {
        guard identity != gateway.chatIdentity else { return }
        operation?.cancel(); operation = nil; identity = gateway.chatIdentity; contextRevision += 1
        messages = []; draft = ""; pending = nil; sending = false; historyLoaded = false; historyLoading = false
        historyError = nil; error = nil; retryNotBefore = nil; mode = .chat; scrollRequest = 0
    }
    func enter() {
        synchronize()
        if !historyLoaded && !historyLoading && historyError == nil { loadHistory() }
    }
    private func valid(_ expected: ChatIdentity, _ revision: Int) -> Bool {
        synchronize()
        return identity == expected && revision == contextRevision
    }
    func loadHistory() {
        synchronize()
        guard let identity, !sending, !historyLoading, pending == nil else { return }
        let revision = contextRevision
        historyLoading = true; historyError = nil
        operation = Task {
            do {
                let rows = try await gateway.chatHistory(identity: identity)
                guard valid(identity, revision) else { return }
                messages = rows; historyLoaded = true; historyLoading = false
            } catch {
                guard valid(identity, revision) else { return }
                historyError = Self.failure(error); historyLoading = false
            }
        }
    }
    @discardableResult func send() -> Bool {
        synchronize()
        guard canSend, let identity else { return false }
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        let request = Pending(identity: identity, id: UUID(), text: text)
        messages.append(ChatMessage(requestID: request.id, role: .user, content: text, timestamp: now(), delivery: .pending))
        pending = request; draft = ""; scrollRequest += 1
        submit(request)
        return true
    }
    @discardableResult func retry() -> Bool {
        synchronize()
        guard canRetry(at: now()), let pending else { return false }
        scrollRequest += 1; submit(pending); return true
    }
    private func mark(_ id: UUID, _ delivery: ChatMessage.Delivery) {
        if let index = messages.firstIndex(where: { $0.requestID == id && $0.role == .user }) { messages[index].delivery = delivery }
    }
    private func submit(_ request: Pending) {
        let revision = contextRevision
        sending = true; error = nil; retryNotBefore = nil; mark(request.id, .pending)
        operation = Task {
            do {
                let reply = try await gateway.chatSend(identity: request.identity, id: request.id, message: request.text)
                guard valid(request.identity, revision) else { return }
                guard reply.requestID == request.id, reply.role == .assistant, reply.delivery == .completed else {
                    throw ChatFailure.uncertain
                }
                mark(request.id, .completed); messages.append(reply)
                sending = false; pending = nil; error = nil; retryNotBefore = nil
            } catch {
                guard valid(request.identity, revision) else { return }
                let failure = Self.failure(error)
                mark(request.id, .failed); sending = false; self.error = failure
                pending = failure.retryable ? request : nil
                retryNotBefore = now().addingTimeInterval(failure.retryAfter)
            }
        }
    }
    private static func failure(_ error: Error) -> ChatFailure {
        if let failure = error as? ChatFailure { return failure }
        if let failure = error as? AuthFailure {
            switch failure {
            case .signedOut, .stale, .rejected(401, _), .rejected(403, _): return ChatFailure(kind: .auth)
            default: break
            }
        }
        return .uncertain
    }
    /// Used by standalone checks; does not initiate any additional operation.
    func waitForOperation() async { await operation?.value }
}
