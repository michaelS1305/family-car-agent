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
    private enum Stage: String {
        case entered = "intent_entered"
        case present = "shortcut_location_present"
        case missing = "shortcut_location_missing"
        case shortcutValid = "shortcut_validation_accepted"
        case shortcutInvalid = "shortcut_validation_rejected"
        case fallback = "fallback_attempted"
        case fallbackValid = "fallback_validation_accepted"
        case fallbackInvalid = "fallback_validation_rejected"
        case accepted = "location_accepted"
        case rejected = "location_rejected"
        case record = "proceeding_to_record"
    }
    private static let logger = Logger(subsystem: "com.familycaragent.app", category: "return_location")
    private static func diagnostic(_ stage: Stage, reason: ReturnLocationReason? = nil) {
        // Public fields are closed enums only; never pass location or identity data.
        if let reason {
            logger.notice("FCA_RETURN_LOCATION stage=\(stage.rawValue, privacy: .public) reason=\(reason.rawValue, privacy: .public)")
        } else {
            logger.notice("FCA_RETURN_LOCATION stage=\(stage.rawValue, privacy: .public)")
        }
    }

    @MainActor static func evidence(_ place: CLPlacemark?, at time: Date) -> VehicleLocationEvidence? {
        func evidence(from fix: CLLocation?, shortcut: Bool) -> VehicleLocationEvidence? {
            let source = fix?.sourceInformation
            let reason = ReturnLocationValidation.rejection(present: fix != nil,
                requiresSource: shortcut, hasSource: source != nil,
                simulated: source?.isSimulatedBySoftware == true,
                validCoordinates: fix.map { CLLocationCoordinate2DIsValid($0.coordinate) } ?? false,
                accuracy: fix?.horizontalAccuracy ?? 0,
                age: fix.map { time.timeIntervalSince($0.timestamp) } ?? 0)
            if let reason {
                diagnostic(shortcut ? .shortcutInvalid : .fallbackInvalid, reason: reason)
                return nil
            }
            guard let fix else { return nil } // Guaranteed by the shared decision helper.
            diagnostic(shortcut ? .shortcutValid : .fallbackValid)
            return .init(latitude: fix.coordinate.latitude, longitude: fix.coordinate.longitude,
                         accuracy: fix.horizontalAccuracy, measuredAt: fix.timestamp)
        }
        let supplied = place?.location
        diagnostic(supplied == nil ? .missing : .present)
        if let result = evidence(from: supplied, shortcut: true) {
            diagnostic(.accepted)
            return result
        }
        diagnostic(.fallback)
        let manager = CLLocationManager()
        guard [.authorizedAlways, .authorizedWhenInUse].contains(manager.authorizationStatus) else {
            diagnostic(.fallbackInvalid, reason: .fallbackUnavailable)
            diagnostic(.rejected)
            return nil
        }
        let result = evidence(from: manager.location, shortcut: false)
        diagnostic(result == nil ? .rejected : .accepted)
        return result
    }

    @MainActor static func record(_ vehicle: FCABoundVehicle, kind: QueuedVehicleEvent.Kind, place: CLPlacemark? = nil) async -> String {
        let time = Date()
        if kind == .returning { diagnostic(.entered) }
        do {
            let runtime = try VehicleSessionRuntime.shared.get()
            let location = kind == .returning ? evidence(place, at: time) : nil
            if kind == .returning { diagnostic(.record) }
            try await runtime.recordShortcut(selection: vehicle.id, kind: kind, time: time, location: location)
            return "האירוע נשמר במכשיר לסנכרון."
        } catch ShortcutQueueError.location { return "ההחזרה לא נרשמה. נדרשת מדידת מיקום עדכנית ומדויקת." }
        catch ShortcutQueueError.alreadyTaken { return "כבר קיימת לקיחה פתוחה לרכב הזה." }
        catch ShortcutQueueError.noUniqueTake { return "לא נמצאה לקיחה פתוחה וחד־משמעית לרכב הזה במכשיר." }
        catch ShortcutQueueError.legacyReturn { return "ההחזרה הקודמת חסומה ללא סיבת דחייה מאומתת. המידע נשמר; נדרשת בדיקה פרטנית מול התמיכה." }
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
    @Parameter(title: "Current Location") var location: CLPlacemark?
    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        .result(value: await VehicleShortcut.record(vehicle, kind: .returning, place: location))
    }
}
#endif
