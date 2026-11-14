import SwiftUI

/// Visual scaffold only. No account, permission or preference state is read or written.
struct SettingsScreen: View {
    let back: () -> Void
    @ScaledMetric(relativeTo: .body) private var iconSize = 32

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Button(action: back) {
                    Image(systemName: "chevron.right")
                        .font(.title3.weight(.semibold))
                        .frame(width: 48, height: 48)
                        .background(SettingsPalette.surface, in: Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("חזרה לדשבורד")
                AppAssetImage(path: ChatStyle.wordmark)
                    .frame(maxWidth: 240).frame(height: 58)
                    .accessibilityHidden(true)
                Color.clear.frame(width: 48, height: 48).accessibilityHidden(true)
            }.padding(.horizontal, 18).frame(height: 76)

            ScrollView {
                VStack(spacing: 18) {
                    AppAssetImage(path: "icons/archive/settings_icon.png")
                        .frame(width: 200, height: 200)
                        .accessibilityLabel("הגדרות").accessibilityAddTraits(.isHeader)
                    Text("תצוגה מקדימה — האפשרויות במסך זה עדיין אינן פעילות")
                        .font(.footnote).foregroundStyle(SettingsPalette.secondary)
                        .multilineTextAlignment(.center)
                    SettingsCard(title: "חשבון") {
                        row("שם", icon: "user", value: "—")
                        Divider()
                        row("המשפחה שלי", icon: "family", detail: "פתיחת ניהול המשפחה", chevron: true)
                        Divider()
                        row("כתובת אימייל", icon: "envelope", value: "—")
                    }
                    SettingsCard(title: "תצוגה") {
                        HStack(spacing: 12) {
                            HStack(spacing: 0) {
                                ForEach(["מערכת", "בהיר", "כהה"], id: \.self) { title in
                                    Text(title).font(.body)
                                        .frame(maxWidth: .infinity).padding(.vertical, 12)
                                        .foregroundStyle(title == "בהיר" ? Color.white : SettingsPalette.ink)
                                        .background(title == "בהיר" ? SettingsPalette.accent : .clear,
                                                    in: RoundedRectangle(cornerRadius: 14))
                                }
                            }.padding(4).background(SettingsPalette.selection, in: RoundedRectangle(cornerRadius: 18))
                            icon("theme")
                        }.padding(.vertical, 10)
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel("תצוגה: מערכת, בהיר, כהה. תצוגה מקדימה בלבד; בחירה אינה זמינה")
                    }
                    SettingsCard(title: "הרשאות") {
                        row("מיקום", icon: "location", chevron: true, permission: true)
                        Divider()
                        row("התראות", icon: "bell", chevron: true, permission: true)
                        Divider()
                        row("זיהוי וחיבור אוטומטי", icon: "car", chevron: true)
                    }
                    SettingsCard(title: "תנאי שימוש ופרטיות") {
                        row("תנאי שימוש", icon: "history", chevron: true)
                        Divider()
                        row("מדיניות פרטיות", icon: "privacy", chevron: true)
                    }
                    SettingsCard(title: "אודות") {
                        row("גרסת האפליקציה", icon: "info",
                            value: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "—")
                        Divider()
                        row("צור קשר לתמיכה", icon: "support", chevron: true)
                    }
                    destructive("התנתקות", icon: "logout")
                    destructive("מחיקת חשבון", icon: "delete_account")
                }
                .padding(.horizontal, 18).padding(.bottom, 24)
                .frame(maxWidth: 620).frame(maxWidth: .infinity)
            }
        }
        .background(SettingsPalette.background.ignoresSafeArea())
        .foregroundStyle(SettingsPalette.ink)
        .environment(\.layoutDirection, .rightToLeft)
        .toolbar(.hidden, for: .navigationBar)
    }

    private func icon(_ name: String) -> some View {
        AppAssetImage(path: "icons/archive/\(name)_icon.png")
            .frame(width: iconSize, height: iconSize).accessibilityHidden(true)
    }

    private func row(_ title: String, icon name: String, value: String? = nil,
                     detail: String? = nil, chevron: Bool = false, permission: Bool = false) -> some View {
        HStack(spacing: 12) {
            if chevron { Image(systemName: "chevron.left").font(.caption).accessibilityHidden(true) }
            VStack(alignment: .leading, spacing: 5) {
                Text(title).font(.body)
                if let detail { Text(detail).font(.subheadline).foregroundStyle(SettingsPalette.secondary) }
            }.frame(maxWidth: .infinity, alignment: .leading)
            if let value { Text(value).font(.body).foregroundStyle(SettingsPalette.secondary) }
            if permission {
                // Deliberately unavailable: this is not the actual OS permission state.
                Toggle(title, isOn: .constant(false)).labelsHidden().disabled(true)
                    .accessibilityLabel("\(title): לא זמין בתצוגה המקדימה")
            }
            icon(name)
        }.padding(.vertical, 16)
    }

    private func destructive(_ title: String, icon name: String) -> some View {
        row(title, icon: name, chevron: true)
            .foregroundStyle(SettingsPalette.destructive)
            .padding(.horizontal, 16)
            .background(SettingsPalette.destructive.opacity(0.06), in: RoundedRectangle(cornerRadius: 18))
            .overlay(RoundedRectangle(cornerRadius: 18).stroke(SettingsPalette.destructive.opacity(0.18)))
            .accessibilityElement(children: .combine)
            .accessibilityHint("לא זמין בתצוגה המקדימה")
    }
}

private struct SettingsCard<Content: View>: View {
    let title: String
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(title).font(.title2.weight(.bold)).padding(.vertical, 14)
                .accessibilityAddTraits(.isHeader)
            Divider()
            content
        }
        .padding(.horizontal, 16)
        .background(SettingsPalette.background, in: RoundedRectangle(cornerRadius: 24))
        .overlay(RoundedRectangle(cornerRadius: 24).stroke(SettingsPalette.border))
    }
}

/// Semantic roles keep future appearance support local; the existing shell stays light.
private enum SettingsPalette {
    static let background = ChatStyle.background
    static let surface = Color(uiColor: .systemBackground)
    static let ink = ChatStyle.ink
    static let secondary = ChatStyle.secondary
    static let border = ChatStyle.border
    static let selection = ChatStyle.selected
    static let accent = Color.accentColor
    static let destructive = Color(uiColor: .systemRed)
}
