#if os(iOS)
import SwiftUI
import UIKit
import UserNotifications
import FirebaseCore
import FirebaseMessaging
import CryptoKit

/// Phase 2A: no Backend registration, delivery claims, or payload routing.
@MainActor final class NativePushService: NSObject, ObservableObject {
    static let shared = NativePushService()
    @Published private(set) var state = NativePushState()
    private var identity: ChatIdentity?
    private var checkingPermission = false
    private var fetchingToken = false
    private var initialized = false

    func configure() {
        guard !initialized else { return }
        initialized = true
        let bundle = Bundle.main
        guard let path = bundle.path(forResource: "GoogleService-Info", ofType: "plist"),
              let data = try? Data(contentsOf: URL(fileURLWithPath: path)),
              let config = (try? PropertyListSerialization.propertyList(from: data, format: nil)) as? [String: Any] else {
            state.errorCategory = "firebase_configuration_unavailable"; return
        }
        state.configurationLoaded = true
        guard bundle.object(forInfoDictionaryKey: "FCAEnvironment") as? String == "development",
              bundle.bundleIdentifier == "XTL-255E706B.com.familycaragent.app.dev",
              bundle.object(forInfoDictionaryKey: "FirebaseAppDelegateProxyEnabled") as? Bool == false,
              bundle.object(forInfoDictionaryKey: "FirebaseMessagingAutoInitEnabled") as? Bool == false,
              config["BUNDLE_ID"] as? String == bundle.bundleIdentifier,
              config["PROJECT_ID"] as? String == "family-car-agent-dev",
              config["GCM_SENDER_ID"] as? String == "452367109329",
              let app = config["GOOGLE_APP_ID"] as? String,
              app.range(of: "^1:452367109329:ios:[0-9a-f]+$", options: .regularExpression) != nil else {
            state.errorCategory = "firebase_dev_configuration"; return
        }
        state.devIdentityValidated = true
        guard let options = FirebaseOptions(contentsOfFile: path) else {
            state.errorCategory = "firebase_options_unavailable"; return
        }
        FirebaseConfiguration.shared.setLoggerLevel(.min)
        guard FirebaseApp.app() == nil else { state.errorCategory = "unexpected_firebase_instance"; return }
        FirebaseApp.configure(options: options)
        Messaging.messaging().isAutoInitEnabled = false
        Messaging.messaging().delegate = self
        UNUserNotificationCenter.current().delegate = self
        state.configured = true
    }

    func authenticatedEntry(_ value: ChatIdentity?) {
        if identity != value {
            invalidate()
            identity = value
            if value != nil { state.activate() }
        }
        guard current(state.epoch) else { return }
        checkPermission()
    }

    func invalidate() {
        let configurationError = state.configured ? "none" : state.errorCategory
        identity = nil; state.deactivate()
        state.errorCategory = configurationError
        checkingPermission = false; fetchingToken = false
        // Firebase's own token is installation-scoped, never associated with an FCA
        // account here. Turn auto-init off; do not race asynchronous token deletion
        // against a subsequent login. No FCA token persistence or Backend upload.
        if state.configured { Messaging.messaging().isAutoInitEnabled = false }
        UIApplication.shared.unregisterForRemoteNotifications()
        UNUserNotificationCenter.current().removeAllDeliveredNotifications()
    }

    private func current(_ ticket: Int) -> Bool {
        guard state.accepts(ticket), let identity,
              let runtime = try? VehicleSessionRuntime.shared.get() else { return false }
        return runtime.sessions.session?.owner == identity.owner
            && runtime.sessions.session?.activated == true
            && runtime.sessions.generation == identity.generation
    }

