import Foundation

enum BookingTime {
    // Offset-free writes cannot identify which occurrence of a repeated local time was intended.
    static func unambiguous(_ date: Date) -> Bool {
        let calendar = BookingPreviewCalendar.calendar
        let parts = calendar.dateComponents([.hour, .minute, .second], from: date)
        let before = calendar.startOfDay(for: date).addingTimeInterval(-1)
        let first = calendar.nextDate(after: before, matching: parts, matchingPolicy: .strict, repeatedTimePolicy: .first)
        let last = calendar.nextDate(after: before, matching: parts, matchingPolicy: .strict, repeatedTimePolicy: .last)
        return first != nil && first == last && calendar.isDate(first!, inSameDayAs: date)
    }
    static func defaults(selected: Date, now: Date) -> (start: Date, end: Date) {
        let calendar = BookingPreviewCalendar.calendar
        let day = max(calendar.startOfDay(for: selected), calendar.startOfDay(for: now))
        var start = calendar.date(bySettingHour: 9, minute: 0, second: 0, of: day)!
        if calendar.isDate(day, inSameDayAs: now) {
            let hour = calendar.dateInterval(of: .hour, for: now)!.start
            start = calendar.date(byAdding: .minute, value: (calendar.component(.minute, from: now) / 15 + 1) * 15, to: hour)!
        }
        var end = calendar.date(byAdding: .hour, value: 1, to: start)!
        while !unambiguous(start) || !unambiguous(end) || wire(end) <= wire(start) {
            start = calendar.date(byAdding: .minute, value: 15, to: start)!
            end = calendar.date(byAdding: .hour, value: 1, to: start)!
        }
        return (start, end)
    }
    static func wire(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = BookingPreviewCalendar.calendar
        formatter.timeZone = BookingPreviewCalendar.calendar.timeZone
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return formatter.string(from: date)
    }
    static func parse(_ value: String) throws -> Date {
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = iso.date(from: value) { return date }
        iso.formatOptions = [.withInternetDateTime]
        if let date = iso.date(from: value) { return date }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = BookingPreviewCalendar.calendar
        formatter.timeZone = BookingPreviewCalendar.calendar.timeZone
        formatter.isLenient = false
        for format in ["yyyy-MM-dd'T'HH:mm:ss.SSSSSS", "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd'T'HH:mm"] {
            formatter.dateFormat = format
            if let date = formatter.date(from: value),
               String(wire(date).prefix(value.count < 19 ? 16 : 19)) == String(value.prefix(19)),
               unambiguous(date) { return date }
        }
        throw AuthFailure.invalidResponse
    }
}

struct BookingReservation: Identifiable, Decodable, Equatable, Sendable {
    let id: UUID
    let member: UUID
    let owner: String
    let start: Date
    let end: Date
    let mine: Bool
    let vehicle: UUID?
    let vehicleName: String?
    let category: VehicleCategory?
    enum CodingKeys: String, CodingKey {
        case reservation_ref, member_ref, owner_name, start_time, end_time, is_mine, vehicle_ref, vehicle_display_name, vehicle_category
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(UUID.self, forKey: .reservation_ref)
        member = try c.decode(UUID.self, forKey: .member_ref)
        owner = try c.decode(String.self, forKey: .owner_name)
        start = try BookingTime.parse(c.decode(String.self, forKey: .start_time))
        end = try BookingTime.parse(c.decode(String.self, forKey: .end_time))
        mine = try c.decode(Bool.self, forKey: .is_mine)
        vehicle = try c.decodeIfPresent(UUID.self, forKey: .vehicle_ref)
        vehicleName = try c.decodeIfPresent(String.self, forKey: .vehicle_display_name)
        category = try c.decodeIfPresent(String.self, forKey: .vehicle_category).flatMap(VehicleCategory.init(rawValue:))
        guard end > start, vehicle != nil || (vehicleName == nil && category == nil) else { throw AuthFailure.invalidResponse }
    }
    func eligible(at now: Date) -> Bool { mine && end > now }
    func overlaps(_ start: Date, _ end: Date) -> Bool { self.start < end && self.end > start }
    static func decodeList(_ data: Data) throws -> [Self] {
        let rows = try JSONDecoder().decode([Self].self, from: data)
        guard Set(rows.map(\.id)).count == rows.count else { throw AuthFailure.invalidResponse }
        return rows.sorted { $0.start < $1.start }
    }
}

