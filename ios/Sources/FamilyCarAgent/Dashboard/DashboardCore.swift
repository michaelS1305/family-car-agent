import Foundation

enum DashboardDestination: String, CaseIterable, Hashable {
    case family, vehicles, settings, history, bookingCenter
    var label: String {
        switch self {
        case .family: "משפחה"
        case .vehicles: "רכבים"
        case .settings: "הגדרות"
        case .history: "היסטוריה"
        case .bookingCenter: "מרכז הזמנות"
        }
    }
    var asset: String {
        "icons/archive/" + (self == .bookingCenter ? "booking_center" : rawValue) + "_icon.png"
    }
    var anchor: (x: Double, y: Double) {
        switch self {
        case .family: (0.50, 0.20)
        case .vehicles: (0.77, 0.44)
        case .settings: (0.67, 0.73)
        case .history: (0.35, 0.75)
        case .bookingCenter: (0.19, 0.39)
        }
    }
}

struct DashboardLayout {
    let compact: Bool
    let headerHeight: Double
    let greetingHeight: Double
    let diameter: Double
    let contentHeight: Double
    var logoutHeight: Double { contentHeight - 8 - headerHeight - greetingHeight - 6 - diameter }
    init(width: Double, height: Double) {
        compact = height < 540
        headerHeight = compact ? 64 : 85
        greetingHeight = compact ? 32 : 38
        // 176 points guarantees 44-point category hit widths. Extremely short
        // viewports scroll rather than overlap logout, greeting or category targets.
        let minimum = 8 + headerHeight + greetingHeight + 6 + 176 + 70
        contentHeight = max(height, minimum)
        diameter = max(0, min(max(0, width - 16), contentHeight - 8 - headerHeight - greetingHeight - 6 - 70))
    }
    static let startAngle = -126.0
    static let sweep = 72.0
    static func radius(_ diameter: Double) -> Double { diameter * 0.46 }
    static func hub(_ diameter: Double) -> Double { radius(diameter) * 0.23 }
    static func greeting(_ name: String) -> String {
        guard let first = name.split(whereSeparator: { $0.isWhitespace }).first else { return "היי" }
        return "היי, \(first)"
    }
}

struct DashboardNavigation {
    var path: [DashboardDestination] = []
    private var identity: ChatIdentity?
    var isRoot: Bool { path.isEmpty }
    mutating func synchronize(_ current: ChatIdentity?) {
        guard current != identity else { return }
        identity = current; path = []
    }
    mutating func open(_ destination: DashboardDestination) {
        guard identity != nil, path.isEmpty else { return }
        path = [destination]
    }
    mutating func back() { path = [] }
}
