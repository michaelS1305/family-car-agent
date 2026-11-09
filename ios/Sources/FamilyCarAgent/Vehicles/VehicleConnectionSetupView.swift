import SwiftUI

/// Presentation only: runtime owns registration, binding and durable authorization.
struct VehicleConnectionSetupView: View {
    let identity: ChatIdentity
    let vehicle: UUID
    let name: String
    let close: () -> Void
    @Environment(\.scenePhase) private var scenePhase
    @State private var presentation = VehicleConnectionPresentation()
    @State private var busy = false
    @State private var message: String?
    @State private var operation: Task<Void, Never>?
    @State private var revision = 0

    var body: some View {
        #if DEBUG
        VStack(spacing: 0) {
            header
            ScrollView {
                VStack(spacing: 22) {
                    Text("חיבור וזיהוי אוטומטי").font(.largeTitle.bold()).multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true).accessibilityAddTraits(.isHeader)
                    if presentation.screen == .loading { ProgressView("בודקים את מצב החיבור…") }
                    else if presentation.screen == .selection { selection }
                    else { setup }
                }.padding(.horizontal, 20).padding(.top, 24).padding(.bottom, 28)
                    .frame(maxWidth: 620).frame(maxWidth: .infinity)
            }
        }.modifier(VehiclesAppearance())
        .task(id: scenePhase) {
            guard scenePhase == .active else { return }
            // Local reads only: reflect background rejection/logout without starting server verification.
            while !Task.isCancelled {
                if !busy { await restore() }
                do { try await Task.sleep(for: .seconds(2)) } catch { return }
            }
        }
        .onDisappear { revision += 1; operation?.cancel() }
        #else
        VStack {
            Text("הגדרת קיצורי הרכב זמינה כעת בגרסת Dev DEBUG בלבד.")
            Button("סגירה") { close() }
        }.modifier(VehiclesAppearance())
        #endif
    }
    private var header: some View {
        HStack(spacing: 6) {
            Button { revision += 1; operation?.cancel(); close() } label: {
                Image(systemName: "xmark").font(.title2).frame(width: 44, height: 44)
                    .background(.white.opacity(0.85), in: Circle())
            }.buttonStyle(.plain).accessibilityLabel("סגירה")
            AppAssetImage(path: ChatStyle.wordmark).frame(maxWidth: 240).frame(height: 62)
                .blendMode(.multiply).accessibilityHidden(true)
            Group {
                if presentation.canGoBack {
                    Button { presentation.back(); message = nil } label: {
                        Image(systemName: "chevron.right").font(.title2).frame(width: 44, height: 44)
                    }.buttonStyle(.plain).disabled(busy).accessibilityLabel("חזרה לבחירת אופן החיבור")
                } else { Color.clear.frame(width: 44, height: 44) }
            }
        }.frame(maxWidth: .infinity).padding(.horizontal, 16).padding(.vertical, 8)
    }
    private var selection: some View {
        VStack(spacing: 24) {
            Text("בחרו איך האייפון שלכם מתחבר לרכב כדי שנכין לכם את ההגדרה המתאימה.")
                .font(.title3).foregroundStyle(ChatStyle.secondary).multilineTextAlignment(.center)
            Text("ברכב הזה אני משתמש עם:").font(.title3.bold()).padding(.top, 12)
            methodCard(.carPlay, title: "CarPlay")
            HStack(spacing: 20) { Rectangle().frame(height: 1); Text("או").font(.title3); Rectangle().frame(height: 1) }
                .foregroundStyle(ChatStyle.secondary.opacity(0.6)).padding(.horizontal, 34)
            methodCard(.bluetooth, title: "Bluetooth")
        }
    }
    private func methodCard(_ method: VehicleConnectionMethod, title: String) -> some View {
        Button { presentation.choose(method) } label: {
            ZStack(alignment: .leading) {
                Image(systemName: "chevron.right").font(.title2).padding(.leading, 6)
                VStack(spacing: 8) {
                    if method == .carPlay {
                        // No CarPlay asset exists in the bundle.
                        Image(systemName: "car.fill").font(.system(size: 32)).foregroundStyle(.white)
                            .frame(width: 54, height: 54).background(Color.green, in: RoundedRectangle(cornerRadius: 14))
                    } else {
                        AppAssetImage(path: "icons/archive/bluetooth_icon.png").frame(width: 60, height: 60)
                    }
                    Text(title).font(.title2.bold())
                }.frame(maxWidth: .infinity).padding(.vertical, 6)
            }.padding(18).frame(maxWidth: .infinity, minHeight: 130)
                .background(.white.opacity(0.8), in: RoundedRectangle(cornerRadius: 22))
                .overlay(RoundedRectangle(cornerRadius: 22).stroke(ChatStyle.border))
                .shadow(color: .black.opacity(0.04), radius: 10, y: 5)
        }.buttonStyle(.plain).accessibilityLabel("בחירת " + title)
    }
    private var setup: some View {
        VStack(spacing: 16) {
            Text("כדי שהזיהוי יעבוד, צריך לחבר את המכשיר ולהגדיר את הקיצורים המתאימים.")
                .font(.title3).foregroundStyle(ChatStyle.secondary).multilineTextAlignment(.center)
            deviceCard
            if let message { Text(message).font(.callout).foregroundStyle(ChatStyle.secondary).frame(maxWidth: .infinity, alignment: .leading) }
            if presentation.showsShortcuts {
                shortcutCard(title: "הגדרת חיבור", description: "הקיצור שיופעל כשמתחברים לרכב.")
                shortcutCard(title: "הגדרת ניתוק", description: presentation.method == .bluetooth
                    ? "קיצור להחזרת הרכב. ניתוק Bluetooth אינו מוגדר אוטומטית."
                    : "הקיצור להחזרת הרכב כשמתנתקים ממנו.")
            }
            Button { perform(refreshOnly: true) } label: {
                Text("רענון").font(.title3).foregroundStyle(Color.blue).frame(minWidth: 80, minHeight: 44)
            }.buttonStyle(.plain).disabled(busy)
        }
    }
    private var deviceCard: some View {
        panel {
            HStack(alignment: .top, spacing: 12) {
                AppAssetImage(path: "icons/archive/phone_icon.png").frame(width: 52, height: 60).accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 6) {
                    Text("המכשיר הזה").font(.title2.bold()).accessibilityAddTraits(.isHeader)
                    HStack(spacing: 8) {
                        if presentation.authorization.isAuthorized {
                            Image(systemName: "checkmark.circle.fill").foregroundStyle(.green).accessibilityHidden(true)
                        }
                        Text(status).font(.title3).foregroundStyle(ChatStyle.secondary)
                    }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }
            Text(presentation.authorization.isAuthorized ? "המכשיר מחובר לזיהוי אוטומטי ברכב הזה." : "חיבור המכשיר ושיוכו לרכב הזה לזיהוי אוטומטי.")
                .foregroundStyle(ChatStyle.secondary).frame(maxWidth: .infinity, alignment: .leading)
            if !presentation.authorization.isAuthorized {
                Button { perform(refreshOnly: !presentation.showsActivation) } label: {
                    HStack(spacing: 8) {
                        if busy { ProgressView().tint(.white) }
                        Text(busy ? "מאמתים את החיבור…" : presentation.showsActivation ? "חיבור המכשיר" : "אימות החיבור")
                            .font(.headline).multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
                    }.foregroundStyle(.white).padding(.horizontal, 12).padding(.vertical, 14)
                        .frame(maxWidth: .infinity, minHeight: 50)
                        .background(ChatStyle.ink.opacity(busy ? 0.55 : 1), in: RoundedRectangle(cornerRadius: 14))
                }.buttonStyle(.plain).disabled(busy)
            }
        }
    }
    private func shortcutCard(title: String, description: String) -> some View {
        panel {
            HStack(alignment: .top, spacing: 12) {
                AppAssetImage(path: "icons/archive/single_car_icon.png").frame(width: 64, height: 64).accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 6) {
                    Text(title).font(.title2.bold()).accessibilityAddTraits(.isHeader)
                    Text("הוספה מתוך האפליקציה עדיין אינה זמינה").font(.callout).foregroundStyle(ChatStyle.secondary)
                }.frame(maxWidth: .infinity, alignment: .leading)
            }
            Text(description).foregroundStyle(ChatStyle.secondary).frame(maxWidth: .infinity, alignment: .leading)
            // Phase 1: no URL, import, automation state or simulated completion.
            Button {} label: {
                Text("הוספת קיצור").font(.headline).foregroundStyle(ChatStyle.secondary)
                    .padding(12).frame(maxWidth: .infinity, minHeight: 48)
                    .overlay(RoundedRectangle(cornerRadius: 12).stroke(ChatStyle.border))
            }.buttonStyle(.plain).disabled(true).accessibilityHint("האפשרות עדיין אינה זמינה")
        }
    }
    private func panel<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 14, content: content).padding(16).frame(maxWidth: .infinity, alignment: .leading)
            .background(.white.opacity(0.8), in: RoundedRectangle(cornerRadius: 22))
            .overlay(RoundedRectangle(cornerRadius: 22).stroke(ChatStyle.border))
            .shadow(color: .black.opacity(0.04), radius: 10, y: 5)
    }
    private var status: String {
        switch presentation.authorization {
        case .authorized: "מחובר"
        case .inactive, .bindingRemoved: "לא מחובר לרכב הזה"
        case .verificationPending: "ממתין לאימות"
        case .temporarilyUnavailable: "לא ניתן לאמת כרגע"
        case .verificationRequired: "נדרש אימות מחדש"
        case .recoveryRequired: "נדרשת התאוששות"
        }
    }
    @MainActor private func restore(afterFailure: Bool = false) async {
        let expected = revision
        do {
            let runtime = try VehicleSessionRuntime.shared.get()
            let method = try runtime.savedConnection(identity: identity, vehicle: vehicle)
            var state = try await runtime.connectionState(identity: identity, vehicle: vehicle)
            guard !Task.isCancelled, expected == revision else { return }
            if afterFailure || presentation.authorization == .temporarilyUnavailable { state = state.afterVerificationFailure() }
            presentation.restore(method: method, authorization: state)
        } catch {
            guard !Task.isCancelled, expected == revision else { return }
            presentation.unavailable(); show(error)
        }
    }
    private func perform(refreshOnly: Bool) {
        guard !busy else { return }
        let method = presentation.method
        let activate = !refreshOnly && presentation.showsActivation
        revision += 1; busy = true; message = nil; presentation.verifying()
        operation = Task { @MainActor in
            defer { busy = false }
            do {
                let runtime = try VehicleSessionRuntime.shared.get()
                if activate, let method { try await runtime.activateConnection(identity: identity, vehicle: vehicle, method: method) }
                else { _ = try await runtime.refreshConnection(identity: identity, vehicle: vehicle) }
                try Task.checkCancellation()
                await restore()
            } catch {
                guard !Task.isCancelled else { return }
                await restore(afterFailure: true); show(error)
            }
        }
    }
    private func show(_ error: Error) {
        switch error {
        case NativeDeviceSetupError.busy: message = "מתבצע אימות נוסף. נסו שוב בעוד רגע."
        case NativeDeviceSetupError.unavailable: message = "המכשיר או השיוך אינם מורשים עוד. נדרשת בדיקת ההרשאות."
        case NativeDeviceSetupError.recoveryRequired, is VehicleQueueError:
            message = "נדרשת התאוששות של זהות המכשיר או התור. הנתונים נשמרו ולא בוצע איפוס."
        case AuthFailure.network: message = "לא ניתן להשלים את האימות כעת. בדקו את החיבור ונסו שוב; זהות הרישום נשמרה."
        case AuthFailure.rejected(403, _): message = "אין הרשאה לבצע את השיוך. חזרו למסך הרכב ורעננו הרשאות."
        default: message = "לא ניתן להשלים את ההגדרה. חזרו למסך הרכב ונסו שוב."
        }
    }
}
