import SwiftUI

/// Account display and existing destinations only; other settings remain unavailable.
struct SettingsScreen: View {
    @ObservedObject var entry: EntryModel
    let back: () -> Void
    let openFamily: () -> Void
    let openVehicles: () -> Void
    @State private var email: String?
    @State private var emailIdentity: ChatIdentity?

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
                    .blendMode(.multiply)
                    .accessibilityHidden(true)
                Color.clear.frame(width: 48, height: 48).accessibilityHidden(true)
            }.padding(.horizontal, 18).frame(height: 76)

            ScrollView {
                VStack(spacing: 18) {
                    AppAssetImage(path: "icons/archive/settings_icon.png")
                        .frame(width: 200, height: 200)
                        .accessibilityLabel("הגדרות").accessibilityAddTraits(.isHeader)
                    Text("אפשרויות התצוגה, ההרשאות ופעולות החשבון עדיין אינן פעילות")
                        .font(.footnote).foregroundStyle(SettingsPalette.secondary)
                        .multilineTextAlignment(.center)
                    SettingsCard(title: "חשבון") {
                        row("שם", icon: "user", value: entry.chatIdentity == nil ? "—" : entry.me?.name.split(whereSeparator: { $0.isWhitespace }).first.map(String.init) ?? "—")
                        Divider()
                        Button(action: openFamily) {
                            row("המשפחה שלי", icon: "family", detail: "פתיחת ניהול המשפחה", chevron: true)
                        }.buttonStyle(.plain)
                        Divider()
                        HStack(spacing: 12) {
                            Text(emailIdentity == entry.chatIdentity ? email ?? "—" : "—")
                                .font(.body).foregroundStyle(SettingsPalette.secondary)
                                .environment(\.layoutDirection, .leftToRight)
                                .multilineTextAlignment(.trailing)
                                .fixedSize(horizontal: false, vertical: true)
                                .frame(maxWidth: .infinity, alignment: .leading)
                            icon("envelope")
                        }.padding(.vertical, 16).accessibilityLabel("אימייל: \(emailIdentity == entry.chatIdentity ? email ?? "לא זמין" : "לא זמין")")
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
                        Button(action: openVehicles) {
                            row("זיהוי וחיבור אוטומטי", icon: "single_car", chevron: true)
                        }.buttonStyle(.plain)
                    }
                    SettingsCard(title: "תנאי שימוש ופרטיות") {
                        row("תנאי שימוש", icon: "about", chevron: true)
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
        .task(id: entry.chatIdentity) {
            email = nil; emailIdentity = nil
            guard let identity = entry.chatIdentity else { return }
            let value = try? await entry.settingsEmail(identity: identity)
            guard !Task.isCancelled, entry.chatIdentity == identity else { return }
            email = value; emailIdentity = identity
        }
    }

    private func icon(_ name: String) -> some View {
        SettingsRowIcon(name: name)
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

/// Alpha bounds measured from the unmodified 512px archive assets.
/// Normalize painted extent to the envelope's original 428/512 × 32pt extent.
private struct SettingsRowIcon: View {
    let name: String
    @ScaledMetric(relativeTo: .body) private var slot: CGFloat = 32
    private static let bounds: [String: CGRect] = [
        "envelope": CGRect(x: 20, y: 128, width: 428, height: 259),
        "user": CGRect(x: 169, y: 173, width: 174, height: 195),
        "family": CGRect(x: 131, y: 154, width: 212, height: 245),
        "theme": CGRect(x: 76, y: 95, width: 389, height: 338),
        "location": CGRect(x: 107, y: 103, width: 271, height: 318),
        "bell": CGRect(x: 85, y: 66, width: 342, height: 386),
        "single_car": CGRect(x: 116, y: 163, width: 280, height: 207),
        "about": CGRect(x: 122, y: 107, width: 270, height: 326),
        "privacy": CGRect(x: 90, y: 89, width: 332, height: 348),
        "info": CGRect(x: 82, y: 85, width: 347, height: 388),
        "support": CGRect(x: 48, y: 35, width: 428, height: 399),
        "logout": CGRect(x: 131, y: 111, width: 279, height: 294),
        "delete_account": CGRect(x: 103, y: 91, width: 315, height: 342)
    ]
    var body: some View {
        let rect = Self.bounds[name] ?? CGRect(x: 0, y: 0, width: 512, height: 512)
        let scale = (slot * 428 / 512) / max(rect.width, rect.height)
        AppAssetImage(path: "icons/archive/\(name)_icon.png")
            .frame(width: 512 * scale, height: 512 * scale)
            .offset(x: (256 - rect.midX) * scale, y: (256 - rect.midY) * scale)
            .frame(width: slot, height: slot)
            .accessibilityHidden(true)
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
