import SwiftUI
import AuthenticationServices

struct ContentView: View {
    @StateObject private var model = EntryModel()
    @Environment(\.scenePhase) private var phase
    var body: some View {
        VStack(spacing: 0) {
            if model.restoring || model.screen == .bootstrap {
                BootstrapLoadingView(busy: model.restoring || model.busy, error: model.error,
                                     retry: { Task { await model.retry() } }, exit: model.logout)
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
                Text(error).font(.footnote).foregroundStyle(.red)
                    .multilineTextAlignment(.center).padding(.horizontal, 20).padding(.vertical, 8)
            }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.white.ignoresSafeArea())
        .environment(\.layoutDirection, .rightToLeft)
        .preferredColorScheme(model.screen == .intro || model.screen == .login || model.screen == .onboarding || model.screen == .ready ? .light : nil)
        .task { await model.start() }
        .onChange(of: phase) { _, value in if value == .active { Task { await model.resume() } } }
        .onReceive(NotificationCenter.default.publisher(for: ASAuthorizationAppleIDProvider.credentialRevokedNotification)) { _ in
            Task { await model.resume() }
        }
    }
}

private struct BootstrapLoadingView: View {
    let busy: Bool
    let error: String?
    let retry: () -> Void
    let exit: () -> Void
    var body: some View {
        VStack(spacing: 24) {
            AppAssetImage(path: ChatStyle.wordmark)
                .frame(maxWidth: 255).frame(height: 85).scaleEffect(0.9).blendMode(.multiply)
            if busy { ProgressView().accessibilityLabel("מתחברים לחשבון") }
            else if error != nil {
                Text("לא הצלחנו להתחבר כרגע. אפשר לנסות שוב.")
                    .multilineTextAlignment(.center)
                Button("נסה שוב", action: retry)
                Button("חזרה לכניסה", action: exit)
            }
        }.padding(24).frame(maxWidth: .infinity, maxHeight: .infinity)
            .foregroundStyle(ChatStyle.ink).background(ChatStyle.background.ignoresSafeArea())
            .preferredColorScheme(.light)
    }
}
