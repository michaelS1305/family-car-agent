import SwiftUI

/// The existing Vehicle Details connection sheet; no automation is created or inspected by FCA.
struct VehicleConnectionSetupView: View {
    let identity: ChatIdentity
    let vehicle: UUID
    let name: String
    @State private var method = VehicleConnectionMethod.carPlay
    @State private var saved = false
    @State private var authorization = VehicleConnectionAuthorizationState.recoveryRequired
    @State private var busy = false
    @State private var message: String?
    @State private var operation: Task<Void, Never>?

    var body: some View {
        #if DEBUG
        VStack(alignment: .leading, spacing: 14) {
            Text(name).fontWeight(.bold)
            Picker("אופן החיבור לרכב", selection: Binding(get: { method }, set: selectMethod)) {
                Text("CarPlay").tag(VehicleConnectionMethod.carPlay)
                Text("Bluetooth").tag(VehicleConnectionMethod.bluetooth)
            }.pickerStyle(.segmented).disabled(busy)
            Text(method == .carPlay
                 ? "מומלץ לרכב עם CarPlay קווי או אלחוטי."
                 : "לרכב עם Bluetooth רגיל, ללא CarPlay. החזרת הרכב אינה מוגדרת אוטומטית.")
            Text(authorizationText)
            if let message { Text(message).foregroundStyle(.secondary) }
            Button(action: activate) {
                HStack {
                    if busy { ProgressView() }
                    Text(busy ? "מאמתים ומשייכים…" : authorization.permitsActivation ? "אישור והפעלת הזיהוי לרכב זה" : "אימות ורענון ההרשאה")
                }.frame(maxWidth: .infinity, minHeight: 50)
            }.buttonStyle(.borderedProminent).tint(ChatStyle.ink).disabled(busy)
            if authorization.isAuthorized { instructions }
        }
        .task {
            do {
                let runtime = try VehicleSessionRuntime.shared.get()
                if let value = try runtime.savedConnection(identity: identity, vehicle: vehicle) { method = value; saved = true }
                let state = try await runtime.connectionState(identity: identity, vehicle: vehicle)
                if !busy { authorization = state }
            } catch { show(error) }
        }
        .onDisappear { operation?.cancel() }
        #else
        Text("הגדרת קיצורי הרכב זמינה כעת בגרסת Dev DEBUG בלבד.")
        #endif
    }

    private var instructions: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("הגדרת הקיצורים — נדרשת פעולה שלך").fontWeight(.bold)
            Text("FCA אינה יכולה לדעת אם האוטומציות נוצרו. יש לבחור ברכב \(name) בכל אחת מפעולות FCA.")
            if method == .carPlay {
                Text("בחיבור: Shortcuts ← Automation ← CarPlay ← Connects ← Run Immediately. הוסיפו FCA — Take Vehicle ובחרו ברכב הזה.")
                Text("בניתוק: צרו אוטומציית CarPlay נוספת עם Disconnects ו־Run Immediately.")
            } else {
                Text("בחיבור: Shortcuts ← Automation ← Bluetooth. בחרו את התקן ה־Bluetooth של הרכב ו־Run Immediately. הוסיפו FCA — Take Vehicle ובחרו ברכב הזה.")
                Text("אין כאן הסתמכות על טריגר ניתוק Bluetooth. להחזרה, צרו קיצור רגיל והפעילו אותו ידנית בעת החזרת הרכב. החזרה אוטומטית דורשת טריגר נתמך נפרד.")
            }
            Text("להחזרה, הוסיפו לפי הסדר:\n1. Get Current Location\n2. FCA — Return Vehicle\nבחרו ברכב הזה והעבירו את פלט המיקום לפקודת Current Location.")
            Text("נדרשת מדידת מיקום אמיתית, בדיוק עד 100 מטר ובגיל עד 30 שניות. כתובת או נקודה שנבחרה במפה אינן תחליף. אם אין מדידה תקינה, ההחזרה לא תירשם.")
            Text("בדקו את שתי הפעולות. הצלחת השיוך אינה מוכיחה שהאוטומציה הוגדרה או שהאירוע התקבל בשרת.")
        }
    }
    private func selectMethod(_ value: VehicleConnectionMethod) {
        do {
            if saved { try VehicleSessionRuntime.shared.get().changeConnection(identity: identity, vehicle: vehicle, method: value) }
            method = value
        } catch {
            show(error)
            if let persisted = try? VehicleSessionRuntime.shared.get().savedConnection(identity: identity, vehicle: vehicle) {
                method = persisted
            } else { authorization = .recoveryRequired }
        }
    }

    private var authorizationText: String {
        switch authorization {
        case .authorized: return "הרכב מורשה במכשיר. נותר להגדיר קיצורים באפליקציית Shortcuts."
        case .verificationPending: return "אימות ההרשאה ממתין להשלמה. פעולות הרכב חסומות בינתיים."
        case .temporarilyUnavailable: return "לא ניתן לאמת כרגע. פעולות הרכב חסומות עד לרענון מוצלח."
        case .bindingRemoved: return "השיוך אינו פעיל. להפעלה מחדש נדרש אישור מפורש."
        case .verificationRequired: return "נדרש אימות שרת לפני הפעלת פעולות הרכב."
        case .recoveryRequired: return "נדרשת בדיקת מצב ההרשאה או התאוששות. פעולות הרכב אינן מוצגות כפעילות."
        case .inactive: return "הזיהוי אינו מופעל עבור רכב זה במכשיר."
        }
    }
    private func activate() {
        guard !busy else { return }
        let activateBinding = authorization.permitsActivation
        busy = true; message = nil; authorization = .verificationPending
        operation = Task { @MainActor in
            defer { busy = false }
            do {
                let runtime = try VehicleSessionRuntime.shared.get()
                if activateBinding {
                    try await runtime.activateConnection(identity: identity, vehicle: vehicle, method: method)
                    saved = true
                } else {
                    _ = try await runtime.refreshConnection(identity: identity, vehicle: vehicle)
                }
                try Task.checkCancellation()
                authorization = try await runtime.connectionState(identity: identity, vehicle: vehicle)
            } catch {
                guard !Task.isCancelled else { return }
                do {
                    let runtime = try VehicleSessionRuntime.shared.get()
                    authorization = try await runtime.connectionState(identity: identity, vehicle: vehicle).afterVerificationFailure()
                } catch { authorization = .recoveryRequired }
                show(error)
            }
        }
    }
    private func show(_ error: Error) {
        switch error {
        case NativeDeviceSetupError.busy: message = "מתבצע אימות נוסף. נסו שוב בעוד רגע."
        case NativeDeviceSetupError.unavailable:
            message = "המכשיר או השיוך אינם מורשים עוד. נדרשת בדיקת ההרשאות."
        case NativeDeviceSetupError.recoveryRequired, is VehicleQueueError:
            message = "נדרשת התאוששות של זהות המכשיר או התור. הנתונים נשמרו ולא בוצע איפוס."
        case AuthFailure.network: message = "לא ניתן להשלים את האימות כעת. בדקו את החיבור ונסו שוב; זהות הרישום נשמרה."
        case AuthFailure.rejected(403, _): message = "אין הרשאה לבצע את השיוך. חזרו למסך הרכב ורעננו הרשאות."
        default: message = "לא ניתן להשלים את ההגדרה. חזרו למסך הרכב ונסו שוב."
        }
    }
}
