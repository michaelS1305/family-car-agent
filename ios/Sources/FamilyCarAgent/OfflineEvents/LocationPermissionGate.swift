// Pure sequencing policy. Notification completion and foreground state are independent.
struct LocationPermissionGate {
    private(set) var notificationsCompleted = false
    private(set) var requested = false
    mutating func notificationsFinished() { notificationsCompleted = true }
    mutating func shouldRequest(active: Bool, notDetermined: Bool) -> Bool {
        guard notificationsCompleted, active, notDetermined, !requested else { return false }
        requested = true
        return true
    }
}
