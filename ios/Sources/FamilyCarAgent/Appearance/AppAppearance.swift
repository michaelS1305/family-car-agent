import Foundation
#if canImport(SwiftUI)
import SwiftUI
#endif

/// Device-local preference, deliberately independent of authentication.
/// Root and Settings observe the same AppStorage key; invalid values follow System.
enum AppAppearance: String, CaseIterable, Sendable {
    case system, light, dark
    static let storageKey = "fca.appearance.mode.v1"

    init(storedValue: Any?) {
        self = (storedValue as? String).flatMap(Self.init(rawValue:)) ?? .system
    }

    var title: String {
        switch self {
        case .system: return "מערכת"
        case .light: return "בהיר"
        case .dark: return "כהה"
        }
    }

    #if canImport(SwiftUI)
    var colorScheme: ColorScheme? {
        switch self {
        case .system: return nil
        case .light: return .light
        case .dark: return .dark
        }
    }
    #endif
}
