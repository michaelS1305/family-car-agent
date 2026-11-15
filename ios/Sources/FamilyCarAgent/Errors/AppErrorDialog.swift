import SwiftUI

struct ErrorPrimaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.body.weight(.semibold))
            .multilineTextAlignment(.center)
            .padding(.horizontal, 24).padding(.vertical, 12)
            .frame(maxWidth: .infinity, minHeight: 52)
            .foregroundStyle(.white)
            .background(ChatStyle.ink, in: Capsule())
            .opacity(enabled ? (configuration.isPressed ? 0.75 : 1) : 0.5)
    }
}

struct AppErrorDialog: View {
    @ObservedObject var presentation: AppErrorPresentation
    @AccessibilityFocusState private var focused: Bool
    var body: some View {
        ZStack {
            Color.black.opacity(0.22).ignoresSafeArea()
            ScrollView {
                VStack(spacing: 20) {
                    Image(systemName: presentation.kind == .offline ? "wifi.slash" : "exclamationmark.circle")
                        .font(.title).foregroundStyle(ChatStyle.secondary).accessibilityHidden(true)
                    Text(presentation.title).font(.title2.weight(.semibold))
                        .accessibilityAddTraits(.isHeader).accessibilityFocused($focused)
                    Text(presentation.message).font(.body).fixedSize(horizontal: false, vertical: true)
                    Button {
                        if presentation.stage == .failed { presentation.dismiss() }
                        else { Task { await presentation.retry() } }
                    } label: {
                        HStack(spacing: 8) {
                            if presentation.stage == .retrying { ProgressView().tint(.white) }
                            Text(presentation.stage == .failed ? "הבנתי" : "נסה שוב")
                        }
                    }
                    .buttonStyle(ErrorPrimaryButtonStyle())
                    .disabled(presentation.stage == .retrying)
                    .accessibilityValue(presentation.stage == .retrying ? "מנסה שוב" : "")
                }
                .multilineTextAlignment(.center).padding(24)
                .frame(maxWidth: 360)
                .background(ChatStyle.background, in: RoundedRectangle(cornerRadius: 24))
                .padding(24)
                .frame(maxWidth: .infinity)
            }
            .scrollBounceBehavior(.basedOnSize)
            .defaultScrollAnchor(.center)
        }
        .foregroundStyle(ChatStyle.ink)
        .environment(\.layoutDirection, .rightToLeft)
        .accessibilityAddTraits(.isModal)
        .onAppear { focused = true }
        .onChange(of: presentation.stage) { _, _ in focused = true }
        .accessibilityAction(.escape) { presentation.dismiss() }
    }
}
