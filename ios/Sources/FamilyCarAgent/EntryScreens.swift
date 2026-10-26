import SwiftUI
import AuthenticationServices
import UIKit

private let entryInk = Color(red: 36/255, green: 51/255, blue: 65/255)
private let entrySecondary = Color(red: 99/255, green: 123/255, blue: 151/255)

// Raw resources are copied by SwiftPM, never sent through actool.
private struct EntryImage: View {
    let name: String
    private static func load(_ name: String) -> UIImage {
        guard let url = Bundle.module.url(forResource: name, withExtension: "png", subdirectory: "EntryAssets"),
              let image = UIImage(contentsOfFile: url.path) else {
            assertionFailure("Missing packaged entry image")
            return UIImage()
        }
        return image
    }
    var body: some View {
        Image(uiImage: Self.load(name)).resizable().scaledToFit().accessibilityHidden(true)
    }
}

// Measure actual SwiftUI text before distributing the spare safe-area height.
// The enclosing ScrollView handles large accessibility fonts / short landscape viewports.
private struct IntroColumn: Layout {
    let viewport: CGFloat
    private let weights: [CGFloat] = [0.12, 0.07, 0.13, 0.13, 0.09, 0.34, 0]
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 320
        let height = subviews.reduce(CGFloat.zero) { $0 + $1.sizeThatFits(.init(width: width, height: nil)).height }
        return CGSize(width: width, height: max(viewport, height + 24))
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let sizes = subviews.map { $0.sizeThatFits(.init(width: bounds.width, height: nil)) }
        let spare = max(0, bounds.height - sizes.reduce(0) { $0 + $1.height })
        var y = bounds.minY
        for (index, view) in subviews.enumerated() {
            y += spare * weights[index]
            view.place(at: CGPoint(x: bounds.midX, y: y), anchor: .top,
                       proposal: .init(width: bounds.width, height: sizes[index].height))
            y += sizes[index].height
        }
    }
}

struct IntroScreen: View {
    let enabled: Bool
    let select: (LoginRoute) -> Void
    @Environment(\.dynamicTypeSize) private var dynamicType
    var body: some View {
        GeometryReader { geometry in
            let compact = geometry.size.height < 560
            ScrollView {
                IntroColumn(viewport: geometry.size.height) {
                    EntryImage(name: "intro_logo").frame(height: compact ? 96 : 126)
                    Text("Family Car Agent")
                        .font(.system(size: compact ? 30 : 34, weight: .bold))
                        .lineLimit(1).minimumScaleFactor(0.65)
                        .environment(\.layoutDirection, .leftToRight)
                    Capsule().fill(Color(red: 226/255, green: 223/255, blue: 220/255))
                        .frame(width: 80, height: 2).frame(maxWidth: .infinity)
                    VStack(spacing: 0) {
                        Text("הדרך החכמה")
                        Text("לנהל את הרכב המשפחתי")
                    }
                    .font(.system(size: compact ? 26 : 29, weight: .bold))
                    .lineLimit(1).minimumScaleFactor(0.65)
                    Text("בדקו מי עם הרכב, נהלו הזמנות וקבלו עדכונים עם סוכן אישי")
                        .font(dynamicType.isAccessibilitySize ? .body : .system(size: compact ? 15 : 16, weight: .medium))
                        .foregroundStyle(Color(red: 83/255, green: 98/255, blue: 114/255))
                        .lineSpacing(6).fixedSize(horizontal: false, vertical: true)
                    HStack(spacing: 10) {
                        routeButton("יצירת\nמשפחה", symbol: "plus.circle", route: .create)
                        routeButton("הצטרפות\nלמשפחה", symbol: "person.crop.circle", route: .join)
                    }
                    Button { select(.existing) } label: {
                        Text("כבר יש לי חשבון").underline()
                            .font(.system(size: 15, weight: .medium))
                            .foregroundStyle(Color(red: 83/255, green: 106/255, blue: 128/255))
                            .frame(minHeight: 48)
                    }
                }
                .frame(maxWidth: 408).padding(.horizontal, 16).frame(maxWidth: .infinity)
            }.scrollIndicators(.hidden).disabled(!enabled)
        }
        .foregroundStyle(entryInk).multilineTextAlignment(.center)
    }
    private func routeButton(_ text: String, symbol: String, route: LoginRoute) -> some View {
        Button { select(route) } label: {
            HStack(spacing: 6) {
                Image(systemName: symbol).font(.system(size: 22, weight: .regular)).accessibilityHidden(true)
                Text(text).font(.system(size: 16, weight: .semibold)).lineLimit(2)
                    .minimumScaleFactor(0.8).frame(maxWidth: .infinity)
            }
            .padding(.horizontal, 8).padding(.vertical, 8).frame(maxWidth: .infinity, minHeight: 60)
            .contentShape(RoundedRectangle(cornerRadius: 16))
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color(red: 217/255, green: 214/255, blue: 210/255), lineWidth: 1))
        }.buttonStyle(.plain).accessibilityLabel(route.title)
    }
}

private struct EntryBackHeader: View {
    let title: String
    let back: () -> Void
    var body: some View {
        Text(title).font(.system(size: 16, weight: .semibold))
            .foregroundStyle(Color(red: 83/255, green: 103/255, blue: 125/255))
            .frame(maxWidth: .infinity, minHeight: 48)
            .overlay(alignment: .leading) {
                Button(action: back) {
                    Image(systemName: "arrow.right").font(.system(size: 25)).foregroundStyle(entryInk)
                        .frame(width: 48, height: 48)
                        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Color(red: 229/255, green: 227/255, blue: 224/255)))
                }.buttonStyle(.plain).accessibilityLabel("חזרה")
            }
    }
}

