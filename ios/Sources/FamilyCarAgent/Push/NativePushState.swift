import Foundation

/// Installation diagnostics only. Never contains a credential, token, or payload.
struct NativePushState: Equatable {
    enum Permission: String { case unknown, notDetermined, denied, authorized, provisional, ephemeral }
    enum Registration: String { case idle, waiting, succeeded, failed }
    private(set) var epoch = 0
    private(set) var active = false
    var configured = false
    var configurationLoaded = false
    var devIdentityValidated = false
    var permission: Permission = .unknown
    var apns: Registration = .idle
    var fcm: Registration = .idle
    var errorCategory = "none"
    private var tokenDigest: Data?
    private(set) var tokenChanges = 0

    mutating func activate() { epoch += 1; active = true }
    mutating func deactivate() {
        epoch += 1; active = false; apns = .idle; fcm = .idle
        tokenDigest = nil; tokenChanges = 0; errorCategory = "none"
    }
    func accepts(_ ticket: Int) -> Bool { active && configured && epoch == ticket }
    var permitsRegistration: Bool {
        [.authorized, .provisional, .ephemeral].contains(permission)
    }
    mutating func apnsResult(succeeded: Bool, ticket: Int) {
        guard accepts(ticket), permitsRegistration else { return }
        apns = succeeded ? .succeeded : .failed
        fcm = .idle
        errorCategory = succeeded ? "none" : "apns_registration"
    }
    mutating func receivedToken(digest: Data, ticket: Int) {
        guard accepts(ticket) else { return }
        if tokenDigest != digest { tokenChanges += 1; tokenDigest = digest }
        fcm = .succeeded; errorCategory = "none"
    }
}
