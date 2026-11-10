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
    func shortcutURL(for action: ShortcutAction) -> URL? {
        guard showsShortcuts, let method else { return nil }
        let identifier: String
        switch (method, action) {
        case (.carPlay, .take): identifier = "1edc051a0b3f4afeb14ae74965b10468"
        case (.carPlay, .returning): identifier = "a19d6cb2360a4abea9725277df018933"
        case (.bluetooth, .take): identifier = "a20e5d04b43e4c1c942d30d331478e3a"
        case (.bluetooth, .returning): identifier = "d23eb9c427674a8f9b84ff8555027763"
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
