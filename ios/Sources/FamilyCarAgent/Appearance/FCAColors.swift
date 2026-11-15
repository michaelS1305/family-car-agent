#if canImport(UIKit)
import UIKit
import SwiftUI
#endif

enum FCABranding {
    static let lightWordmark = "branding/in-app-brand/Family Car Agent Road Logo(1).png"
    static let darkWordmark = "branding/in-app-brand/fca-wordmark-dark.png"
    static func wordmark(dark: Bool) -> String { dark ? darkWordmark : lightWordmark }
}

/// Adaptive presentation only. Light values preserve the existing iOS palette;
/// distinct legacy values remain separate roles rather than being normalized.
enum FCAColors {
    enum Role: CaseIterable, Sendable {
        case background, surface, elevated, text, secondaryText, mutedText
        case primaryAction, onPrimaryAction, secondaryAction, border, divider, input
        case incomingBubble, incomingText, outgoingBubble, outgoingText
        case selection, onSelection, success, warning, error, onStatus
        case calendarSelection, onCalendarSelection, calendarIndicator
        case entryBackground, entryHeading, entryBody, entryLink, entryNavigation, entryFootnote
        case entryDivider, entryBorder, entryBackBorder, loginBorder, onboardingBorder
        case mapFallback, familyControl, retired, retireAction, retireBorder
        case historyAvailable, historyIndicator, wheelBase, wheelSurface, wheelLine, wheelHighlight
        case dialog, sheet, systemSurface, settingsCard, destructiveAction, onDestructiveAction
        case shadow, scrim, link, positiveIndicator
    }
    enum Value: Equatable, Sendable {
        case rgb(UInt32), systemBlue, systemRed, systemGreen, systemBackground, mapGray
    }
    static func value(_ role: Role, dark: Bool) -> Value {
        if dark {
            switch role {
            case .background, .entryBackground: return .rgb(0x121A22)
            case .surface, .input, .systemSurface, .settingsCard, .mapFallback, .dialog: return .rgb(0x1D2833)
            case .elevated, .selection: return .rgb(0x303D49)
            case .text, .incomingText, .outgoingText, .onSelection, .entryHeading: return .rgb(0xEDF2F7)
            case .secondaryText, .entryBody, .entryNavigation, .entryFootnote: return .rgb(0xBAC8D5)
            case .mutedText, .retired: return .rgb(0xADB9C5)
            case .primaryAction, .secondaryAction, .calendarSelection, .calendarIndicator, .entryLink: return .rgb(0xA9CDF8)
            case .onPrimaryAction, .onCalendarSelection: return .rgb(0x102D4F)
            case .border, .divider, .entryDivider, .entryBorder, .entryBackBorder, .loginBorder, .onboardingBorder, .wheelLine: return .rgb(0x596B7C)
            case .incomingBubble, .sheet, .familyControl, .wheelBase: return .rgb(0x2D3945)
            case .wheelSurface: return .rgb(0x303D49)
            case .wheelHighlight: return .rgb(0x596B7C)
            case .outgoingBubble: return .rgb(0x244663)
            case .success, .historyAvailable, .historyIndicator: return .rgb(0x8BD8AD)
            case .warning: return .rgb(0xFFD18A)
            case .error, .retireAction, .destructiveAction: return .rgb(0xFFB4AB)
            case .retireBorder: return .rgb(0x8E5654)
            case .onDestructiveAction: return .rgb(0x121A22)
            case .shadow, .scrim: return .rgb(0x000000)
            case .link: return .rgb(0xA9CDF8)
            case .positiveIndicator: return .rgb(0x8BD8AD)
            // iOS semantic assignment: text on a solid light status fill.
            // For translucent status surfaces use the status color as foreground instead.
            case .onStatus: return .rgb(0x121A22)
            }
        }
        switch role {
        case .background, .dialog, .settingsCard: return .rgb(0xF6F7F7)
        case .surface, .input, .onPrimaryAction, .outgoingText, .onStatus, .onCalendarSelection: return .rgb(0xFFFFFF)
        case .elevated, .selection: return .rgb(0xDDE5EA)
        case .text, .primaryAction, .secondaryAction, .incomingText, .outgoingBubble, .onSelection: return .rgb(0x243341)
        case .secondaryText, .mutedText: return .rgb(0x637B97)
        case .border, .divider: return .rgb(0xD9DEE7)
        case .incomingBubble, .sheet: return .rgb(0xE9EEF0)
        case .success: return .rgb(0x168153)
        case .warning: return .rgb(0x9B631A)
        case .error: return .systemRed
        case .calendarSelection, .calendarIndicator: return .systemBlue
        case .entryBackground, .wheelSurface, .wheelLine, .wheelHighlight, .onDestructiveAction: return .rgb(0xFFFFFF)
        case .systemSurface: return .systemBackground
        case .entryHeading: return .rgb(0x112642)
        case .entryBody: return .rgb(0x536272)
        case .entryLink: return .rgb(0x536A80)
        case .entryNavigation: return .rgb(0x53677D)
        case .entryFootnote: return .rgb(0x6B7785)
        case .entryDivider: return .rgb(0xE2DFDC)
        case .entryBorder: return .rgb(0xD9D6D2)
        case .entryBackBorder: return .rgb(0xE5E3E0)
        case .loginBorder: return .rgb(0xEAE8E5)
        case .onboardingBorder: return .rgb(0xD7D9DC)
        case .mapFallback: return .mapGray
        case .familyControl: return .rgb(0xF1F5F9)
        case .retired: return .rgb(0x7A8795)
        case .retireAction: return .rgb(0xBD2626)
        case .retireBorder: return .rgb(0xEBCACA)
        case .historyAvailable: return .rgb(0x315D65)
        case .historyIndicator: return .rgb(0x279759)
        case .wheelBase: return .rgb(0xE4EBEF)
        case .destructiveAction: return .systemRed
        case .shadow, .scrim: return .rgb(0x243341)
        case .link: return .systemBlue
        case .positiveIndicator: return .systemGreen
        }
    }

    #if canImport(UIKit)
    // Preserve the app's existing accent in Light (including system resolution).
    static func appearanceAccent(dark: Bool) -> Color {
        dark ? color(.primaryAction) : .accentColor
    }
    static func color(_ role: Role) -> Color { Color(uiColor: uiColor(role)) }
    // Canvas needs explicit resolution from SwiftUI's effective environment.
    static func color(_ role: Role, dark: Bool) -> Color {
        Color(uiColor: uiColor(role).resolvedColor(with: UITraitCollection(userInterfaceStyle: dark ? .dark : .light)))
    }
    static func uiColor(_ role: Role) -> UIColor {
        UIColor { traits in
            switch value(role, dark: traits.userInterfaceStyle == .dark) {
            case .rgb(let hex):
                return UIColor(red: CGFloat((hex >> 16) & 255) / 255,
                               green: CGFloat((hex >> 8) & 255) / 255,
                               blue: CGFloat(hex & 255) / 255, alpha: 1)
            case .systemBlue: return UIColor.systemBlue.resolvedColor(with: traits)
            case .systemRed: return UIColor.systemRed.resolvedColor(with: traits)
            case .systemGreen: return UIColor.systemGreen.resolvedColor(with: traits)
            case .systemBackground: return UIColor.systemBackground.resolvedColor(with: traits)
            case .mapGray: return UIColor(white: 0.95, alpha: 1)
            }
        }
    }
    #endif
}
