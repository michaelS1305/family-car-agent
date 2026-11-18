import Foundation

@main struct BookingPreviewChecks {
    static func main() {
        let calendar = BookingPreviewCalendar.calendar
        func date(_ year: Int, _ month: Int, _ day: Int) -> Date {
            calendar.date(from: DateComponents(year: year, month: month, day: day, hour: 12))!
        }
        precondition(calendar.identifier == .gregorian && calendar.firstWeekday == 1)
        precondition(calendar.timeZone.identifier == "Asia/Jerusalem")
        for year in [2024, 2025, 2026, 2027] {
            for month in 1...12 {
                let model = BookingPreviewCalendar(now: date(year, month, 15))
                precondition(model.days.count % 7 == 0 && (28...42).contains(model.days.count))
                precondition(calendar.component(.weekday, from: model.days.first!) == 1)
                precondition(calendar.component(.weekday, from: model.days.last!) == 7)
                let actual = model.days.filter { calendar.isDate($0, equalTo: model.month, toGranularity: .month) }
                precondition(actual.count == calendar.range(of: .day, in: .month, for: model.month)!.count)
                for pair in zip(model.days, model.days.dropFirst()) {
                    precondition(calendar.dateComponents([.day], from: pair.0, to: pair.1).day == 1)
                }
            }
        }
        var model = BookingPreviewCalendar(now: date(2026, 12, 31))
        let selected = model.selected
        model.moveMonth(1)
        precondition(calendar.component(.year, from: model.month) == 2027)
        precondition(calendar.component(.month, from: model.month) == 1 && model.selected != selected)
        model.moveMonth(-1)
        precondition(calendar.component(.month, from: model.month) == 12)
        model.select(date(2027, 1, 1))
        precondition(calendar.component(.year, from: model.selected) == 2027)
        model.select(date(2024, 2, 29))
        precondition(calendar.component(.day, from: model.selected) == 29)
        // Local dates remain consecutive through Israel's daylight-saving transitions.
        for day in [date(2026, 3, 27), date(2026, 10, 25)] {
            model.select(day)
            precondition(calendar.isDate(model.selected, inSameDayAs: day))
        }
        print("PASS: Booking preview calendar, 48 months, Sunday-first, leap year, selection, year/month boundaries and Israel DST dates")
    }
}
