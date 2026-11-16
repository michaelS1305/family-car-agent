import SwiftUI
import AuthenticationServices

struct ContentView: View {
    @StateObject private var model = EntryModel()
    @Environment(\.scenePhase) private var phase
    var body: some View {
        VStack(spacing: 0) {
            if model.deletionBlocking {
                ScrollView {
                    VStack(spacing: 20) {
                        Text("מחיקת חשבון").font(.title2.bold())
                        Text(model.deletionMessage ?? "בודקים את מצב המחיקה…")
                            .multilineTextAlignment(.center)
                        Text("אם נדרש ביטול ידני של Apple: הגדרות חשבון Apple > התחברות באמצעות Apple > FCA.")
                            .font(.footnote)
                        if model.deletionBusy { ProgressView("ממתינים…") }
                        if model.deletionCanLeave {
                            Button("חזרה לכניסה", action: model.leaveDeletionResult)
                                .buttonStyle(BookingCapsuleStyle())
                        } else {
                            if model.deletionRetryAllowed {
                            if let consequence = model.deletionPreview {
                                Text(consequence)
                                Button("אישור ושליחה מחדש של בקשת המחיקה", role: .destructive) {
                                    Task { await model.submitDeletion() }
                                }.buttonStyle(BookingCapsuleStyle(destructive: true)).disabled(model.deletionBusy)
                            } else {
                                Button("עיון בהשלכות לפני ניסיון נוסף") { Task { await model.loadDeletionPreview() } }
                                    .buttonStyle(BookingCapsuleStyle(secondary: true)).disabled(model.deletionBusy)
                            }
                        }
                        Button("בדיקת מצב המחיקה") { Task { await model.checkDeletionStatus() } }
                                .buttonStyle(BookingCapsuleStyle()).disabled(model.deletionBusy)
                        }
                    }.padding(24)
                }
            } else if model.restoring || model.screen == .bootstrap {
                BootstrapLoadingView(busy: model.restoring || model.busy, error: model.error,
                                     retry: { await model.retry() })
            } else {
            switch model.screen {
            case .intro:
                IntroScreen(enabled: !model.busy, select: model.selectRoute)
            case .login:
                LoginScreen(enabled: !model.busy, back: model.backFromEntry) { apple in
                    Task { await model.login(apple: apple) }
                }
            case .onboarding:
                if model.displayStep == 1 {
                    FamilyNameScreen(model: model)
                } else {
                    OnboardingStepsScreen(model: model)
                }
            case .success:
                OnboardingSuccessScreen(model: model)
            case .ready:
                AuthenticatedAppShell(entry: model)
            case .bootstrap:
                EmptyView() // Handled by the privacy-safe loading presentation above.
            }
            if model.busy {
                HStack {
                    ProgressView().accessibilityLabel("טוען")
                    Button("ביטול") { model.logout() }
                }.padding(8)
            }
            if let error = model.error {
                Text(error).font(.footnote).foregroundStyle(FCAColors.color(.error))
                    .multilineTextAlignment(.center).padding(.horizontal, 20).padding(.vertical, 8)
            }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(FCAColors.color(.entryBackground).ignoresSafeArea())
        .environment(\.layoutDirection, .rightToLeft)
        .task { await model.start() }
        .onChange(of: model.chatIdentity, initial: true) { _, value in NativePushService.shared.authenticatedEntry(value) }
        .onChange(of: phase) { _, value in if value == .active { Task {
            await model.resume()
            NativePushService.shared.authenticatedEntry(model.chatIdentity)
        } } }
        .onReceive(NotificationCenter.default.publisher(for: ASAuthorizationAppleIDProvider.credentialRevokedNotification)) { _ in
            Task { await model.resume() }
        }
    }
}

private struct BootstrapLoadingView: View {
    let busy: Bool
    let error: String?
    let retry: () async -> Void
    @State private var retrying = false
    var body: some View {
        VStack(spacing: 24) {
            AppAssetImage(path: ChatStyle.wordmark)
                .frame(maxWidth: 255).frame(height: 85).scaleEffect(0.9).modifier(FCAWordmarkBlend())
            if error != nil || retrying {
                Text("לא הצלחנו להתחבר כרגע. אפשר לנסות שוב.")
                    .font(.body).multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                Button {
                    guard !busy, !retrying else { return }
                    retrying = true
                    Task { await retry(); retrying = false }
                } label: {
                    HStack(spacing: 8) {
                        if retrying { ProgressView().tint(FCAColors.color(.onPrimaryAction)) }
                        Text("נסה שוב")
                    }
                }
                .buttonStyle(ErrorPrimaryButtonStyle())
                .frame(maxWidth: 260)
                .disabled(busy || retrying)
                .accessibilityValue(retrying ? "מנסה שוב" : "")
            } else if busy {
                ProgressView().accessibilityLabel("מתחברים לחשבון")
            }
        }.padding(24).frame(maxWidth: .infinity, maxHeight: .infinity)
            .foregroundStyle(ChatStyle.ink).background(ChatStyle.background.ignoresSafeArea())
    }
}
