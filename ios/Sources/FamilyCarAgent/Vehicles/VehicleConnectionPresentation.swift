import Foundation

/// Transient navigation only; authorization always comes from runtime/SQLite.
struct VehicleConnectionPresentation {
    enum Screen { case loading, selection, setup }
    private(set) var screen = Screen.loading
    private(set) var method: VehicleConnectionMethod?
    private(set) var authorization = VehicleConnectionAuthorizationState.recoveryRequired
    private(set) var methodLocked = false
    var canGoBack: Bool { screen == .setup && !methodLocked && authorization.permitsActivation }
    var showsShortcuts: Bool { authorization.isAuthorized }
    var showsActivation: Bool { screen == .setup && authorization.permitsActivation && method != nil }
    mutating func restore(method saved: VehicleConnectionMethod?, authorization state: VehicleConnectionAuthorizationState) {
        authorization = state
        // A saved method is per vehicle, after an explicit binding attempt, not global registration.
        // Interrupted verification preserves the choice and offers verification, not a new setup.
        if let saved { method = saved; methodLocked = true }
        if state.isAuthorized { methodLocked = true }
        if methodLocked || !state.permitsActivation { screen = .setup }
        else if screen == .loading || method == nil { screen = .selection }
    }
    mutating func choose(_ value: VehicleConnectionMethod) {
        guard screen == .selection, !methodLocked, authorization.permitsActivation else { return }
        method = value; screen = .setup
    }
    mutating func back() { if canGoBack { screen = .selection } }
    mutating func verifying() { authorization = .verificationPending }
    mutating func unavailable() { authorization = .recoveryRequired; screen = .setup }
}
