import Foundation

// Intended canonical destinations for v1.2; website publication is a separate task.
enum PublicWebsiteDestination: String, CaseIterable {
    case terms, privacy, support, contact
    var url: URL { URL(string: "https://familycaragent.com/" + rawValue)! }
    static func allows(_ url: URL) -> Bool { allCases.contains { $0.url == url } }
}

enum EntryLegalDocument: String {
    case privacy, terms
    var url: URL { self == .privacy ? PublicWebsiteDestination.privacy.url : PublicWebsiteDestination.terms.url }
}

#if canImport(SwiftUI)
import SwiftUI

extension EntryLegalDocument {
    private static func linked(_ title: String, document: Self) -> AttributedString {
        var text = AttributedString(title)
        text.link = document.url
        text.swiftUI.underlineStyle = Text.LineStyle(pattern: .solid)
        return text
    }
    static var linkedNotice: AttributedString {
        var result = AttributedString("אנו מעבדים מידע אישי כדי לספק את Family Car Agent. מידע על המטרות, הספקים והזכויות שלך מופיע ב־ ")
        result += linked("מדיניות הפרטיות", document: .privacy)
        result += AttributedString(" וב־")
        result += linked("תנאי השימוש", document: .terms)
        result += AttributedString(".")
        return result
    }
    static var linkedAcceptance: AttributedString {
        var result = AttributedString("קראתי ואני מסכים/ה ל")
        result += linked("תנאי השימוש", document: .terms)
        result += AttributedString(", ואני מאשר/ת שקראתי את ")
        result += linked("מדיניות הפרטיות", document: .privacy)
        result += AttributedString(" של Family Car Agent.")
        return result
    }
}

private struct PublicWebsiteLinks: ViewModifier {
    @Environment(\.openURL) private var openURL
    @State private var failed = false
    func body(content: Content) -> some View {
        content.environment(\.openURL, OpenURLAction { url in
            guard PublicWebsiteDestination.allows(url) else { return .discarded }
            openURL(url) { accepted in failed = !accepted }
            return .handled
        })
        .alert("לא ניתן לפתוח את הקישור", isPresented: $failed) {
            Button("הבנתי", role: .cancel) { }
        } message: { Text("נסו שוב או פתחו את האתר בדפדפן.") }
    }
}

extension View {
    func publicWebsiteLinks() -> some View { modifier(PublicWebsiteLinks()) }
}
#endif
