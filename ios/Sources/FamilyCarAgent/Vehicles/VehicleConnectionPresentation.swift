import Foundation

/// Transient navigation only; authorization always comes from runtime/SQLite.
struct VehicleConnectionPresentation {
    enum Screen { case loading, selection, setup }
    enum ShortcutAction { case take, returning }
    private(set) var screen = Screen.loading
    private(set) var method: VehicleConnectionMethod?
    private(set) var authorization = VehicleConnectionAuthorizationState.recoveryRequired
    private(set) var methodLocked = false
    var canGoBack: Bool { screen == .setup && !methodLocked && authorization.permitsActivation }
    var showsShortcuts: Bool { authorization.isAuthorized }
    var showsActivation: Bool { screen == .setup && authorization.permitsActivation && method != nil }
    func shortcutURL(for action: ShortcutAction, environment: AppEnvironment?) -> URL? {
        guard showsShortcuts, let method, let environment else { return nil }
        let identifier: String
        switch (environment, method, action) {
        case (.development, .carPlay, .take): identifier = "099b74c9808f4dcba04a8578e2a469d0"
        case (.development, .carPlay, .returning): identifier = "34aa0aaf15cb43a8b1824176231f3950"
        case (.development, .bluetooth, .take): identifier = "306ff496250b4e28a7702ca430e94ffe"
        case (.development, .bluetooth, .returning): identifier = "022b1a3800b243a4b576fb7deac614ab"
        case (.production, .carPlay, .take): identifier = "90e16638d8a84f44868298cfebf95a92"
        case (.production, .carPlay, .returning): identifier = "f67ed93cb09c4dee8ed595c9d14db3db"
        case (.production, .bluetooth, .take): identifier = "e1bd388340fe49309523a570f05b12f6"
        case (.production, .bluetooth, .returning): identifier = "6ee5f10d3f154735b2e3c7ac4430dc7b"
        }
        return URL(string: "https://www.icloud.com/shortcuts/" + identifier)
    }
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
