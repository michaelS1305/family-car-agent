import SwiftUI

private struct ChatBottomPreference: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = nextValue() }
}

struct ChatScreen: View {
    @ObservedObject var model: ChatModel
    let userName: String
    @State private var scroll = ChatScrollPolicy()
    @State private var bottomY: CGFloat = 0
    @State private var dragging = false
    @FocusState private var composing: Bool
    private var keys: [String] { model.messages.map(\.id) + (model.sending ? ["waiting"] : []) }
    var body: some View {
        VStack(spacing: 0) {
            GeometryReader { viewport in
                ScrollViewReader { reader in
                    ScrollView {
                        VStack(spacing: 18) {
                            // Keep the first message below the unchanged wordmark at rest,
                            // while the viewport itself extends behind the top safe area.
                            Color.clear.frame(height: 100 + viewport.safeAreaInsets.top)
                            if model.historyLoading { ProgressView().accessibilityLabel("טוען שיחה") }
                            if model.historyError != nil {
                                Text("לא ניתן לטעון את השיחה כרגע").font(.footnote)
                                Button("נסה שוב", action: model.loadHistory)
                            }
                            ForEach(model.messages) { message in bubble(message) }
                            if model.sending {
                                HStack { Spacer(); Text("...").padding(.horizontal, 16).padding(.vertical, 10)
                                    .background(ChatStyle.incoming, in: RoundedRectangle(cornerRadius: 18)) }
                                    .accessibilityLabel("ממתין לתשובת הסוכן")
                            }
                            Color.clear.frame(height: 1).id("chat-bottom")
                                .background(GeometryReader { geometry in
                                    Color.clear.preference(key: ChatBottomPreference.self,
                                                           value: geometry.frame(in: .named("chat-scroll")).maxY)
                                })
                        }.padding(.horizontal, 16).padding(.bottom, 8)
                    }
                    .coordinateSpace(name: "chat-scroll")
                    .scrollDismissesKeyboard(.interactively)
                    .simultaneousGesture(DragGesture().onChanged { value in
                        dragging = true
                        if value.translation.height > 0 { scroll.userScrolled(distance: 49) }
                        else { scroll.userScrolled(distance: Double(bottomY - viewport.size.height - viewport.safeAreaInsets.top)) }
                    }.onEnded { _ in
                        dragging = false
                        scroll.userScrolled(distance: Double(bottomY - viewport.size.height - viewport.safeAreaInsets.top))
                    })
                    .onPreferenceChange(ChatBottomPreference.self) { value in
                        bottomY = value
                        if dragging { scroll.userScrolled(distance: Double(value - viewport.size.height - viewport.safeAreaInsets.top)) }
                    }
                    .onChange(of: keys) { _, next in
                        if scroll.update(next, ready: model.historyLoaded) { reader.scrollTo("chat-bottom", anchor: .bottom) }
                    }
                    .onChange(of: model.historyLoaded) { _, ready in
                        if scroll.update(keys, ready: ready) { reader.scrollTo("chat-bottom", anchor: .bottom) }
                    }
                    .onChange(of: model.scrollRequest) { _, _ in
                        scroll.sent(); reader.scrollTo("chat-bottom", anchor: .bottom)
                    }
                    .onChange(of: viewport.size.height) { _, _ in
                        if scroll.following { reader.scrollTo("chat-bottom", anchor: .bottom) }
                    }
                    .onChange(of: model.contextRevision) { _, _ in scroll = ChatScrollPolicy(); composing = false }
                    // Fade only the scrolling pixels, never paint a tinted header surface.
                    .mask(alignment: .top) {
                        VStack(spacing: 0) {
                            LinearGradient(colors: [.clear, .black], startPoint: .top, endPoint: .bottom)
                                .frame(height: 105 + viewport.safeAreaInsets.top)
                            Color.black
                        }
                    }
                    .padding(.top, -viewport.safeAreaInsets.top)
                }
                .overlay(alignment: .top) {
                        AppAssetImage(path: ChatStyle.wordmark)
                            .frame(maxWidth: 255).frame(height: 85).scaleEffect(0.9).blendMode(.multiply)
                            .frame(maxWidth: .infinity)
                            .allowsHitTesting(false).accessibilityHidden(true)
                }
            }
            if model.showSuggestions {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(ChatModel.suggestions, id: \.self) { text in
                        Button { model.draft = text } label: {
                            HStack(spacing: 5) {
                                Text("›").font(.system(size: 22))
                                Text(text).font(.system(size: 14))
                            }.frame(maxWidth: .infinity, alignment: .leading).frame(minHeight: 43)
                                .padding(.horizontal, 12)
                                .background(Color.white.opacity(0.7), in: RoundedRectangle(cornerRadius: 16))
                                .overlay(RoundedRectangle(cornerRadius: 16).stroke(ChatStyle.border, lineWidth: 1))
                        }.buttonStyle(.plain)
                    }
                }.padding(.trailing, 80).padding(.leading, 16).padding(.bottom, 24)
            }
            if let error = model.error {
                VStack(spacing: 4) {
                    Text(error.kind == .auth ? "לא ניתן לאמת את ההתחברות כרגע" : "לא ניתן להשלים את הבקשה כרגע")
                        .font(.footnote).multilineTextAlignment(.center)
                    if error.retryable && model.pending != nil {
                        TimelineView(.periodic(from: .now, by: 1)) { context in
                            Button("נסה שוב") { model.retry() }.disabled(!model.canRetry(at: context.date))
                        }
                    }
                }.padding(6)
            }
            HStack(spacing: 10) {
                TextField("", text: $model.draft, prompt: Text("איך אפשר לעזור..").foregroundColor(ChatStyle.secondary))
                    .font(.system(size: 15)).multilineTextAlignment(.trailing)
                    .environment(\.layoutDirection, .leftToRight)
                    .focused($composing).submitLabel(.send).onSubmit { model.send() }
                    .padding(.horizontal, 16).frame(height: 52)
                    .background(.white, in: Capsule()).overlay(Capsule().stroke(ChatStyle.border, lineWidth: 1))
                    .accessibilityLabel("הודעה לסוכן")
                Button { model.send() } label: {
                    Image(systemName: "arrow.up.circle").font(.system(size: 28, weight: .semibold))
                        .frame(width: 48, height: 48).background(ChatStyle.selected, in: Circle())
                }.buttonStyle(.plain).disabled(!model.canSend).accessibilityLabel("שלח הודעה")
            }.padding(.horizontal, 16).padding(.top, 8).padding(.bottom, 6)
        }
    }
    private func bubble(_ message: ChatMessage) -> some View {
        VStack(alignment: message.role == .user ? .leading : .trailing, spacing: 8) {
            Text(message.content).font(.system(size: 14)).lineSpacing(6)
                .foregroundStyle(message.role == .user ? Color.white : ChatStyle.ink)
                .padding(.horizontal, 14).padding(.vertical, 12)
                .background(message.role == .user ? ChatStyle.ink : ChatStyle.incoming,
                            in: RoundedRectangle(cornerRadius: 18))
            HStack(spacing: 5) {
                if message.role == .user { avatar }
                Text(message.timestamp, format: .dateTime.hour().minute()).font(.system(size: 10)).foregroundStyle(ChatStyle.secondary)
                if message.role == .assistant {
                    AppAssetImage(path: ChatStyle.logo).frame(width: 26, height: 26).background(.white, in: Circle())
                }
            }
            if message.delivery == .failed && message.role == .user {
                Text("ההודעה לא הושלמה").font(.system(size: 10)).foregroundStyle(ChatStyle.secondary)
            }
        }
        .frame(maxWidth: 280, alignment: message.role == .user ? .leading : .trailing)
        .frame(maxWidth: .infinity, alignment: message.role == .user ? .leading : .trailing)
    }
    private var avatar: some View {
        let words = userName.split(whereSeparator: \.isWhitespace)
        let scalars = words.count > 1 ? words.prefix(2).compactMap { $0.unicodeScalars.first } : Array(userName.trimmingCharacters(in: .whitespacesAndNewlines).unicodeScalars.prefix(2))
        return Text(String(String.UnicodeScalarView(scalars))).font(.system(size: 9, weight: .heavy))
            .frame(width: 26, height: 26).background(ChatStyle.selected, in: Circle())
            .overlay(Circle().stroke(ChatStyle.border, lineWidth: 1)).accessibilityHidden(true)
    }
}
