#if DEBUG && !FCA_PRODUCTION && os(iOS)
import AppIntents
import CoreLocation
import Foundation
import OSLog
import SwiftUI
import UIKit

@MainActor private enum NativeLocationPOCLog {
    static let logger = Logger(subsystem: "com.familycaragent.app.dev", category: "native_location_poc")
    enum Stage: String { case intentEntered, context, application, authorization, accuracy, acquisitionStarted,
        measurementReceived, validation, coreLocationError, elapsed, timeout, cancellation, cleanupCompleted, result }
    // Callers supply only constants, enum raw values or bounded numeric diagnostics, never objects/errors.
    static func emit(_ stage: Stage, _ value: String = "none") {
        logger.notice("FCA_NATIVE_LOCATION_POC stage=\(stage.rawValue, privacy: .public) value=\(value, privacy: .public)")
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
@MainActor final class NativeLocationPOCAcquisition: NSObject, @preconcurrency CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private let clock = ContinuousClock()
    private var began: ContinuousClock.Instant?
    private var timer: Task<Void, Never>?
    private var continuation: CheckedContinuation<NativeLocationPOCCore.Outcome, Never>?
    private var core: NativeLocationPOCCore?

    func acquire() async -> NativeLocationPOCCore.Outcome {
        // Instances are deliberately single-use; separate invocations own separate managers.
        guard core == nil else { return .failed }
        return await withTaskCancellationHandler {
            await withCheckedContinuation { continuation in
                self.continuation = continuation
                let start = clock.now
                began = start
                let core = NativeLocationPOCCore(elapsed: { [clock] in start.duration(to: clock.now) },
                    cleanup: { [weak self] in self?.cleanup() },
                    completion: { [weak self] result in self?.complete(result) })
                self.core = core
                if Task.isCancelled { core.cancel(); return }
                manager.delegate = self
                NativeLocationPOCLog.authorization(manager.authorizationStatus)
                NativeLocationPOCLog.emit(.accuracy, manager.accuracyAuthorization == .fullAccuracy ? "full" : "reduced")
                let authorization: NativeLocationPOCCore.Authorization
                switch manager.authorizationStatus {
                case .authorizedWhenInUse, .authorizedAlways: authorization = .allowed
                case .denied, .restricted: authorization = .denied
                default: authorization = .unavailable
                }
                guard core.start(authorization) else { return }
                manager.desiredAccuracy = kCLLocationAccuracyBest
                manager.distanceFilter = kCLDistanceFilterNone
                manager.allowsBackgroundLocationUpdates = true
                manager.showsBackgroundLocationIndicator = true
                timer = Task { [weak self, clock] in
                    do { try await clock.sleep(until: start.advanced(by: NativeLocationPOCCore.limit)) }
                    catch { return }
                    self?.core?.timeout()
                }
                NativeLocationPOCLog.emit(.acquisitionStarted, "start_updating_location")
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
            NativeLocationPOCLog.emit(.measurementReceived)
            let reason = core.measurement(hasSource: fix.sourceInformation != nil,
                simulated: fix.sourceInformation?.isSimulatedBySoftware == true,
                validCoordinates: CLLocationCoordinate2DIsValid(fix.coordinate),
                accuracy: fix.horizontalAccuracy, age: Date().timeIntervalSince(fix.timestamp))
            if let reason { NativeLocationPOCLog.emit(.validation, reason.rawValue) }
            else if core.outcome == .acquired { NativeLocationPOCLog.emit(.validation, "valid") }
        }
    }
    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        guard let core, core.outcome == nil else { return }
        let error = error as NSError
        if error.domain == kCLErrorDomain {
            NativeLocationPOCLog.emit(.coreLocationError, "kCLErrorDomain_" + String(error.code))
            // Transient inability to obtain a fix can improve within the original deadline.
            if error.code == CLError.Code.locationUnknown.rawValue { return }
        } else { NativeLocationPOCLog.emit(.coreLocationError, "other_domain") }
        core.failure()
    }
    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        guard let core, core.outcome == nil else { return }
        NativeLocationPOCLog.authorization(manager.authorizationStatus)
        NativeLocationPOCLog.emit(.accuracy, manager.accuracyAuthorization == .fullAccuracy ? "full" : "reduced")
        if ![.authorizedWhenInUse, .authorizedAlways].contains(manager.authorizationStatus) { core.failure() }
    }
    private func cleanup() {
        manager.stopUpdatingLocation()
        manager.allowsBackgroundLocationUpdates = false
        manager.delegate = nil
        timer?.cancel(); timer = nil
        NativeLocationPOCLog.emit(.cleanupCompleted)
    }
    private func complete(_ result: NativeLocationPOCCore.Outcome) {
        if result == .timedOut { NativeLocationPOCLog.emit(.timeout) }
        if result == .cancelled { NativeLocationPOCLog.emit(.cancellation) }
        if let began {
            let d = began.duration(to: clock.now).components
            let milliseconds = max(0, min(300_000, d.seconds * 1000 + d.attoseconds / 1_000_000_000_000_000))
            NativeLocationPOCLog.emit(.elapsed, String(milliseconds))
        }
        NativeLocationPOCLog.emit(.result, result.rawValue)
        let saved = continuation; continuation = nil
        saved?.resume(returning: result)
    }
}

