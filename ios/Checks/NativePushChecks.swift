import Foundation

@main enum NativePushChecks {
    static func main() {
        var state = NativePushState()
        assert(!state.accepts(0))
        state.configured = true
        state.activate()
        let old = state.epoch
        for permission in [NativePushState.Permission.unknown, .notDetermined, .denied] {
            state.permission = permission; assert(!state.permitsRegistration)
        }
        for permission in [NativePushState.Permission.authorized, .provisional, .ephemeral] {
            state.permission = permission; assert(state.permitsRegistration)
        }
        state.apnsResult(succeeded: false, ticket: old)
        assert(state.apns == .failed && state.errorCategory == "apns_registration")
        state.apnsResult(succeeded: true, ticket: old)
        assert(state.apns == .succeeded && state.errorCategory == "none")
        state.receivedToken(digest: Data([1]), ticket: old)
        state.receivedToken(digest: Data([1]), ticket: old)
        assert(state.tokenChanges == 1 && state.fcm == .succeeded)
        state.receivedToken(digest: Data([2]), ticket: old)
        assert(state.tokenChanges == 2)
        state.deactivate()
        assert(!state.accepts(old) && state.tokenChanges == 0 && state.fcm == .idle)
        state.activate()
        state.apnsResult(succeeded: true, ticket: old)
        assert(state.apns == .idle)
        state.receivedToken(digest: Data([3]), ticket: old)
        assert(state.fcm == .idle && state.tokenChanges == 0)
        assert(state.accepts(state.epoch))
        print("Native Push state checks passed (mock lifecycle; no APNs/FCM network)")
    }
}