    private func checkPermission() {
        guard !checkingPermission else { return }
        checkingPermission = true
        let ticket = state.epoch
        Task { @MainActor in
            defer { if state.epoch == ticket { checkingPermission = false } }
            let center = UNUserNotificationCenter.current()
            var settings = await center.notificationSettings()
            guard current(ticket) else { return }
            if settings.authorizationStatus == .notDetermined {
                do { _ = try await center.requestAuthorization(options: [.alert, .badge, .sound]) }
                catch {
                    guard current(ticket) else { return }
                    state.errorCategory = "notification_permission"; return
                }
                settings = await center.notificationSettings()
                guard current(ticket) else { return }
            }
            switch settings.authorizationStatus {
            case .notDetermined: state.permission = .notDetermined
            case .denied: state.permission = .denied
            case .authorized: state.permission = .authorized
            case .provisional: state.permission = .provisional
            case .ephemeral: state.permission = .ephemeral
            @unknown default: state.permission = .unknown
            }
            guard state.permitsRegistration else {
                state.apns = .idle; state.fcm = .idle
                Messaging.messaging().isAutoInitEnabled = false
                UIApplication.shared.unregisterForRemoteNotifications(); return
            }
            state.apns = .waiting
            UIApplication.shared.registerForRemoteNotifications()
        }
    }

    func registeredAPNs(_ token: Data) {
        guard current(state.epoch), state.permitsRegistration else { return }
        Messaging.messaging().setAPNSToken(token, type: .sandbox)
        state.apnsResult(succeeded: true, ticket: state.epoch)
        // Auto-init is persisted by Firebase. Keep it off even while signed in,
        // so a process restart cannot auto-register before session restoration.
        // Explicit token() refresh runs after each authenticated foreground entry.
        fetchToken()
    }
    func failedAPNs() {
        guard current(state.epoch) else { return }
        state.apnsResult(succeeded: false, ticket: state.epoch)
    }
    private func fetchToken() {
        guard current(state.epoch), state.apns == .succeeded, !fetchingToken else { return }
        fetchingToken = true; state.fcm = .waiting
        let ticket = state.epoch
        Task { @MainActor in
            defer { if state.epoch == ticket { fetchingToken = false } }
            do {
                let token = try await Messaging.messaging().token()
                guard current(ticket), state.permitsRegistration, state.apns == .succeeded else { return }
                guard !token.isEmpty else { throw TokenError.empty }
                state.receivedToken(digest: Data(SHA256.hash(data: Data(token.utf8))), ticket: ticket)
            } catch {
                guard current(ticket) else { return }
                state.fcm = .failed; state.errorCategory = "fcm_token"
            }
        }
    }
    private enum TokenError: Error { case empty }
}

extension NativePushService: MessagingDelegate {
    nonisolated func messaging(_ messaging: Messaging, didReceiveRegistrationToken fcmToken: String?) {
        // Re-read SDK state with a current identity ticket; never retain callback tokens.
        Task { @MainActor in self.fetchToken() }
    }
}

extension NativePushService: UNUserNotificationCenterDelegate {
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        // Phase 2A does not associate incoming payloads with an authenticated account.
        // Do not show unverified account content in the foreground.
        completionHandler([])
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse, withCompletionHandler completionHandler: @escaping () -> Void) {
        // System may open the app; payloads never authorize protected navigation.
        completionHandler()
    }
}

#if DEBUG
struct NativePushDiagnosticControl: ViewModifier {
    @ObservedObject private var push = NativePushService.shared
    @State private var shown = false
    let enabled: Bool
    func body(content: Content) -> some View {
        content.overlay(alignment: .topLeading) {
            if enabled { Button("Push DEBUG") { shown = true }.font(.caption2).padding(6) }
        }.sheet(isPresented: $shown) {
            NavigationStack {
                List {
                    Text("Phase 2A — no Backend registration or delivery verification")
                    Text("Configuration loaded: \(push.state.configurationLoaded ? "yes" : "no")")
                    Text("Dev identity validated: \(push.state.devIdentityValidated ? "yes" : "no")")
                    Text("Firebase initialized: \(push.state.configured ? "yes" : "no")")
                    Text("Permission: \(push.state.permission.rawValue)")
                    Text("APNs token: \(push.state.apns.rawValue)")
                    Text("FCM token: \(push.state.fcm.rawValue)")
                    Text("Token changes: \(push.state.tokenChanges)")
                    Text("Error category: \(push.state.errorCategory)")
                }.navigationTitle("Push DEBUG")
                    .toolbar { Button("סגירה") { shown = false } }
            }
        }.onChange(of: enabled) { _, value in if !value { shown = false } }
    }
}
#endif
#endif
