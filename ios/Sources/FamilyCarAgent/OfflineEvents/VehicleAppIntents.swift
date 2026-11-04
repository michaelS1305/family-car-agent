#if DEBUG && os(iOS)
import AppIntents
import CoreLocation
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
              let choices = try? runtime.shortcutVehicles(), let names = runtime.sessions.session?.boundVehicles else { return [] }
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
    @MainActor static func evidence(_ place: CLPlacemark?, at time: Date) -> VehicleLocationEvidence? {
        func evidence(from fix: CLLocation?) -> VehicleLocationEvidence? {
            guard let fix, CLLocationCoordinate2DIsValid(fix.coordinate),
                  fix.horizontalAccuracy > 0, fix.horizontalAccuracy <= 100,
                  (0...30).contains(time.timeIntervalSince(fix.timestamp)) else { return nil }
            return .init(latitude: fix.coordinate.latitude, longitude: fix.coordinate.longitude,
                         accuracy: fix.horizontalAccuracy, measuredAt: fix.timestamp)
        }
        // A placemark may be a geocoded address with only a coordinate. Require
        // measurement provenance before using its accuracy or capture timestamp.
        if let fix = place?.location, let source = fix.sourceInformation, !source.isSimulatedBySoftware,
           let result = evidence(from: fix) { return result }
        let manager = CLLocationManager()
        guard [.authorizedAlways, .authorizedWhenInUse].contains(manager.authorizationStatus),
              let fix = manager.location, fix.sourceInformation?.isSimulatedBySoftware != true else { return nil }
        return evidence(from: fix)
    }

    @MainActor static func record(_ vehicle: FCABoundVehicle, kind: QueuedVehicleEvent.Kind, place: CLPlacemark? = nil) async -> String {
        let time = Date()
        do {
            let runtime = try VehicleSessionRuntime.shared.get()
            guard try runtime.shortcutVehicles()[vehicle.id] != nil else { return "הרכב אינו משויך למכשיר בחשבון הנוכחי." }
            let location = kind == .returning ? evidence(place, at: time) : nil
            try await runtime.recordShortcut(selection: vehicle.id, kind: kind, time: time, location: location)
            return "האירוע נשמר במכשיר לסנכרון."
        } catch ShortcutQueueError.location { return "ההחזרה לא נרשמה. נדרשת מדידת מיקום עדכנית ומדויקת." }
        catch ShortcutQueueError.alreadyTaken { return "כבר קיימת לקיחה פתוחה לרכב הזה." }
        catch ShortcutQueueError.noUniqueTake { return "לא נמצאה לקיחה פתוחה וחד־משמעית לרכב הזה במכשיר." }
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
