import Foundation

@MainActor final class Harness {
    var time: Duration = .zero
    var cleanups = 0
    var results: [ReturnLocationAcquisitionCore.Outcome] = []
    lazy var core = ReturnLocationAcquisitionCore(elapsed: { self.time },
        cleanup: { self.cleanups += 1 }, completion: { self.results.append($0) })
    func sample(accuracy: Double = 10, age: Double = 0, simulated: Bool = false,
                source: Bool = true, coordinates: Bool = true) -> ReturnLocationReason? {
        core.measurement(hasSource: source, simulated: simulated, validCoordinates: coordinates,
                         accuracy: accuracy, age: age)
    }
    func terminal(_ outcome: ReturnLocationAcquisitionCore.Outcome) {
        precondition(results == [outcome] && cleanups == 1)
        _ = sample(); core.failure(); core.cancel(); time = .seconds(20); core.timeout()
        precondition(results == [outcome] && cleanups == 1, "Late callbacks must be inert")
    }
}
@main struct NativeReturnLocationChecks {
    @MainActor static func main() {
        var permissionChecks = 0
        for _ in ["notification_granted", "notification_denied"] {
            var permission = LocationPermissionGate()
            precondition(!permission.shouldRequest(active: true, notDetermined: true))
            permission.notificationsFinished()
            precondition(!permission.shouldRequest(active: false, notDetermined: true))
            precondition(permission.shouldRequest(active: true, notDetermined: true))
            precondition(!permission.shouldRequest(active: true, notDetermined: true))
            permission.notificationsFinished()
            precondition(!permission.shouldRequest(active: true, notDetermined: true))
            permissionChecks += 1
        }
        for _ in ["granted", "denied", "restricted"] {
            var existing = LocationPermissionGate()
            existing.notificationsFinished()
            precondition(!existing.shouldRequest(active: true, notDetermined: false))
            precondition(!existing.shouldRequest(active: false, notDetermined: false))
            permissionChecks += 1
        }
        var existingInstallation = LocationPermissionGate()
        existingInstallation.notificationsFinished()
        precondition(existingInstallation.shouldRequest(active: true, notDetermined: true))
        permissionChecks += 1
        print("PASS: \(permissionChecks) permission sequencing scenarios")
        enum NotificationError: Error { case failed }
        var errored = LocationPermissionGate()
        do {
            defer { errored.notificationsFinished() }
            throw NotificationError.failed
        } catch NotificationError.failed { } catch { preconditionFailure() }
        precondition(!errored.shouldRequest(active: false, notDetermined: true))
        precondition(errored.shouldRequest(active: true, notDetermined: true))
        precondition(!errored.shouldRequest(active: true, notDetermined: true))
        var recording = ReturnRecordingProgress()
        precondition(recording.diagnostic == .failedBeforeCommit)
        recording.didCommit()
        precondition(recording.diagnostic == .persistedOutcome)
        recording.didFinishProcessing()
        precondition(recording.diagnostic == .stored)
        for _ in ["recovery_expired", "reconciliation_conflict", "retry_stored"] {
            var persisted = ReturnRecordingProgress()
            persisted.didCommit()
            precondition(persisted.diagnostic == .persistedOutcome)
        }
        print("PASS: notification error/inactive/duplicate sequencing and 6 recording diagnostic cases")
        var count = 0
        func check(_ body: (Harness) -> Void) { body(Harness()); count += 1 }
        check { h in precondition(h.core.start(.allowed)); precondition(h.sample() == nil); h.terminal(.acquired) }
        for accuracy in [0.0, -1, 100.001, Double.nan, Double.infinity] {
            check { h in _ = h.core.start(.allowed); precondition(h.sample(accuracy: accuracy) == .accuracy)
                precondition(h.results.isEmpty); _ = h.sample(); h.terminal(.acquired) }
        }
        for (age, reason) in [(30.001, ReturnLocationReason.stale), (-0.001, .future), (Double.infinity, .stale)] {
            check { h in _ = h.core.start(.allowed); precondition(h.sample(age: age) == reason)
                precondition(h.results.isEmpty); h.core.cancel(); h.terminal(.cancelled) }
        }
        check { h in _ = h.core.start(.allowed); precondition(h.sample(accuracy: 100, age: 30) == nil); h.terminal(.acquired) }
        check { h in _ = h.core.start(.allowed); precondition(h.sample(simulated: true) == .simulated)
            precondition(h.results.isEmpty); h.core.failure(); h.terminal(.failed) }
        check { h in _ = h.core.start(.allowed); precondition(h.sample(source: false) == nil); h.terminal(.acquired) }
        check { h in _ = h.core.start(.allowed); precondition(h.sample(coordinates: false) == .coordinates)
            h.core.cancel(); h.terminal(.cancelled) }
        check { h in precondition(!h.core.start(.denied)); h.terminal(.unauthorized) }
        check { h in precondition(!h.core.start(.unavailable)); h.terminal(.unavailable) }
        // Reduced authorization does not change numeric policy or prompt for full accuracy.
        check { h in _ = h.core.start(.allowed); precondition(h.sample(accuracy: 5000) == .accuracy)
            h.time = .seconds(15); h.core.timeout(); h.terminal(.timedOut) }
        check { h in _ = h.core.start(.allowed); h.time = .seconds(14); h.core.timeout()
            precondition(h.results.isEmpty); h.time = .seconds(15); h.core.timeout(); h.terminal(.timedOut) }
        check { h in _ = h.core.start(.allowed); h.time = .seconds(15); _ = h.sample(); h.terminal(.timedOut) }
        check { h in h.core.cancel(); precondition(!h.core.start(.allowed)); h.terminal(.cancelled) }
        check { h in _ = h.core.start(.allowed); h.core.cancel(); h.terminal(.cancelled) }
        check { h in _ = h.core.start(.allowed); h.core.failure(); h.terminal(.failed) }
        check { h in _ = h.core.start(.allowed); precondition(!h.core.start(.allowed))
            _ = h.sample(accuracy: 150); _ = h.sample(accuracy: 101); _ = h.sample(); h.terminal(.acquired) }
        check { h in h.time = .seconds(16); precondition(!h.core.start(.allowed)); h.terminal(.timedOut) }
        print("Native RETURN acquisition: \(count) lifecycle/validation scenarios passed")
    }
}
