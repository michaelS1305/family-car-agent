#if os(iOS)
import CoreLocation
import Foundation
import OSLog
import SwiftUI
import UIKit

@MainActor enum ReturnLocationLog {
    static let logger = Logger(subsystem: "com.familycaragent.app", category: "return_location")
    enum Stage: String { case intentEntered, context, application, authorization, accuracy, acquisitionStarted,
        measurementReceived, validation, coreLocationError, elapsed, timeout, cancellation, cleanupCompleted, result, proceedingToRecord, recorded, recordingFailed }
    // Callers supply only constants, enum raw values or bounded numeric diagnostics, never objects/errors.
    static func emit(_ stage: Stage, _ value: String = "none") {
        logger.notice("FCA_RETURN_LOCATION stage=\(stage.rawValue, privacy: .public) value=\(value, privacy: .public)")
    }
    static func recording(_ progress: ReturnRecordingProgress) {
        logger.notice("FCA_RETURN_LOCATION stage=\(progress.diagnostic.rawValue, privacy: .public)")
    }
    static func authorization(_ status: CLAuthorizationStatus) {
        let value: String
        switch status {
        case .notDetermined: value = "not_determined"
        case .restricted: value = "restricted"
        case .denied: value = "denied"
        case .authorizedAlways: value = "always"
        case .authorizedWhenInUse: value = "when_in_use"
        @unknown default: value = "unknown"
        }
        emit(.authorization, value)
    }
}

// Core Location delivers delegates on the creating thread run loop. Both managers are
// created on MainActor; preconcurrency bridges the legacy nonisolated ObjC protocol
// while retaining runtime actor-isolation checks. Never create these managers off-main.
@MainActor final class ReturnLocationAcquisition: NSObject, @preconcurrency CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private let clock = ContinuousClock()
    private var began: ContinuousClock.Instant?
    private var timer: Task<Void, Never>?
    private var continuation: CheckedContinuation<VehicleLocationEvidence?, Never>?
    private var core: ReturnLocationAcquisitionCore?
    private var candidate: VehicleLocationEvidence?
    private(set) var outcome: ReturnLocationAcquisitionCore.Outcome?

    func acquire() async -> VehicleLocationEvidence? {
        // Instances are deliberately single-use; separate invocations own separate managers.
        guard core == nil else { return nil }
        return await withTaskCancellationHandler {
            await withCheckedContinuation { continuation in
                self.continuation = continuation
                let start = clock.now
                began = start
                let core = ReturnLocationAcquisitionCore(elapsed: { [clock] in start.duration(to: clock.now) },
                    cleanup: { [weak self] in self?.cleanup() },
                    completion: { [weak self] result in self?.complete(result) })
                self.core = core
                if Task.isCancelled { core.cancel(); return }
                manager.delegate = self
                ReturnLocationLog.authorization(manager.authorizationStatus)
                ReturnLocationLog.emit(.accuracy, manager.accuracyAuthorization == .fullAccuracy ? "full" : "reduced")
                let authorization: ReturnLocationAcquisitionCore.Authorization
                switch manager.authorizationStatus {
                case .authorizedWhenInUse, .authorizedAlways: authorization = .allowed
                case .denied, .restricted: authorization = .denied
                default: authorization = .unavailable
                }
                guard CLLocationManager.locationServicesEnabled() else { core.failure(); return }
                guard core.start(authorization) else { return }
                manager.desiredAccuracy = kCLLocationAccuracyBest
                manager.distanceFilter = kCLDistanceFilterNone
                manager.allowsBackgroundLocationUpdates = true
                manager.showsBackgroundLocationIndicator = true
                timer = Task { [weak self, clock] in
                    do { try await clock.sleep(until: start.advanced(by: ReturnLocationAcquisitionCore.limit)) }
                    catch { return }
                    self?.core?.timeout()
                }
                ReturnLocationLog.emit(.acquisitionStarted, "start_updating_location")
                manager.startUpdatingLocation()
            }
        } onCancel: {
            Task { @MainActor [weak self] in self?.core?.cancel() }
        }
    }
    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let core, core.outcome == nil else { return }
        for fix in locations {
            guard core.outcome == nil else { break }
            ReturnLocationLog.emit(.measurementReceived)
            // Only actual Core Location delegate evidence can populate this private candidate.
            candidate = .init(latitude: fix.coordinate.latitude, longitude: fix.coordinate.longitude,
                              accuracy: fix.horizontalAccuracy, measuredAt: fix.timestamp)
            let reason = core.measurement(hasSource: fix.sourceInformation != nil,
                simulated: fix.sourceInformation?.isSimulatedBySoftware == true,
                validCoordinates: CLLocationCoordinate2DIsValid(fix.coordinate),
                accuracy: fix.horizontalAccuracy, age: Date().timeIntervalSince(fix.timestamp))
            if let reason { ReturnLocationLog.emit(.validation, reason.rawValue) }
            else if core.outcome == .acquired { ReturnLocationLog.emit(.validation, "valid") }
        }
    }
    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        guard let core, core.outcome == nil else { return }
        let error = error as NSError
        if error.domain == kCLErrorDomain {
            ReturnLocationLog.emit(.coreLocationError, "kCLErrorDomain_" + String(error.code))
            // Transient inability to obtain a fix can improve within the original deadline.
            if error.code == CLError.Code.locationUnknown.rawValue { return }
        } else { ReturnLocationLog.emit(.coreLocationError, "other_domain") }
        core.failure()
    }
    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        guard let core, core.outcome == nil else { return }
        ReturnLocationLog.authorization(manager.authorizationStatus)
        ReturnLocationLog.emit(.accuracy, manager.accuracyAuthorization == .fullAccuracy ? "full" : "reduced")
        if ![.authorizedWhenInUse, .authorizedAlways].contains(manager.authorizationStatus) { core.failure() }
    }
    private func cleanup() {
        manager.stopUpdatingLocation()
        manager.allowsBackgroundLocationUpdates = false
        manager.delegate = nil
        timer?.cancel(); timer = nil
        ReturnLocationLog.emit(.cleanupCompleted)
    }
    private func complete(_ result: ReturnLocationAcquisitionCore.Outcome) {
        if result == .timedOut { ReturnLocationLog.emit(.timeout) }
        if result == .cancelled { ReturnLocationLog.emit(.cancellation) }
        if let began {
            let d = began.duration(to: clock.now).components
            let milliseconds = max(0, min(300_000, d.seconds * 1000 + d.attoseconds / 1_000_000_000_000_000))
            ReturnLocationLog.emit(.elapsed, String(milliseconds))
        }
        ReturnLocationLog.emit(.result, result.rawValue)
        let saved = continuation; continuation = nil
        outcome = result
        saved?.resume(returning: result == .acquired ? candidate : nil)
        candidate = nil
    }
}

#endif