/// Foreground user action only. It never starts location updates or reads manager.location.
@MainActor private final class NativeLocationPOCPermission: NSObject, ObservableObject, @preconcurrency CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    @Published var message = "ניסוי Development בלבד: הרשאת מיקום לבדיקה נקודתית."
    override init() { super.init(); manager.delegate = self }
    func request() {
        guard UIApplication.shared.applicationState == .active else { return }
        if manager.authorizationStatus == .notDetermined { manager.requestWhenInUseAuthorization() }
        else { message = "ההרשאה כבר נקבעה. אפשר לבדוק אותה בהגדרות iOS; לא הופעלה מדידת מיקום." }
    }
    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        NativeLocationPOCLog.authorization(manager.authorizationStatus)
        message = "לא הופעלה מדידה. הפעילו בנפרד את קיצור האבחון לאחר בדיקת ההרשאה."
    }
}

struct NativeLocationPOCPermissionView: View {
    @StateObject private var permission = NativeLocationPOCPermission()
    var body: some View {
        VStack(spacing: 8) {
            Text(permission.message).font(.caption)
            Button("Development: בקשת הרשאת מיקום לניסוי") { permission.request() }
                .buttonStyle(.bordered).frame(minHeight: 44)
        }
    }
}

struct FCANativeLocationPOCIntent: AppIntent {
    static let title: LocalizedStringResource = "FCA Dev — Native Location POC"
    static let openAppWhenRun = false
    // Same default authenticationPolicy as RETURN. No parameter resolution or queue access.
    @MainActor func perform() async throws -> some IntentResult & ReturnsValue<String> {
        NativeLocationPOCLog.emit(.intentEntered)
        if #available(iOS 26.0, *) {
            NativeLocationPOCLog.emit(.context, systemContext.currentMode == .background ? "background" : "foreground")
        } else { NativeLocationPOCLog.emit(.context, "unavailable") }
        switch UIApplication.shared.applicationState {
        case .active: NativeLocationPOCLog.emit(.application, "active")
        case .inactive: NativeLocationPOCLog.emit(.application, "inactive")
        case .background: NativeLocationPOCLog.emit(.application, "background")
        @unknown default: NativeLocationPOCLog.emit(.application, "unknown")
        }
        let acquisition = NativeLocationPOCAcquisition()
        let result = await acquisition.acquire()
        let message: String
        switch result {
        case .acquired: message = "ניסוי בלבד: התקבלה מדידת מיקום תקפה. לא נרשם אירוע רכב."
        case .unauthorized, .unavailable: message = "ניסוי בלבד: אין הרשאת מיקום זמינה ל־FCA. לא נרשם אירוע."
        case .timedOut: message = "ניסוי בלבד: לא התקבלה מדידה תקפה בתוך 15 שניות. לא נרשם אירוע."
        case .cancelled: message = "ניסוי המיקום בוטל. לא נרשם אירוע."
        case .failed: message = "ניסוי המיקום נכשל. בדקו את לוג האבחון. לא נרשם אירוע."
        }
        return .result(value: message)
    }
}
#endif
