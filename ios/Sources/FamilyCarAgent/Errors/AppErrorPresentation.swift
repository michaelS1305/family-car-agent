import Foundation
#if canImport(Combine)
import Combine
#endif

/// Presentation only. Callers retain ownership of operation safety and identity checks.
enum AppErrorKind: Equatable {
    case general, offline, serviceUnavailable

    static func classify(_ error: Error? = nil, status: Int? = nil) -> Self {
        if let urlError = error as? URLError, urlError.code == .notConnectedToInternet { return .offline }
        if status == 503 { return .serviceUnavailable }
        return .general
    }
    var title: String {
        switch self {
        case .general: return "משהו השתבש"
        case .offline: return "אין חיבור לאינטרנט"
        case .serviceUnavailable: return "השירות אינו זמין כרגע"
        }
    }
    var message: String {
        switch self {
        case .general: return "אירעה שגיאה זמנית. אפשר לנסות שוב."
        case .offline: return "נראה שאין חיבור לאינטרנט. בדוק את החיבור ונסה שוב."
        case .serviceUnavailable: return "לא הצלחנו להתחבר לשירות. אפשר לנסות שוב."
        }
    }
}

@MainActor final class AppErrorPresentation: ObservableObject {
    enum Stage: Equatable { case initial, retrying, failed }
    @Published private(set) var kind: AppErrorKind?
    @Published private(set) var stage = Stage.initial
    private var retryAction: (@MainActor () async -> Bool)?
    private var revision = 0
    var isPresented: Bool { kind != nil }
    var title: String { stage == .failed ? "עדיין יש תקלה" : kind?.title ?? "" }
    var message: String {
        stage == .failed
            ? "מצטערים, לא הצלחנו להשלים את הפעולה. כדאי לנסות שוב מאוחר יותר. אנחנו עובדים על פתרון התקלה."
            : kind?.message ?? ""
    }
    func present(_ kind: AppErrorKind, retry: @escaping @MainActor () async -> Bool) {
        guard !isPresented else { return }
        revision += 1; self.kind = kind; stage = .initial; retryAction = retry
    }
    func retry() async {
        guard isPresented, stage == .initial, let action = retryAction else { return }
        let ticket = revision
        stage = .retrying
        let succeeded = await action()
        guard ticket == revision, isPresented else { return }
        if succeeded { reset() } else { stage = .failed; retryAction = nil }
    }
    func dismiss() {
        guard stage != .retrying else { return }
        reset()
    }
    /// Invalidate delayed completions when leaving a screen or changing accounts.
    func reset() { revision += 1; kind = nil; stage = .initial; retryAction = nil }
}
