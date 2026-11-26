#if os(iOS)
import CoreLocation
import UIKit
import SwiftUI

/// Permission management never starts measurements. Acquisition is owned by each RETURN.
@MainActor final class LocationPermissionService: NSObject, ObservableObject, @preconcurrency CLLocationManagerDelegate {
    static let shared = LocationPermissionService()
    private let manager = CLLocationManager()
    private var gate = LocationPermissionGate()
    @Published private(set) var ready = false
    @Published private(set) var detail = "הרשאת מיקום טרם ניתנה"
    override init() {
        super.init()
        manager.delegate = self
        NotificationCenter.default.addObserver(self, selector: #selector(active), name: UIApplication.didBecomeActiveNotification, object: nil)
        refresh()
    }
    func notificationsFinished() {
        gate.notificationsFinished()
        refreshAndRequest()
    }
    @objc private func active() { refreshAndRequest() }
    private func refreshAndRequest() {
        refresh()
        if gate.shouldRequest(active: UIApplication.shared.applicationState == .active,
                              notDetermined: manager.authorizationStatus == .notDetermined) {
            manager.requestWhenInUseAuthorization()
        }
    }
    func refresh() {
        let authorized = [.authorizedWhenInUse, .authorizedAlways].contains(manager.authorizationStatus)
        let enabled = CLLocationManager.locationServicesEnabled()
        ready = enabled && authorized && manager.accuracyAuthorization == .fullAccuracy
        if !enabled { detail = "שירותי המיקום כבויים" }
        else if authorized { detail = manager.accuracyAuthorization == .fullAccuracy ? "מיקום מדויק מאושר" : "מיקום משוער — יש להפעיל מיקום מדויק להחזרה אוטומטית" }
        else {
            switch manager.authorizationStatus {
            case .denied: detail = "הרשאת המיקום נדחתה"
            case .restricted: detail = "הרשאת המיקום מוגבלת במכשיר"
            default: detail = "הרשאת מיקום טרם ניתנה"
            }
        }
    }
    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) { refresh() }
}
#endif
