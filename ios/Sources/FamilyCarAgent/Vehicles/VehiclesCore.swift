import Foundation

enum VehicleCategory: String, CaseIterable, Sendable {
    case hatchback, sedan, crossover, minivan, suv
    var label: String { self == .suv ? "SUV" : rawValue.capitalized }
    var asset: String {
        switch self {
        case .hatchback: "vehicles/hatchback/vehicle_hatchback.png"
        case .sedan: "vehicles/sedan/vehicle_sedan.png"
        case .crossover: "vehicles/crossover/vehicle_crossover.png"
        case .minivan: "vehicles/van/modern_silver_minivan.png"
        case .suv: "vehicles/suv/suv_silver.png"
        }
    }
    static func illustration(_ category: Self?) -> String { category?.asset ?? "icons/archive/single_car_icon.png" }
}
struct ManagedVehicle: Decodable, Identifiable, Sendable, Equatable {
    let id: UUID
    let name: String
    let createdAt: Date
    let retiredAt: Date?
    let category: VehicleCategory?
    let manufacturerID: Int?
    let manufacturerName: String?
    let model: String?
    let plate: String?
    var retired: Bool { retiredAt != nil }
    enum CodingKeys: String, CodingKey {
        case vehicle_ref, display_name, created_at, retired_at, category, manufacturer_id, manufacturer_name_he, model, license_plate
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        for key in [CodingKeys.retired_at, .category, .manufacturer_id, .manufacturer_name_he, .model, .license_plate] {
            guard c.contains(key) else { throw AuthFailure.invalidResponse }
        }
        func date(_ text: String) throws -> Date {
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = formatter.date(from: text) { return date }
            formatter.formatOptions = [.withInternetDateTime]
            guard let date = formatter.date(from: text) else { throw AuthFailure.invalidResponse }
            return date
        }
        id = try c.decode(UUID.self, forKey: .vehicle_ref)
        name = try c.decode(String.self, forKey: .display_name)
        createdAt = try date(c.decode(String.self, forKey: .created_at))
        retiredAt = try c.decodeIfPresent(String.self, forKey: .retired_at).map(date)
        category = try c.decodeIfPresent(String.self, forKey: .category).flatMap(VehicleCategory.init(rawValue:))
        manufacturerID = try c.decodeIfPresent(Int.self, forKey: .manufacturer_id)
        if let manufacturerID, manufacturerID <= 0 { throw AuthFailure.invalidResponse }
        manufacturerName = try c.decodeIfPresent(String.self, forKey: .manufacturer_name_he)
        model = try c.decodeIfPresent(String.self, forKey: .model)
        plate = try c.decodeIfPresent(String.self, forKey: .license_plate)
    }
}
struct VehicleManufacturer: Decodable, Identifiable, Equatable, Sendable {
    let id: Int
    let name_he: String
}
struct VehiclePermission: Decodable, Sendable { let can_edit_roles: Bool }
enum VehicleFormField: CaseIterable { case name, category, manufacturer, model, plate }
struct VehicleDraft: Equatable, Sendable {
    var name = ""
    var category: VehicleCategory?
    var manufacturer: VehicleManufacturer?
    var manufacturerQuery = ""
    var model = ""
    var plate = ""
    var valid: Bool {
        validationErrors.isEmpty
    }
    var validationErrors: [VehicleFormField: String] {
        var errors: [VehicleFormField: String] = [:]
        if name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { errors[.name] = "יש להזין שם לרכב" }
        if category == nil { errors[.category] = "יש לבחור סוג רכב" }
        if manufacturer == nil || manufacturerQuery != manufacturer?.name_he {
            errors[.manufacturer] = manufacturerQuery.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "יש לבחור יצרן" : "יש לבחור יצרן מהרשימה"
        }
        if model.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { errors[.model] = "יש להזין דגם" }
        if plate.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { errors[.plate] = "יש להזין מספר רכב" }
        return errors
    }
}
struct VehicleSubmission: Equatable, Sendable, Encodable {
    let requestID: UUID
    let draft: VehicleDraft
    enum CodingKeys: String, CodingKey { case request_id, display_name, category, manufacturer_id, model, license_plate }
    func encode(to encoder: Encoder) throws {
        guard draft.valid, requestID.uuid.6 >> 4 == 4 else { throw AuthFailure.configuration }
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(requestID.uuidString.lowercased(), forKey: .request_id)
        try c.encode(draft.name, forKey: .display_name)
        try c.encode(draft.category!.rawValue, forKey: .category)
        try c.encode(draft.manufacturer!.id, forKey: .manufacturer_id)
        try c.encode(draft.model, forKey: .model)
        try c.encode(draft.plate, forKey: .license_plate)
    }
}
enum VehiclesOperation: Sendable {
    case list, permission, manufacturers, create(VehicleSubmission)
    var path: String {
        switch self { case .list, .create: "/api/vehicles"; case .permission: "/api/family"; case .manufacturers: "/api/reference/manufacturers" }
    }
    var method: String { if case .create = self { "POST" } else { "GET" } }
    var query: [URLQueryItem] { if case .list = self { [URLQueryItem(name: "include_retired", value: "true")] } else { [] } }
    func body() throws -> Data? { if case .create(let request) = self { try JSONEncoder().encode(request) } else { nil } }
}
enum VehiclesReply: Sendable { case list([ManagedVehicle]), permission(Bool), manufacturers([VehicleManufacturer]), created(ManagedVehicle) }
protocol VehiclesTransport: Sendable { func vehicles(token: String, operation: VehiclesOperation) async throws -> VehiclesReply }
@MainActor protocol VehiclesGateway: AnyObject, Sendable {
    var vehiclesIdentity: ChatIdentity? { get }
    func vehiclesRequest(identity: ChatIdentity, operation: VehiclesOperation) async throws -> VehiclesReply
}
enum VehiclesDestination: Hashable { case add, details(UUID) }

