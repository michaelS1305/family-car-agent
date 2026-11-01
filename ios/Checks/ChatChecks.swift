import Foundation
#if !canImport(Combine)
protocol ObservableObject: AnyObject {}
@propertyWrapper struct Published<Value> { var wrappedValue: Value; init(wrappedValue: Value) { self.wrappedValue = wrappedValue } }
#endif

@MainActor final class MockChat: ChatGateway {
    var chatIdentity: ChatIdentity? = ChatIdentity(owner: UUID(), user: 1, family: 2, generation: 0, version: 0)
    var history: [ChatMessage] = []
    var calls: [(UUID, String)] = []
    var historyCalls = 0
    var failure: ChatFailure?
    var pause = false
    var continuation: CheckedContinuation<Void, Never>?
    var wrongReply = false
    func chatHistory(identity: ChatIdentity) async throws -> [ChatMessage] {
        historyCalls += 1
        if pause { await withCheckedContinuation { continuation = $0 } }
        if let failure { throw failure }
        return history
    }
    func chatSend(identity: ChatIdentity, id: UUID, message: String) async throws -> ChatMessage {
        calls.append((id, message))
        if pause { await withCheckedContinuation { continuation = $0 } }
        if let failure { throw failure }
        return ChatMessage(requestID: wrongReply ? UUID() : id, role: .assistant, content: "תשובה", timestamp: Date(), delivery: .completed)
    }
    func release() { pause = false; continuation?.resume(); continuation = nil }
}

