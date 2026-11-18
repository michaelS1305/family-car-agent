import Foundation

enum HistoryTime {
    static func parse(_ text: String) throws -> Date {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = f.date(from: text) { return date }
        f.formatOptions = [.withInternetDateTime]
        guard let date = f.date(from: text) else { throw AuthFailure.invalidResponse }
        return date
    }
    static func wire(_ date: Date) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        f.timeZone = .current
        return f.string(from: date)
    }
    static func display(_ date: Date, format: String, zone: TimeZone = .current) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "he_IL"); f.calendar = Calendar(identifier: .gregorian)
        f.timeZone = zone; f.dateFormat = format
        return f.string(from: date)
    }
    static func interval(_ start: Date, _ end: Date, zone: TimeZone = .current) -> String {
        var calendar = Calendar(identifier: .gregorian); calendar.timeZone = zone
        if calendar.isDate(start, inSameDayAs: end) {
            return display(start, format: "HH:mm", zone: zone) + "–" + display(end, format: "HH:mm", zone: zone)
        }
        return display(start, format: "dd/MM · HH:mm", zone: zone) + "\n" + display(end, format: "dd/MM · HH:mm", zone: zone)
    }
}
struct HistoryFilters: Equatable, Sendable {
    var vehicle: UUID?
    var member: UUID?
    var from: Date?
    var to: Date?
    var valid: Bool { guard let from, let to else { return true }; return from <= to }
    var empty: Bool { self == HistoryFilters() }
    func query(cursor: UUID?) -> [URLQueryItem] {
        var result = [URLQueryItem(name: "limit", value: "50")]
        for (name, value) in [("cursor", cursor?.uuidString.lowercased()),
                              ("vehicle_ref", vehicle?.uuidString.lowercased()),
                              ("member_ref", member?.uuidString.lowercased()),
                              ("from_datetime", from.map(HistoryTime.wire)), ("to_datetime", to.map(HistoryTime.wire))] {
            if let value { result.append(URLQueryItem(name: name, value: value)) }
        }
        return result
    }
}
struct HistoryUsage: Decodable, Sendable, Identifiable {
    let id: UUID
    let vehicle: UUID
    let member: UUID
    let vehicleName: String
    let name: String
    let start: Date
    let end: Date
    enum CodingKeys: String, CodingKey { case session_ref, vehicle_ref, member_ref, vehicle_name, name, started_at, ended_at }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(UUID.self, forKey: .session_ref)
        vehicle = try c.decode(UUID.self, forKey: .vehicle_ref); member = try c.decode(UUID.self, forKey: .member_ref)
        vehicleName = try c.decode(String.self, forKey: .vehicle_name); name = try c.decode(String.self, forKey: .name)
        start = try HistoryTime.parse(c.decode(String.self, forKey: .started_at))
        end = try HistoryTime.parse(c.decode(String.self, forKey: .ended_at))
        guard end >= start else { throw AuthFailure.invalidResponse }
    }
}
struct HistoryPage: Decodable, Sendable {
    let recent_usage: [HistoryUsage]
    let has_more: Bool
    let next_cursor: UUID?
    enum CodingKeys: String, CodingKey { case recent_usage, has_more, next_cursor }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        recent_usage = try c.decode([HistoryUsage].self, forKey: .recent_usage)
        has_more = try c.decode(Bool.self, forKey: .has_more)
        guard c.contains(.next_cursor) else { throw AuthFailure.invalidResponse }
        next_cursor = try c.decodeIfPresent(UUID.self, forKey: .next_cursor)
        guard recent_usage.count <= 50,
              has_more ? (!recent_usage.isEmpty && next_cursor == recent_usage.last?.id) : next_cursor == nil
        else { throw AuthFailure.invalidResponse }
    }
}
struct HistoryVehicle: Decodable, Sendable, Identifiable {
    let id: UUID
    let name: String
    let inUse: Bool
    let driver: String?
    let start: Date?
    enum CodingKeys: String, CodingKey { case vehicle_ref, display_name, in_use, current_driver, started_at, retired_at }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(UUID.self, forKey: .vehicle_ref); name = try c.decode(String.self, forKey: .display_name)
        inUse = try c.decode(Bool.self, forKey: .in_use)
        guard c.contains(.retired_at), try c.decodeNil(forKey: .retired_at),
              c.contains(.current_driver), c.contains(.started_at) else { throw AuthFailure.invalidResponse }
        driver = try c.decodeIfPresent(String.self, forKey: .current_driver)
        start = try c.decodeIfPresent(String.self, forKey: .started_at).map(HistoryTime.parse)
        guard inUse ? (driver != nil && start != nil) : (driver == nil && start == nil) else { throw AuthFailure.invalidResponse }
    }
}
struct HistoryMembers: Decodable, Sendable { let members: [FamilyMember] }
enum HistoryOperation: Sendable {
    case page(HistoryFilters, UUID?), current, members
    var path: String { switch self { case .page: "/api/car/history"; case .current: "/api/vehicles"; case .members: "/api/family" } }
    var query: [URLQueryItem] { if case .page(let filters, let cursor) = self { filters.query(cursor: cursor) } else { [] } }
}
enum HistoryReply: Sendable { case page(HistoryPage), current([HistoryVehicle]), members([FamilyMember]) }
protocol HistoryTransport: Sendable { func history(token: String, operation: HistoryOperation) async throws -> HistoryReply }
@MainActor protocol HistoryGateway: VehiclesGateway {
    func historyRequest(identity: ChatIdentity, operation: HistoryOperation) async throws -> HistoryReply
}
