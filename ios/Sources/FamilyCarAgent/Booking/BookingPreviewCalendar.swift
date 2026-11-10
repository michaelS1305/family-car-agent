import Foundation

/// Gregorian calendar shared by the Booking Center and its deterministic checks.
struct BookingPreviewCalendar {
    static var calendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Asia/Jerusalem")!
        calendar.locale = Locale(identifier: "he_IL")
        calendar.firstWeekday = 1
        return calendar
    }
    private(set) var month: Date
    private(set) var selected: Date
    init(now: Date = Date()) {
        let calendar = Self.calendar
        selected = calendar.startOfDay(for: now)
        month = calendar.dateInterval(of: .month, for: now)!.start
    }
    var days: [Date] {
        let calendar = Self.calendar
        let offset = calendar.component(.weekday, from: month) - 1
        let start = calendar.date(byAdding: .day, value: -offset, to: month)!
        let count = calendar.range(of: .day, in: .month, for: month)!.count
        let cells = ((offset + count + 6) / 7) * 7
        return (0..<cells).map { calendar.date(byAdding: .day, value: $0, to: start)! }
    }
    mutating func moveMonth(_ delta: Int) {
        month = Self.calendar.date(byAdding: .month, value: delta, to: month)!
        let day = min(Self.calendar.component(.day, from: selected), Self.calendar.range(of: .day, in: .month, for: month)!.count)
        selected = Self.calendar.date(byAdding: .day, value: day - 1, to: month)!
    }
    mutating func select(_ day: Date) {
        selected = Self.calendar.startOfDay(for: day)
        month = Self.calendar.dateInterval(of: .month, for: day)!.start
    }
    static func label(_ date: Date, format: String) -> String {
        let formatter = DateFormatter()
        formatter.calendar = calendar
        formatter.locale = Locale(identifier: "he_IL")
        formatter.timeZone = calendar.timeZone
        formatter.dateFormat = format
        return formatter.string(from: date)
    }
}
