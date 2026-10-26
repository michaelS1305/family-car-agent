import SwiftUI
import AuthenticationServices

struct ContentView: View {
    @StateObject private var model = EntryModel()
    @Environment(\.scenePhase) private var phase
    var body: some View {
        VStack(spacing: 0) {
            switch model.screen {
            case .intro:
                IntroScreen(enabled: !model.busy, select: model.selectRoute)
            case .login:
                LoginScreen(enabled: !model.busy, back: model.backFromEntry) { apple in
                    Task { await model.login(apple: apple, previewOnboarding: true) }
                }
            case .onboarding:
                OnboardingPlaceholder(route: model.route, back: model.backFromEntry)
            case .bootstrap, .success, .ready:
                Form {
                    Text("Family Car Agent · Dev").font(.headline)
                    if model.screen == .bootstrap {
                        Button("נסה שוב") { Task { await model.retry() } }.disabled(model.busy)
                    } else if model.screen == .success {
                        Text("ההרשמה הושלמה")
                        if !model.createdCode.isEmpty { Text("קוד המשפחה: \(model.createdCode)") }
                        Button("המשך") { model.enter() }.disabled(model.busy)
                    } else if let account = model.me {
                        Text(account.name); Text("משפחה: \(account.family_id)")
                    }
                    Button("התנתקות / ביטול") { model.logout() }
                }
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
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.white.ignoresSafeArea())
        .environment(\.layoutDirection, .rightToLeft)
        .preferredColorScheme(model.screen == .intro || model.screen == .login || model.screen == .onboarding ? .light : nil)
        .task { await model.start() }
        .onChange(of: phase) { _, value in if value == .active { Task { await model.resume() } } }
        .onReceive(NotificationCenter.default.publisher(for: ASAuthorizationAppleIDProvider.credentialRevokedNotification)) { _ in
            Task { await model.resume() }
        }
    }
}
