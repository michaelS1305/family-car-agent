import Foundation
#if !canImport(Combine)
protocol ObservableObject: AnyObject {}
@propertyWrapper struct Published<Value> { var wrappedValue: Value; init(wrappedValue: Value) { self.wrappedValue = wrappedValue } }
#endif

@main struct ErrorPresentationChecks {
    @MainActor static func main() async {
        precondition(AppErrorKind.classify(URLError(.notConnectedToInternet)) == .offline)
        precondition(AppErrorKind.classify(URLError(.timedOut)) == .general)
        precondition(AppErrorKind.classify(URLError(.cannotFindHost)) == .general)
        precondition(AppErrorKind.classify(status: 503) == .serviceUnavailable)
        precondition(AppErrorKind.classify(status: 500) == .general)
        let state = AppErrorPresentation()
        var calls = 0
        state.present(.offline) { calls += 1; return true }
        state.present(.general) { preconditionFailure("stacked dialog replaced retry") }
        precondition(state.kind == .offline && calls == 0)
        await state.retry()
        precondition(!state.isPresented && calls == 1)
        state.present(.general) { calls += 1; return false }
        await state.retry()
        precondition(state.stage == .failed && state.title == "עדיין יש תקלה")
        precondition(state.message.contains("כדאי לנסות שוב מאוחר יותר"))
        await state.retry()
        precondition(calls == 2)
        state.dismiss()
        precondition(!state.isPresented)
        var continuation: CheckedContinuation<Bool, Never>?
        state.present(.general) {
            calls += 1
            return await withCheckedContinuation { continuation = $0 }
        }
        let task = Task { await state.retry() }
        while continuation == nil { await Task.yield() }
        precondition(state.stage == .retrying)
        await state.retry(); state.dismiss()
        precondition(calls == 3 && state.isPresented)
        // Leaving the context invalidates completions without resetting any model/navigation.
        state.reset()
        state.present(.serviceUnavailable) { true }
        continuation?.resume(returning: false)
        await task.value
        precondition(state.kind == .serviceUnavailable && state.stage == .initial)
        await state.retry()
        precondition(!state.isPresented)
        print("PASS: error classification, success, fallback, dismissal, duplicate retry, stacking and stale completion")
    }
}