@main struct ChatChecks {
    @MainActor static var count = 0
    @MainActor static func check(_ condition: Bool, _ label: String) { precondition(condition, label); count += 1 }
    @MainActor static func rejects(_ label: String, _ action: () throws -> Void) {
        do { try action(); preconditionFailure(label) } catch { check(error is ChatFailure, label) }
    }
    @MainActor static func main() async throws {
        let id = UUID()
        func row(_ role: String, _ content: String = "טקסט") -> String {
            "{\"request_id\":\"\(id)\",\"role\":\"\(role)\",\"content\":\"\(content)\",\"created_at\":\"2026-10-30T10:00:00Z\",\"request_status\":\"completed\"}"
        }
        let ordered = try ChatCodec.history(Data("{\"messages\":[\(row("user")),\(row("assistant"))]}".utf8))
        check(ordered.map(\.role) == [.user, .assistant], "server tie order")
        check(try ChatCodec.history(Data("{\"messages\":[]}".utf8)).isEmpty, "empty history")
        rejects("duplicate stable keys") { _ = try ChatCodec.history(Data("{\"messages\":[\(row("user")),\(row("user"))]}".utf8)) }
        for invalid in ["{}", "{\"messages\":[{}]}", "{\"messages\":[\(row("system"))]}", "{\"messages\":[\(row("user").replacingOccurrences(of: "2026-10-30T10:00:00Z", with: "bad"))]}"] {
            rejects("malformed history") { _ = try ChatCodec.history(Data(invalid.utf8)) }
        }
        let reply = "{\"request_id\":\"\(id)\",\"status\":\"completed\",\"assistant_message\":\(row("assistant"))}"
        check(try ChatCodec.reply(Data(reply.utf8), expected: id).role == .assistant, "reply")
        rejects("wrong request") { _ = try ChatCodec.reply(Data(reply.utf8), expected: UUID()) }
        for invalid in [reply.replacingOccurrences(of: "completed", with: "processing"), reply.replacingOccurrences(of: "assistant\"", with: "user\""), "{}"] {
            rejects("malformed reply") { _ = try ChatCodec.reply(Data(invalid.utf8), expected: id) }
        }
        check(!ChatCodec.validInput(""), "empty")
        check(ChatCodec.validInput(String(repeating: "😀", count: 4000)), "scalar emoji boundary")
        check(!ChatCodec.validInput(String(repeating: "😀", count: 4001)), "scalar limit")
        check(!ChatCodec.validInput(String(repeating: "e\u{301}", count: 2001)), "combining scalars")
        let now = Date(timeIntervalSince1970: 1_000)
        let limited = ChatFailure.parse(status: 429, data: Data("{\"detail\":{\"retry_after_seconds\":2.2}}".utf8), retryHeader: "8", now: now)
        check(limited.retryAfter == 8 && limited.retryable, "maximum retry delay")
        let dateDelay = ChatFailure.parse(status: 429, data: Data(), retryHeader: "Thu, 01 Jan 1970 00:16:50 GMT", now: now)
        check(dateDelay.retryAfter == 10, "http date retry")
        for (status, code, kind, retryable) in [
            (401,"",ChatFailure.Kind.auth,false), (403,"",.auth,false), (422,"",.validation,false),
            (409,"IDEMPOTENCY_KEY_REUSED",.conflict,false), (409,"REQUEST_CONTEXT_CHANGED",.conflict,false),
            (503,"AI_UNAVAILABLE",.terminal,false), (503,"CHAT_ATTEMPTS_EXHAUSTED",.terminal,false),
            (409,"CHAT_IN_PROGRESS",.inProgress,true), (409,"CHAT_CONCURRENCY_LIMITED",.inProgress,true),
            (409,"CHAT_LEASE_LOST",.inProgress,true), (503,"CHAT_RECOVERY_REQUIRED",.uncertain,true),
            (503,"GEMINI_CAPACITY_UNAVAILABLE",.uncertain,true), (500,"",.unknown,true), (404,"",.unknown,false)] {
            let failure = ChatFailure.parse(status: status, data: Data("{\"detail\":{\"code\":\"\(code)\"}}".utf8), retryHeader: nil)
            check(failure.kind == kind && failure.retryable == retryable, "error classification")
        }
        check(ChatFailure.parse(status: 429, data: Data(), retryHeader: "secret").retryAfter == 0, "invalid header")
        var policy = ChatScrollPolicy()
        check(!policy.update([], ready: false), "not ready")
        check(policy.update(["1"], ready: true), "initial scroll")
        policy.userScrolled(distance: 100)
        check(!policy.update(["1","2"], ready: true), "reading older")
        check(!policy.following, "keyboard must preserve reading")
        policy.sent(); check(policy.following, "send follows")
        check(!policy.update(["0","1","2"], ready: true), "prepend")
        policy.userScrolled(distance: 48); check(policy.following, "threshold")

        let gateway = MockChat(); let model = ChatModel(gateway: gateway, now: { now })
        model.draft = "cannot send yet"; check(!model.send(), "initial blocked")
        model.enter(); model.enter(); await model.waitForOperation()
        check(gateway.historyCalls == 1 && model.showSuggestions, "single history / suggestions")
        check(ChatModel.suggestions.count == 3, "suggestions")
        model.draft = ChatModel.suggestions[0]
        check(gateway.calls.isEmpty, "suggestion never sends")
        model.mode = .dashboard; model.mode = .chat
        check(model.draft == ChatModel.suggestions[0] && model.historyLoaded, "mode preserves state")
        gateway.pause = true
        check(model.send(), "send accepted")
        check(model.sending && model.messages.count == 1 && model.messages[0].delivery == .pending && model.draft.isEmpty, "optimistic waiting")
        model.draft = "second"; check(!model.send(), "duplicate blocked")
        model.loadHistory(); check(gateway.historyCalls == 1, "pending history blocked")
        while gateway.continuation == nil { await Task.yield() }
        gateway.failure = .uncertain; gateway.release(); await model.waitForOperation()
        let original = gateway.calls[0]
        check(model.pending != nil && model.messages[0].delivery == .failed && !model.sending, "uncertain retained")
        model.loadHistory(); check(gateway.historyCalls == 1, "uncertain history blocked")
        gateway.failure = nil; check(model.retry(), "retry accepted"); await model.waitForOperation()
        check(gateway.calls.count == 2 && gateway.calls[1].0 == original.0 && gateway.calls[1].1 == original.1, "same id and payload")
        check(model.messages.count == 2 && model.pending == nil && model.messages.allSatisfy { $0.delivery == .completed }, "no duplicate user")
        gateway.failure = limited; model.draft = "rate limited"; check(model.send(), "second request"); await model.waitForOperation()
        check(!model.retry() && !model.canRetry(at: now.addingTimeInterval(7)) && model.canRetry(at: now.addingTimeInterval(8)), "retry deadline")
        gateway.chatIdentity = ChatIdentity(owner: UUID(), user: 3, family: 4, generation: 1, version: 1)
        model.enter(); gateway.failure = nil; await model.waitForOperation()
        check(model.draft.isEmpty && model.messages.isEmpty && model.pending == nil, "new identity clears")
        gateway.pause = true; model.draft = "old account"; check(model.send(), "old send")
        while gateway.continuation == nil { await Task.yield() }
        let previous = gateway.chatIdentity!
        gateway.chatIdentity = ChatIdentity(owner: previous.owner, user: previous.user, family: 99, generation: previous.generation, version: previous.version)
        model.synchronize(); gateway.release(); for _ in 0..<20 { await Task.yield() }
        check(model.messages.isEmpty && !model.sending && model.draft.isEmpty, "late family response fenced")
        model.enter(); await model.waitForOperation()
        gateway.wrongReply = true; model.draft = "invalid reply"; check(model.send(), "invalid response request"); await model.waitForOperation()
        check(model.error?.kind == .uncertain && model.pending != nil && model.messages.count == 1, "mismatched reply not accepted")
        gateway.chatIdentity = nil; model.synchronize()
        check(model.messages.isEmpty && model.pending == nil && !model.canSend, "logout")
        print("Chat checks passed: \(count). Synthetic only; no network or device requests.")
    }
}
