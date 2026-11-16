import SwiftUI

enum ChatStyle {
    static let background = FCAColors.color(.background)
    static let ink = FCAColors.color(.text)
    static let incoming = FCAColors.color(.incomingBubble)
    static let selected = FCAColors.color(.selection)
    static let secondary = FCAColors.color(.secondaryText)
    static let border = FCAColors.color(.border)
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
    @State private var firstVehicleSetup = FirstVehicleSetupState()
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
        .allowsHitTesting(!errors.isPresented && !invitationVisible)
        .accessibilityHidden(errors.isPresented || invitationVisible)
        .overlay {
            if invitationVisible {
                FirstVehicleSetupDialog(dismiss: dismissInvitation, configure: configureFirstVehicle)
            }
        }
        .overlay { if errors.isPresented { AppErrorDialog(presentation: errors) } }
        .onChange(of: chat.historyError) { _, _ in presentHistoryError() }
        .onChange(of: chat.mode) { _, _ in errors.reset() }
        .task {
            navigation.synchronize(entry.chatIdentity); chat.enter()
            firstVehicleSetup.activate(entry.chatIdentity)
            if firstVehicleSetup.needsCheck(entry.chatIdentity) { vehicles.start() }
        }
        .onChange(of: invitationSnapshot) { _, value in firstVehicleSetup.observe(value) }
        .onChange(of: entry.chatIdentity) { _, identity in
            errors.reset()
            vehicles.stop(); navigation.synchronize(identity); chat.enter()
            bookings.synchronize()
            firstVehicleSetup.activate(identity)
            if firstVehicleSetup.needsCheck(identity) { vehicles.start() }
        }
        .onChange(of: navigation.path) { previous, path in
            errors.reset()
            if previous.contains(.vehicles) && !path.contains(.vehicles) { vehicles.stop() }
            if !path.contains(.vehicles) { navigation.vehicleHelpPresented = false }
            if navigation.isRoot && firstVehicleSetup.needsCheck(entry.chatIdentity) { vehicles.start() }
        }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillChangeFrameNotification)) { notification in
            guard let frame = notification.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect else { return }
            keyboardVisible = frame.minY < UIScreen.main.bounds.height
        }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)) { _ in keyboardVisible = false }
        .onDisappear { errors.reset(); vehicles.stop(); chat.synchronize() }
    }

    private var invitationSnapshot: FirstVehicleSetupSnapshot {
        FirstVehicleSetupSnapshot(identity: entry.chatIdentity, current: vehicles.current,
            loaded: vehicles.loaded, loading: vehicles.loading, loadError: vehicles.loadError,
            canCreate: vehicles.canCreate, vehicleCount: vehicles.rows.count,
            atRoot: navigation.isRoot, hasVehicleDestination: vehicles.destination != nil,
            blocked: entry.busy || entry.deletionBlocking || entry.deletionBusy ||
                errors.isPresented || keyboardVisible || chat.sending || chat.historyError != nil)
    }
    private var invitationVisible: Bool { firstVehicleSetup.visible(invitationSnapshot) }
    private func dismissInvitation() { firstVehicleSetup.handle(entry.chatIdentity) }
    private func configureFirstVehicle() {
        guard invitationVisible else { return }
        firstVehicleSetup.handle(entry.chatIdentity)
        chat.mode = .dashboard
        navigation.open(.vehicles)
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
            AppAssetImage(path: "icons/archive/" + asset, monochromeControl: true).frame(width: 34, height: 34)
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
    @Environment(\.colorScheme) private var colorScheme
    @ViewBuilder func body(content: Content) -> some View {
        if colorScheme == .dark {
            content.background(FCAColors.color(.surface), in: Capsule())
                .overlay(Capsule().stroke(FCAColors.color(.border)))
        } else if #available(iOS 26.0, *) {
            content.glassEffect(.regular.interactive(), in: Capsule())
        } else {
            content.background(.ultraThinMaterial, in: Capsule())
        }
    }
}
