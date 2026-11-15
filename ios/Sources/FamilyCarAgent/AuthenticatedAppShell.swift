import SwiftUI

enum ChatStyle {
    static let background = Color(red: 246/255, green: 247/255, blue: 247/255)
    static let ink = Color(red: 36/255, green: 51/255, blue: 65/255)
    static let incoming = Color(red: 233/255, green: 238/255, blue: 240/255)
    static let selected = Color(red: 221/255, green: 229/255, blue: 234/255)
    static let secondary = Color(red: 99/255, green: 123/255, blue: 151/255)
    static let border = Color(red: 217/255, green: 222/255, blue: 231/255)
    static let wordmark = "branding/in-app-brand/Family Car Agent Road Logo(1).png"
    static let logo = "branding/app-icon/family-car-agent-logo.png"
}

struct AuthenticatedAppShell: View {
    @ObservedObject var entry: EntryModel
    @StateObject private var chat: ChatModel
    @StateObject private var vehicles: VehiclesModel
    @StateObject private var bookings: BookingModel
    @StateObject private var errors = AppErrorPresentation()
    @State private var keyboardVisible = false
    @State private var navigation = DashboardNavigation()
    init(entry: EntryModel) {
        self.entry = entry
        _chat = StateObject(wrappedValue: ChatModel(gateway: entry))
        _vehicles = StateObject(wrappedValue: VehiclesModel(gateway: entry))
        _bookings = StateObject(wrappedValue: BookingModel(gateway: entry))
    }
    var body: some View {
        NavigationStack(path: $navigation.path) {
        ZStack(alignment: .bottom) {
            ZStack {
                ChatScreen(model: chat, userName: entry.me?.name ?? "", retryHistory: retryHistory)
                    .opacity(chat.mode == .chat ? 1 : 0)
                    .allowsHitTesting(chat.mode == .chat)
                    .accessibilityHidden(chat.mode != .chat)
                if chat.mode == .dashboard {
                    DashboardScreen(name: entry.me?.name ?? "", busy: entry.busy,
                                    open: { navigation.open($0) }, logout: entry.logout)
                }
            }
            .padding(.bottom, keyboardVisible || !navigation.isRoot ? 0 : 60)
            // Floating control layer; reserve its full height so the composer stays unobscured.
            if !keyboardVisible && navigation.isRoot { AppModeBar(mode: $chat.mode).padding(.horizontal, 44).padding(.bottom, 2) }
        }
        // Paint inside NavigationStack: its system surface can obscure an outer background.
        .background(ChatStyle.background.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
        .navigationDestination(for: DashboardDestination.self) { destination in
            if destination == .family {
                FamilyScreen(entry: entry, back: { navigation.back() })
            } else if destination == .vehicles {
                VehiclesScreen(model: vehicles, back: { navigation.back() })
                    .alert("זיהוי וחיבור אוטומטי", isPresented: $navigation.vehicleHelpPresented) {
                        Button("הבנתי", role: .cancel) { navigation.vehicleHelpPresented = false }
                    } message: {
                        Text("כדי להגדיר זיהוי וחיבור אוטומטי, בחר רכב מרשימת הרכבים. ניתן להגדיר את האפשרות עבור כל רכב בנפרד.")
                    }
            } else if destination == .history {
                HistoryScreen(entry: entry, back: { navigation.back() })
            } else if destination == .bookingCenter {
                BookingCenterPreview(model: bookings, back: { navigation.back() })
            } else if destination == .settings {
                SettingsScreen(entry: entry, back: { navigation.back() },
                               openFamily: { navigation.openFromSettings(.family) },
                               openVehicles: { navigation.openFromSettings(.vehicles) }, logout: entry.logout)
            } else {
                DashboardDestinationPlaceholder(destination: destination, back: { navigation.back() })
                    .toolbar(.visible, for: .navigationBar)
            }
        }
        }
        .background(ChatStyle.background.ignoresSafeArea())
        .foregroundStyle(ChatStyle.ink)
        .preferredColorScheme(.light)
        .allowsHitTesting(!errors.isPresented)
        .accessibilityHidden(errors.isPresented)
        .overlay { if errors.isPresented { AppErrorDialog(presentation: errors) } }
        .onChange(of: chat.historyError) { _, _ in presentHistoryError() }
        .onChange(of: chat.mode) { _, _ in errors.reset() }
        .task { navigation.synchronize(entry.chatIdentity); chat.enter() }
        .onChange(of: entry.chatIdentity) { _, identity in
            errors.reset()
            vehicles.stop(); navigation.synchronize(identity); chat.enter()
            bookings.synchronize()
        }
        .onChange(of: navigation.path) { _, path in
            errors.reset()
            if !path.contains(.vehicles) { vehicles.stop(); navigation.vehicleHelpPresented = false }
        }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillChangeFrameNotification)) { notification in
            guard let frame = notification.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect else { return }
            keyboardVisible = frame.minY < UIScreen.main.bounds.height
        }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)) { _ in keyboardVisible = false }
        .onDisappear { errors.reset(); vehicles.stop(); chat.synchronize() }
    }

    // Only a read-only history load is integrated. Writes and contextual failures
    // retain their existing retry/uncertainty handling.
    private var historyDialogKind: AppErrorKind? {
        guard let failure = chat.historyError, failure.retryAfter == 0,
              failure.kind == .uncertain || (failure.kind == .unknown && (failure.status ?? 0) >= 500)
        else { return nil }
        // Chat currently erases transport details: never infer offline from uncertainty.
        return AppErrorKind.classify(status: failure.status)
    }
    private func retryHistory() {
        if historyDialogKind != nil { presentHistoryError() }
        else { chat.loadHistory() }
    }
    private func presentHistoryError() {
        guard navigation.isRoot, chat.mode == .chat, let identity = entry.chatIdentity,
              let kind = historyDialogKind else { return }
        errors.present(kind) {
            guard entry.chatIdentity == identity else { return false }
            chat.loadHistory()
            await chat.waitForOperation()
            return entry.chatIdentity == identity && chat.historyLoaded && chat.historyError == nil
        }
    }
}

struct AppModeBar: View {
    @Binding var mode: ChatModel.Mode
    var body: some View {
        HStack(spacing: 0) {
            tab(.chat, title: "צ׳אט", asset: "chat_icon.png", scale: 2.00, offset: -1.1)
            tab(.dashboard, title: "דשבורד", asset: "dashboard_icon.png", scale: 2.01, offset: 1.5)
        }
        .padding(3)
        .modifier(ModeBarGlass())
        .frame(height: 58)
    }
    private func tab(_ value: ChatModel.Mode, title: String, asset: String, scale: CGFloat, offset: CGFloat) -> some View {
        Button { mode = value } label: {
            // Display the entire original PNG, including lettering. Match the previous
            // cropped artwork's pixel scale and center without changing the control layout.
            AppAssetImage(path: "icons/archive/" + asset).frame(width: 34, height: 34)
            .scaleEffect(scale)
            .offset(y: offset)
            .frame(maxWidth: .infinity).frame(height: 50)
            .background(mode == value ? ChatStyle.selected.opacity(0.35) : .clear, in: Capsule())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title)
        .accessibilityAddTraits(mode == value ? .isSelected : [])
    }
}

private struct ModeBarGlass: ViewModifier {
    @ViewBuilder func body(content: Content) -> some View {
        if #available(iOS 26.0, *) {
            content.glassEffect(.regular.interactive(), in: Capsule())
        } else {
            content.background(.ultraThinMaterial, in: Capsule())
        }
    }
}
