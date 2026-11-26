// Pure decision helper shared by the iOS adapter and executable regression checks.
// Inputs are never logged. These are the original checks, in their original order.
enum ReturnLocationReason: String {
    case missingLocation = "missing_location"
    case missingSource = "missing_source_information"
    case simulated = "simulated_location"
    case stale = "stale_location"
    case future = "future_timestamp"
    case accuracy = "insufficient_accuracy"
    case coordinates = "invalid_coordinates"
    case fallbackUnavailable = "fallback_unavailable"
}
enum ReturnLocationValidation {
    static func rejection(present: Bool, requiresSource: Bool, hasSource: Bool,
                          simulated: Bool, validCoordinates: Bool, accuracy: Double,
                          age: Double) -> ReturnLocationReason? {
        guard present else { return .missingLocation }
        guard !requiresSource || hasSource else { return .missingSource }
        guard !simulated else { return .simulated }
        guard validCoordinates else { return .coordinates }
        guard accuracy > 0, accuracy <= 100 else { return .accuracy }
        guard (0...30).contains(age) else { return age < 0 ? .future : .stale }
        return nil
    }
}

#if os(iOS)
import AppIntents
import CoreLocation
import OSLog
import Foundation

struct FCABoundVehicle: AppEntity {
    static let typeDisplayRepresentation = TypeDisplayRepresentation(name: "FCA Vehicle")
    static let defaultQuery = FCABoundVehicleQuery()
    let id: String
    let vehicleRef: UUID
    let name: String
    var displayRepresentation: DisplayRepresentation { .init(title: "\(name)", subtitle: "\(vehicleRef.uuidString)") }
}

struct FCABoundVehicleQuery: EntityQuery {
    @MainActor func suggestedEntities() async throws -> [FCABoundVehicle] {
        guard let runtime = try? VehicleSessionRuntime.shared.get(),
              let choices = try? await runtime.shortcutVehicles(), let names = runtime.sessions.session?.boundVehicles else { return [] }
        return choices.compactMap { key, ref in
            names[ref].map { FCABoundVehicle(id: key, vehicleRef: ref, name: $0) }
        }.sorted { $0.id < $1.id }
    }
    func entities(for identifiers: [String]) async throws -> [FCABoundVehicle] {
        let choices = try await suggestedEntities()
        return identifiers.compactMap { id in choices.first { $0.id == id } }
    }
}

private enum VehicleShortcut {
    @MainActor static func record(_ vehicle: FCABoundVehicle, kind: QueuedVehicleEvent.Kind) async -> String {
        let intentStartedAt = Date() // Invocation time, not a claim about the disconnect time.
        var progress = ReturnRecordingProgress()
        defer { if kind == .returning { ReturnLocationLog.recording(progress) } }
        if kind == .returning { ReturnLocationLog.emit(.intentEntered) }
        do {
            let runtime = try VehicleSessionRuntime.shared.get()
            if kind == .take {
                try await runtime.recordShortcut(selection: vehicle.id, kind: kind, time: intentStartedAt, location: nil)
            } else {
                let prepared = try await runtime.prepareNativeReturn(selection: vehicle.id)
                let acquisition = ReturnLocationAcquisition()
                guard let location = await acquisition.acquire() else {
                    switch acquisition.outcome {
                    case .unauthorized, .unavailable: return "ההחזרה לא נרשמה. פתחו את FCA ואפשרו גישה למיקום בהגדרות האייפון."
                    case .cancelled: return "מדידת המיקום בוטלה. ההחזרה לא נרשמה."
                    case .timedOut: return "ההחזרה לא נרשמה. לא התקבלה מדידה עדכנית ומדויקת בתוך 15 שניות. בדקו שמיקום מדויק מופעל ונסו שוב."
                    default: return "ההחזרה לא נרשמה. שירותי המיקום אינם זמינים כעת. בדקו את הגדרות המיקום ונסו שוב."
                    }
                }
                ReturnLocationLog.emit(.proceedingToRecord)
                try await runtime.recordNativeReturn(prepared, location: location) { progress.didCommit() }
                progress.didFinishProcessing()
            }
            return "האירוע נשמר במכשיר לסנכרון."
        } catch ShortcutQueueError.location { return "ההחזרה לא נרשמה. נדרשת מדידת מיקום עדכנית ומדויקת." }
        catch is CancellationError { return kind == .returning ? "הפעולה בוטלה לפני רישום ההחזרה. הפעילו שוב כשברצונכם להחזיר את הרכב." : "לא ניתן לרשום את האירוע. בדקו שהמכשיר נפתח לאחר האתחול ושהרכב משויך לחשבון." }
        catch ShortcutQueueError.contextChanged { return "ההחזרה לא נרשמה: החשבון, הרכב או הנסיעה השתנו בזמן המדידה. בדקו את המצב והפעילו שוב את ההחזרה." }
        catch ShortcutQueueError.alreadyTaken { return "כבר קיימת לקיחה פתוחה לרכב הזה." }
        catch ShortcutQueueError.noUniqueTake { return "לא נמצאה לקיחה פתוחה וחד־משמעית לרכב הזה במכשיר." }
        catch ShortcutQueueError.legacyReturn { return "ההחזרה הקודמת חסומה ללא סיבת דחייה מאומתת. המידע נשמר; נדרשת בדיקה פרטנית מול התמיכה." }
        catch ShortcutQueueError.locationExpired { return "מדידת המיקום פגה. ההחזרה נשמרה במכשיר; הפעילו שוב את קיצור ההחזרה עם מיקום עדכני." }
        catch ShortcutQueueError.retryStored { return "ההחזרה שמורה במכשיר וממתינה לסנכרון. אם השליחה טרם אושרה, ייעשה ניסיון חוזר כשהחיבור והשירות יהיו זמינים." }
        catch ShortcutQueueError.recoveryBlocked { return "לא ניתן לשחזר את ההחזרה אוטומטית. המידע נשמר; פנו לתמיכה לבדיקת סדר האירועים או סיבת הדחייה." }
        catch { return "לא ניתן לרשום את האירוע. בדקו שהמכשיר נפתח לאחר האתחול ושהרכב משויך לחשבון." }
    }
}

struct FCATakeVehicleIntent: AppIntent {
    static let title: LocalizedStringResource = "FCA — Take Vehicle"
    static let openAppWhenRun = false
    @Parameter(title: "Vehicle") var vehicle: FCABoundVehicle
    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        .result(value: await VehicleShortcut.record(vehicle, kind: .take))
    }
}

struct FCAReturnVehicleIntent: AppIntent {
    static let title: LocalizedStringResource = "FCA — Return Vehicle"
    static let openAppWhenRun = false
    @Parameter(title: "Vehicle") var vehicle: FCABoundVehicle
    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        .result(value: await VehicleShortcut.record(vehicle, kind: .returning))
    }
}
#endif