struct BookingFilters: Equatable, Sendable {
    var vehicle: UUID?
    var member: UUID?
    var start: Date?
    var end: Date?
    var valid: Bool { start == nil || end == nil || start! < end! }
    var empty: Bool { self == Self() }
    func matches(_ row: BookingReservation) -> Bool {
        (vehicle == nil || row.vehicle == vehicle) && (member == nil || row.member == member) &&
        (start == nil || row.end > start!) && (end == nil || row.start < end!)
    }
}
struct BookingQuery: Equatable, Sendable {
    let start: Date
    let end: Date
    let filters: BookingFilters
    init(calendar: BookingPreviewCalendar, filters: BookingFilters) {
        start = calendar.days.first!
        end = BookingPreviewCalendar.calendar.date(byAdding: .day, value: 1, to: calendar.days.last!)!
        self.filters = filters
    }
    var lower: Date { max(start, filters.start ?? start) }
    var upper: Date { min(end, filters.end ?? end) }
    var empty: Bool { lower >= upper }
    var items: [URLQueryItem] {
        var values = [URLQueryItem(name: "range_start", value: BookingTime.wire(lower)),
                      URLQueryItem(name: "range_end", value: BookingTime.wire(upper)), URLQueryItem(name: "scope", value: "all")]
        if let id = filters.vehicle { values.append(URLQueryItem(name: "vehicle_ref", value: id.uuidString.lowercased())) }
        if let id = filters.member { values.append(URLQueryItem(name: "member_ref", value: id.uuidString.lowercased())) }
        return values
    }
    func covers(_ date: Date, vehicle: UUID?, member: UUID?) -> Bool {
        !empty && lower <= date && date < upper && (filters.vehicle == nil || filters.vehicle == vehicle) &&
        (filters.member == nil || filters.member == member)
    }
}
struct BookingDraft: Equatable, Sendable {
    var original: BookingReservation?
    var vehicle: UUID?
    var start: Date?
    var end: Date?
    func valid(now: Date, vehicles: [ManagedVehicle]) -> Bool {
        guard let start, let end, end > start, end > now,
              BookingTime.wire(end) > BookingTime.wire(start),
              BookingTime.unambiguous(start), BookingTime.unambiguous(end) else { return false }
        if let original {
            guard original.eligible(at: now), original.start >= now || start == original.start else { return false }
        }
        guard start >= now || start == original?.start else { return false }
        if let original, vehicle == original.vehicle { return true }
        if vehicles.contains(where: { $0.id == vehicle && !$0.retired }) { return true }
        return original == nil && vehicle == nil && !vehicles.contains(where: { !$0.retired })
    }
    func body() throws -> Data {
        guard let start, let end, end > start else { throw AuthFailure.configuration }
        var fields: [String: Any] = ["start_time": BookingTime.wire(start), "end_time": BookingTime.wire(end)]
        if let original { fields["reservation_ref"] = original.id.uuidString.lowercased() }
        if original == nil ? vehicle != nil : vehicle != original?.vehicle {
            fields["vehicle_ref"] = vehicle.map { $0.uuidString.lowercased() } as Any? ?? NSNull()
        }
        return try JSONSerialization.data(withJSONObject: fields)
    }
}
enum BookingWrite: Equatable, Sendable {
    case save(BookingDraft), cancel(BookingReservation)
    var original: BookingReservation? { switch self { case .save(let d): d.original; case .cancel(let r): r } }
    var start: Date { switch self { case .save(let d): d.start!; case .cancel(let r): r.start } }
    var end: Date { switch self { case .save(let d): d.end!; case .cancel(let r): r.end } }
    var vehicle: UUID? { switch self { case .save(let d): d.vehicle; case .cancel(let r): r.vehicle } }
    var method: String { if case .save(let d) = self, d.original != nil { return "PATCH" }; return "POST" }
    var isCancel: Bool { if case .cancel = self { return true }; return false }
    func body() throws -> Data {
        switch self {
        case .save(let d): try d.body()
        case .cancel(let r): try JSONSerialization.data(withJSONObject: ["reservation_ref": r.id.uuidString.lowercased()])
        }
    }
}
/// Process-memory reconciliation, matching Android: reads never prove an ambiguous write did not happen.
struct BookingPending {
    let operation: BookingWrite
    var proposedRead = false
    var originalRead = false
    var lastQuery: BookingQuery?
    mutating func observe(_ query: BookingQuery) {
        let proposed = query.covers(operation.start, vehicle: operation.vehicle, member: operation.original?.member)
        let old = operation.original.map { query.covers($0.start, vehicle: $0.vehicle, member: $0.member) } ?? false
        guard proposed || old else { return }
        proposedRead = proposedRead || proposed
        originalRead = originalRead || old
        lastQuery = query
    }
    var inspected: Bool { proposedRead && (operation.original == nil || originalRead) }
}
@MainActor protocol BookingGateway: AnyObject, Sendable {
    var vehiclesIdentity: ChatIdentity? { get }
    func reservationData(identity: ChatIdentity, method: String, cancel: Bool, query: [URLQueryItem], body: Data?) async throws -> Data
    func vehiclesRequest(identity: ChatIdentity, operation: VehiclesOperation) async throws -> VehiclesReply
    func historyRequest(identity: ChatIdentity, operation: HistoryOperation) async throws -> HistoryReply
}
