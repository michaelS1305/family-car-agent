import Foundation
#if canImport(SwiftUI)
import SwiftUI
#endif
#if canImport(UIKit)
import UIKit
#endif

@main struct AppearanceChecks {
    static func main() {
        precondition(AppAppearance.allCases.count == 3)
        precondition(AppAppearance.allCases.map(\.title) == ["מערכת", "בהיר", "כהה"])
        for value in [nil, "invalid", "", 42, ["dark"], true] as [Any?] {
            precondition(AppAppearance(storedValue: value) == .system)
        }
        let suite = "fca.appearance.tests." + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        precondition(AppAppearance(storedValue: defaults.object(forKey: AppAppearance.storageKey)) == .system)
        for mode in AppAppearance.allCases {
            defaults.set(mode.rawValue, forKey: AppAppearance.storageKey)
            let reopened = UserDefaults(suiteName: suite)!
            precondition(AppAppearance(storedValue: reopened.object(forKey: AppAppearance.storageKey)) == mode)
        }
        defaults.set(42, forKey: AppAppearance.storageKey)
        precondition(AppAppearance(storedValue: defaults.object(forKey: AppAppearance.storageKey)) == .system)
        defaults.set("invalid", forKey: AppAppearance.storageKey)
        precondition(AppAppearance(storedValue: defaults.object(forKey: AppAppearance.storageKey)) == .system)
        for role in FCAColors.Role.allCases {
            for dark in [false, true] {
                if case .rgb(let hex) = FCAColors.value(role, dark: dark) { precondition(hex <= 0xFFFFFF) }
            }
        }
        let light: [(FCAColors.Role, UInt32)] = [(.background,0xF6F7F7),(.text,0x243341),
            (.incomingBubble,0xE9EEF0),(.selection,0xDDE5EA),(.secondaryText,0x637B97),(.border,0xD9DEE7),
            (.primaryAction,0x243341),(.outgoingBubble,0x243341),(.outgoingText,0xFFFFFF)]
        for (role, hex) in light { precondition(FCAColors.value(role, dark: false) == .rgb(hex)) }
        // Every unique migrated legacy Light RGB remains independently preserved.
        let legacy: [(FCAColors.Role, UInt32)] = [
            (.entryBackground,0xFFFFFF),(.entryHeading,0x112642),(.entryBody,0x536272),
            (.entryLink,0x536A80),(.entryNavigation,0x53677D),(.entryFootnote,0x6B7785),
            (.entryDivider,0xE2DFDC),(.entryBorder,0xD9D6D2),(.entryBackBorder,0xE5E3E0),
            (.loginBorder,0xEAE8E5),(.onboardingBorder,0xD7D9DC),(.familyControl,0xF1F5F9),
            (.retired,0x7A8795),(.retireAction,0xBD2626),(.retireBorder,0xEBCACA),
            (.historyAvailable,0x315D65),(.historyIndicator,0x279759),(.wheelBase,0xE4EBEF),
            (.wheelSurface,0xFFFFFF),(.wheelHighlight,0xFFFFFF),(.wheelLine,0xFFFFFF),
            (.dialog,0xF6F7F7),(.settingsCard,0xF6F7F7),(.sheet,0xE9EEF0),(.shadow,0x243341),(.scrim,0x243341)]
        for (role, hex) in legacy { precondition(FCAColors.value(role, dark: false) == .rgb(hex)) }
        precondition(FCAColors.value(.mapFallback, dark: false) == .mapGray)
        precondition(FCAColors.value(.systemSurface, dark: false) == .systemBackground)
        precondition(FCABranding.wordmark(dark: false) == "branding/in-app-brand/Family Car Agent Road Logo(1).png")
        precondition(FCABranding.wordmark(dark: true) == "branding/in-app-brand/fca-wordmark-dark.png")
        // WCAG text contrast for the principal Dark semantic pairings. Actual
        // raster assets, translucency and native controls still require visual QA.
        func luminance(_ role: FCAColors.Role) -> Double {
            guard case .rgb(let hex) = FCAColors.value(role, dark: true) else { preconditionFailure() }
            let channels = [16, 8, 0].map { shift -> Double in
                let v = Double((hex >> shift) & 255) / 255
                return v <= 0.04045 ? v / 12.92 : pow((v + 0.055) / 1.055, 2.4)
            }
            return channels[0]*0.2126 + channels[1]*0.7152 + channels[2]*0.0722
        }
        let readable: [(FCAColors.Role, FCAColors.Role)] = [(.text,.background),(.text,.surface),
            (.secondaryText,.surface),(.incomingText,.incomingBubble),(.outgoingText,.outgoingBubble),
            (.onPrimaryAction,.primaryAction),(.onSelection,.selection),(.onCalendarSelection,.calendarSelection),
            (.error,.surface),(.success,.surface),(.warning,.surface),(.text,.dialog),(.text,.sheet),
            (.onDestructiveAction,.destructiveAction)]
        for (foreground, background) in readable {
            let a = luminance(foreground), b = luminance(background)
            precondition((max(a,b)+0.05)/(min(a,b)+0.05) >= 4.5, "Insufficient Dark text contrast")
        }
        precondition(FCAColors.value(.calendarSelection, dark: false) == .systemBlue)
        precondition(FCAColors.value(.error, dark: false) == .systemRed)
        precondition(FCAColors.value(.background, dark: true) == .rgb(0x121A22))
        precondition(FCAColors.value(.surface, dark: true) == .rgb(0x1D2833))
        precondition(FCAColors.value(.text, dark: true) == .rgb(0xEDF2F7))
        precondition(FCAColors.value(.primaryAction, dark: true) == .rgb(0xA9CDF8))
        precondition(FCAColors.value(.outgoingBubble, dark: true) == .rgb(0x244663))
        let pairs: [(FCAColors.Role, FCAColors.Role)] = [(.onPrimaryAction, .primaryAction),
                (.incomingText,.incomingBubble),(.outgoingText,.outgoingBubble),(.onSelection,.selection),
                (.onCalendarSelection,.calendarSelection)]
        for dark in [false, true] {
            for (foreground, background) in pairs {
                precondition(FCAColors.value(foreground, dark: dark) != FCAColors.value(background, dark: dark))
            }
        }
        #if canImport(SwiftUI)
        precondition(AppAppearance.system.colorScheme == nil)
        precondition(AppAppearance.light.colorScheme == .light)
        precondition(AppAppearance.dark.colorScheme == .dark)
        defaults.removeObject(forKey: AppAppearance.storageKey)
        let rootPreference = AppStorage(wrappedValue: AppAppearance.system.rawValue, AppAppearance.storageKey, store: defaults)
        let settingsPreference = AppStorage(wrappedValue: AppAppearance.system.rawValue, AppAppearance.storageKey, store: defaults)
        precondition(AppAppearance(storedValue: rootPreference.wrappedValue) == .system)
        for mode in [AppAppearance.dark, .light, .system] {
            settingsPreference.wrappedValue = mode.rawValue
            precondition(AppAppearance(storedValue: rootPreference.wrappedValue) == mode)
            precondition(AppAppearance(storedValue: UserDefaults(suiteName: suite)!.object(forKey: AppAppearance.storageKey)) == mode)
        }
        // Selected preference remains System regardless of the effective OS scheme.
        precondition(AppAppearance(storedValue: settingsPreference.wrappedValue) == .system)
        precondition(AppAppearance(storedValue: settingsPreference.wrappedValue).colorScheme == nil)
        settingsPreference.wrappedValue = "invalid"
        precondition(AppAppearance(storedValue: rootPreference.wrappedValue).colorScheme == nil)
        #else
        print("NOT RUN: SwiftUI ColorScheme mapping requires Apple SDK")
        #endif
        #if canImport(UIKit)
        let color = FCAColors.uiColor(.background)
        let lightColor = color.resolvedColor(with: UITraitCollection(userInterfaceStyle: .light))
        let darkColor = color.resolvedColor(with: UITraitCollection(userInterfaceStyle: .dark))
        precondition(!lightColor.isEqual(darkColor))
        precondition(color.resolvedColor(with: UITraitCollection(userInterfaceStyle: .light)).isEqual(lightColor))
        for role in FCAColors.Role.allCases {
            let dynamic = FCAColors.uiColor(role)
            let light = dynamic.resolvedColor(with: UITraitCollection(userInterfaceStyle: .light))
            let dark = dynamic.resolvedColor(with: UITraitCollection(userInterfaceStyle: .dark))
            precondition(!light.isEqual(dark), "Role must adapt to appearance: \(role)")
        }
        #else
        print("NOT RUN: dynamic UIColor trait resolution requires iOS SDK/runtime")
        #endif
        print("PASS: appearance defaults, corrupt values, isolated persistence, all palette roles and Light baselines")
    }
}
