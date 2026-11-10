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
        case (.carPlay, .take): identifier = "0778e9ea8728412ea433f8f86f7b9641"
        case (.carPlay, .returning): identifier = "6a52317d132747a39c0b4a70cf6906c3"
        case (.bluetooth, .take): identifier = "ff56f83128ab4bbd9f302d69fe00bcad"
        case (.bluetooth, .returning): identifier = "df28edf6d0794cc5810787ac4f161904"
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
