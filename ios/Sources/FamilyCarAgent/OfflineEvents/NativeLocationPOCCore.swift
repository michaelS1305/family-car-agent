#if DEBUG && !FCA_PRODUCTION
import Foundation

/// One acquisition, with an injected monotonic elapsed clock and terminal cleanup.
/// No location values are persisted and this component has no queue dependency.
@MainActor final class NativeLocationPOCCore {
    enum Outcome: String { case acquired, unauthorized, unavailable, timedOut, cancelled, failed }
    enum Authorization { case allowed, denied, unavailable }
    private(set) var outcome: Outcome?
    private(set) var started = false
    private let elapsed: () -> Duration
    private let cleanup: () -> Void
    private let completion: (Outcome) -> Void
    static let limit: Duration = .seconds(15)

    init(elapsed: @escaping () -> Duration, cleanup: @escaping () -> Void,
         completion: @escaping (Outcome) -> Void) {
        self.elapsed = elapsed; self.cleanup = cleanup; self.completion = completion
    }
    func start(_ authorization: Authorization) -> Bool {
        guard !started, outcome == nil else { return false }
        started = true
        switch authorization {
        case .denied: finish(.unauthorized)
        case .unavailable: finish(.unavailable)
        case .allowed: if elapsed() >= Self.limit { finish(.timedOut) }
        }
        return outcome == nil
    }
    func measurement(hasSource: Bool, simulated: Bool, validCoordinates: Bool,
                     accuracy: Double, age: Double) -> ReturnLocationReason? {
        guard started, outcome == nil else { return nil }
        guard elapsed() < Self.limit else { finish(.timedOut); return nil }
        let reason = ReturnLocationValidation.rejection(present: true, requiresSource: false,
            hasSource: hasSource, simulated: simulated, validCoordinates: validCoordinates,
            accuracy: accuracy, age: age)
        if reason == nil { finish(.acquired) }
        return reason
    }
    func timeout() { if elapsed() >= Self.limit { finish(.timedOut) } }
    func cancel() { finish(.cancelled) }
    func failure() { finish(.failed) }
    private func finish(_ result: Outcome) {
        guard outcome == nil else { return }
        outcome = result
        cleanup()
        completion(result)
    }
}
#endif