struct VehicleDetail: Decodable, Sendable {
    let vehicle: ManagedVehicle
    let inUse: Bool
    enum CodingKeys: String, CodingKey { case in_use }
    init(from decoder: Decoder) throws {
        vehicle = try ManagedVehicle(from: decoder)
        inUse = try decoder.container(keyedBy: CodingKeys.self).decode(Bool.self, forKey: .in_use)
    }
    var status: String { vehicle.retired ? "לא פעיל" : inUse ? "בשימוש" : "פנוי" }
}

/// A server calendar day, never an instant converted through the device time zone.
struct VehicleDay: Equatable, Sendable, Codable {
    let rawValue: String
    static var calendar: Calendar {
        var c = Calendar(identifier: .gregorian); c.timeZone = TimeZone(secondsFromGMT: 0)!; return c
    }
    init(_ value: String) throws {
        guard value.range(of: "^[0-9]{4}-[0-9]{2}-[0-9]{2}$", options: .regularExpression) != nil else { throw AuthFailure.invalidResponse }
        let p = value.split(separator: "-").compactMap { Int($0) }
        guard p.count == 3, p[0] > 0,
              let date = Self.calendar.date(from: DateComponents(year: p[0], month: p[1], day: p[2])),
              Self.string(date) == value else { throw AuthFailure.invalidResponse }
        rawValue = value
    }
    static func string(_ date: Date) -> String {
        let p = calendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", p.year!, p.month!, p.day!)
    }
    var date: Date {
        let p = rawValue.split(separator: "-").map { Int($0)! }
        return Self.calendar.date(from: DateComponents(year: p[0], month: p[1], day: p[2]))!
    }
    static func today() -> Self {
        let p = Calendar.current.dateComponents([.year, .month, .day], from: Date())
        return try! Self(String(format: "%04d-%02d-%02d", p.year!, p.month!, p.day!))
    }
    var label: String { rawValue.split(separator: "-").reversed().joined(separator: "/") }
    init(from decoder: Decoder) throws { try self.init(decoder.singleValueContainer().decode(String.self)) }
    func encode(to encoder: Encoder) throws { var c = encoder.singleValueContainer(); try c.encode(rawValue) }
}
struct VehicleMaintenance: Decodable, Identifiable, Sendable, Equatable {
    let id: UUID
    let description: String
    let day: VehicleDay
    let completed: Bool
    enum CodingKeys: String, CodingKey { case maintenance_ref, description, scheduled_date, completed, created_at }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(UUID.self, forKey: .maintenance_ref)
        description = try c.decode(String.self, forKey: .description)
        day = try c.decode(VehicleDay.self, forKey: .scheduled_date)
        completed = c.contains(.completed) ? try c.decode(Bool.self, forKey: .completed) : false
        let text = try c.decode(String.self, forKey: .created_at)
        let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if f.date(from: text) == nil {
            f.formatOptions = [.withInternetDateTime]
            guard f.date(from: text) != nil else { throw AuthFailure.invalidResponse }
        }
    }
}
struct VehicleEdit: Encodable, Sendable {
    let draft: VehicleDraft
    enum CodingKeys: String, CodingKey { case display_name, category, manufacturer_id, model, license_plate }
    func encode(to encoder: Encoder) throws {
        guard draft.valid else { throw AuthFailure.configuration }
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(draft.name, forKey: .display_name); try c.encode(draft.category!.rawValue, forKey: .category)
        try c.encode(draft.manufacturer!.id, forKey: .manufacturer_id)
        try c.encode(draft.model, forKey: .model); try c.encode(draft.plate, forKey: .license_plate)
    }
}
struct MaintenanceEdit: Encodable, Sendable {
    let description: String
    let scheduled_date: VehicleDay
}
enum VehicleDetailsOperation: Sendable {
    case detail, maintenance, edit(VehicleDraft), retire
    case add(MaintenanceEdit), update(UUID, MaintenanceEdit), delete(UUID), complete(UUID)
    var method: String {
        switch self { case .detail, .maintenance: "GET"; case .edit, .update: "PUT"; case .delete: "DELETE"; default: "POST" }
    }
    func path(_ id: UUID) -> String {
        let root = "/api/vehicles/" + id.uuidString.lowercased()
        switch self {
        case .detail, .edit: return root
        case .retire: return root + "/retire"
        case .maintenance, .add: return root + "/maintenance"
        case .update(let item, _), .delete(let item): return root + "/maintenance/" + item.uuidString.lowercased()
        case .complete(let item): return root + "/maintenance/" + item.uuidString.lowercased() + "/complete"
        }
    }
    func body() throws -> Data? {
        switch self {
        case .edit(let draft): return try JSONEncoder().encode(VehicleEdit(draft: draft))
        case .add(let value), .update(_, let value):
            guard !value.description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw AuthFailure.configuration }
            return try JSONEncoder().encode(value)
        default: return nil
        }
    }
}
enum VehicleDetailsReply: Sendable { case detail(VehicleDetail), maintenance([VehicleMaintenance]), saved }
struct VehicleDeletionReceipt: Decodable, Sendable {}
protocol VehicleDetailsTransport: Sendable {
    func vehicleDetails(token: String, id: UUID, operation: VehicleDetailsOperation) async throws -> VehicleDetailsReply
}
@MainActor protocol VehicleDetailsGateway: VehiclesGateway {
    func vehicleDetailsRequest(identity: ChatIdentity, id: UUID, operation: VehicleDetailsOperation) async throws -> VehicleDetailsReply
}