// Apple's native branded control, wired to the EXISTING provider rather than a
// second SignInWithAppleButton request/completion implementation.
private struct AppleProviderButton: UIViewRepresentable {
    let enabled: Bool
    let action: () -> Void
    func makeCoordinator() -> Coordinator { Coordinator(action) }
    func makeUIView(context: Context) -> ASAuthorizationAppleIDButton {
        let button = ASAuthorizationAppleIDButton(type: .signIn, style: .black)
        button.cornerRadius = 24
        button.addTarget(context.coordinator, action: #selector(Coordinator.tap), for: .touchUpInside)
        return button
    }
    func updateUIView(_ uiView: ASAuthorizationAppleIDButton, context: Context) {
        uiView.isEnabled = enabled; context.coordinator.action = action
    }
    @MainActor final class Coordinator: NSObject {
        var action: () -> Void
        init(_ action: @escaping () -> Void) { self.action = action }
        @objc func tap() { action() }
    }
}

struct LoginScreen: View {
    let enabled: Bool
    let back: () -> Void
    let login: (Bool) -> Void
    @State private var legal: EntryLegalDocument?
    @Environment(\.dynamicTypeSize) private var dynamicType
    var body: some View {
        GeometryReader { geometry in
            let compact = geometry.size.height < 740 || dynamicType.isAccessibilitySize
            let width = min(max(0, geometry.size.width - 32), 440)
            let buttonHeight = max(48, (width - 32) / 4.5)
            VStack(spacing: 8) {
                EntryBackHeader(title: "התחברות", back: back).disabled(!enabled)
                ScrollView {
                    VStack(spacing: 0) {
                        Spacer(minLength: 0)
                        VStack(spacing: compact ? 12 : 20) {
                            EntryImage(name: "login_logo").frame(height: compact ? 70 : 114)
                            Text("מתחברים וממשיכים")
                                .font(.system(size: compact ? 26 : 30, weight: .bold))
                                .foregroundStyle(entryInk).lineLimit(1).minimumScaleFactor(0.75)
                            Text("כדי להשלים את החיבור והזיהוי שלכם, התחברו עם חשבונכם האישי")
                                .font(dynamicType.isAccessibilitySize ? .body : .system(size: compact ? 15 : 17))
                                .foregroundStyle(entrySecondary).lineSpacing(5)
                                .fixedSize(horizontal: false, vertical: true)
                            VStack(spacing: 10) {
                                Button { login(false) } label: {
                                    EntryImage(name: "google_sign_in").frame(maxWidth: .infinity)
                                        .frame(height: buttonHeight).contentShape(Capsule())
                                }.buttonStyle(.plain).accessibilityLabel("התחברות באמצעות Google").disabled(!enabled)
                                AppleProviderButton(enabled: enabled) { login(true) }
                                    .frame(maxWidth: .infinity).frame(height: buttonHeight)
                            }
                            VStack(spacing: 6) {
                                Text("פרטי ההתחברות נשמרים ומנוהלים על ידי Supabase Auth.")
                                Text(EntryLegalDocument.linkedNotice)
                                    .tint(Color(red: 17/255, green: 38/255, blue: 66/255))
                                    .environment(\.openURL, OpenURLAction { url in
                                        guard let document = EntryLegalDocument(link: url) else { return .discarded }
                                        legal = document; return .handled
                                    })
                            }
                            .font(dynamicType.isAccessibilitySize ? .footnote : .system(size: 11.5))
                            .foregroundStyle(Color(red: 107/255, green: 119/255, blue: 133/255))
                            .lineSpacing(4).fixedSize(horizontal: false, vertical: true)
                        }
                        .frame(maxWidth: .infinity).padding(.horizontal, 16).padding(.vertical, compact ? 10 : 18)
                        .background(Color.white)
                        .overlay(RoundedRectangle(cornerRadius: 26).stroke(Color(red: 234/255, green: 232/255, blue: 229/255)))
                        Spacer(minLength: 0)
                    }.frame(minHeight: max(0, geometry.size.height - 72))
                }.scrollIndicators(.hidden)
            }.padding(.top, 8).frame(width: width).frame(maxWidth: .infinity)
        }
        .multilineTextAlignment(.center)
        .sheet(item: $legal) { document in
            NavigationStack {
                ScrollView { Text(document.body).frame(maxWidth: .infinity, alignment: .leading).padding(20) }
                    .navigationTitle(document.title).navigationBarTitleDisplayMode(.inline)
                    .toolbar { ToolbarItem(placement: .confirmationAction) { Button("סגור") { legal = nil } } }
            }.environment(\.layoutDirection, .rightToLeft)
        }
    }
}

struct OnboardingPlaceholder: View {
    let route: LoginRoute
    let back: () -> Void
    var body: some View {
        VStack(spacing: 24) {
            EntryBackHeader(title: route.title, back: back)
            Spacer()
            Text("תהליך ההצטרפות יתווסף בהמשך").font(.title2.bold())
            Text("זהו מסך זמני. לא נוצרו משפחה או חברות במשפחה.").font(.body)
            Button("חזרה להתחברות", action: back).frame(minHeight: 44)
            Spacer()
        }.padding(16).foregroundStyle(entryInk).multilineTextAlignment(.center)
    }
}
