import SwiftUI
import CoreLocation
import UserNotifications

/// Account, system permission indicators and shared logout; remaining actions stay unavailable.
struct SettingsScreen: View {
    @ObservedObject var entry: EntryModel
    let back: () -> Void
    let openFamily: () -> Void
    let openVehicles: () -> Void
    let logout: () -> Void
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.openURL) private var openURL
    @State private var locationEnabled = false
    @State private var notificationsEnabled = false
    @State private var settingsOpenFailed = false
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
                        .frame(width: 200, height: 200).offset(y: -15).frame(height: 108)
                        .accessibilityLabel("הגדרות").accessibilityAddTraits(.isHeader)
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
                        permissionRow("מיקום", icon: "location", enabled: locationEnabled)
                        Divider()
                        permissionRow("התראות", icon: "bell", enabled: notificationsEnabled)
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
                    Button(action: logout) {
                        destructive("התנתקות", icon: "logout")
                    }.buttonStyle(.plain).disabled(entry.busy)
                    destructive("מחיקת חשבון", icon: "delete_account")
                        .accessibilityHint("לא זמין בתצוגה המקדימה")
                }
                .padding(.horizontal, 18).padding(.top, 10).padding(.bottom, 24)
                .frame(maxWidth: 620).frame(maxWidth: .infinity)
            }
        }
        .background(SettingsPalette.background.ignoresSafeArea())
        .foregroundStyle(SettingsPalette.ink)
        .environment(\.layoutDirection, .rightToLeft)
        .toolbar(.hidden, for: .navigationBar)
        .alert("לא ניתן לפתוח את הגדרות המכשיר", isPresented: $settingsOpenFailed) {
            Button("הבנתי", role: .cancel) { }
        } message: {
            Text("אפשר לפתוח את הגדרות iOS ולבחור באפליקציית FCA.")
        }
        .task(id: scenePhase) {
            guard scenePhase == .active else { return }
            // Reading status does not start location monitoring or request permission.
            locationEnabled = CLLocationManager().authorizationStatus == .authorizedAlways
            let settings = await UNUserNotificationCenter.current().notificationSettings()
            guard !Task.isCancelled, scenePhase == .active else { return }
            notificationsEnabled = settings.authorizationStatus == .authorized
        }
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

    private func permissionRow(_ title: String, icon name: String, enabled: Bool) -> some View {
        Button {
            guard let url = URL(string: UIApplication.openSettingsURLString) else {
                settingsOpenFailed = true; return
            }
            openURL(url) { accepted in settingsOpenFailed = !accepted }
        } label: {
            row(title, icon: name, chevron: true, permission: enabled)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(title)
        .accessibilityValue(enabled ? "פעיל" : "לא פעיל")
        .accessibilityHint("פתיחת הגדרות ההרשאות של האפליקציה ב־iOS")
    }

    private func row(_ title: String, icon name: String, value: String? = nil,
                     detail: String? = nil, chevron: Bool = false, permission: Bool? = nil) -> some View {
        HStack(spacing: 12) {
            if chevron { Image(systemName: "chevron.left").font(.caption).accessibilityHidden(true) }
            VStack(alignment: .leading, spacing: 5) {
                Text(title).font(.body)
                if let detail { Text(detail).font(.subheadline).foregroundStyle(SettingsPalette.secondary) }
            }.frame(maxWidth: .infinity, alignment: .leading)
            if let value { Text(value).font(.body).foregroundStyle(SettingsPalette.secondary) }
            if let permission {
                // Read-only visual indicator; the containing row is the sole tap target.
                Capsule().fill(permission ? Color.green : Color(uiColor: .systemGray4))
                    .frame(width: 51, height: 31)
                    .overlay(alignment: permission ? .trailing : .leading) {
                        Circle().fill(.white).frame(width: 27, height: 27).padding(2)
                    }
                    .environment(\.layoutDirection, .leftToRight)
                    .accessibilityHidden(true)
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
