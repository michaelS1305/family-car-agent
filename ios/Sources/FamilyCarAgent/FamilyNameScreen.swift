import SwiftUI

/// The first onboarding step only. Networking and validation remain in EntryModel.
struct FamilyNameScreen: View {
    @ObservedObject var model: EntryModel
    @FocusState private var nameFocused: Bool

    private let ink = Color(red: 17/255, green: 38/255, blue: 66/255)

    var body: some View {
        GeometryReader { geometry in
            let compact = geometry.size.height < 620
            ScrollView {
                VStack(spacing: 0) {
                    EntryBackHeader(title: "1 מתוך \(model.totalSteps)", back: model.backFromEntry)
                        .disabled(model.busy)
                    Text(model.route == .join ? "לאיזו משפחה מצטרפים?" : "איך קוראים למשפחה?")
                        .font(.system(size: 28, weight: .bold))
                        .multilineTextAlignment(.center).foregroundStyle(ink)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.top, compact ? 24 : 48)
                    VStack(alignment: .leading, spacing: 7) {
                        Text("שם המשפחה").font(.system(size: 16, weight: .semibold)).foregroundStyle(ink)
                        TextField("לדוגמה: כהן", text: $model.familyName)
                            .font(.system(size: 18)).foregroundStyle(ink)
                            .multilineTextAlignment(.trailing)
                            .environment(\.layoutDirection, .leftToRight)
                            .padding(.horizontal, 12).frame(minHeight: 54)
                            .overlay(RoundedRectangle(cornerRadius: 16)
                                .stroke(Color(red: 215/255, green: 217/255, blue: 220/255)))
                            .accessibilityLabel("שם המשפחה")
                            .focused($nameFocused).submitLabel(.next)
                            .onSubmit(continueFlow).disabled(model.busy)
                    }.padding(.top, compact ? 24 : 52)
                    Spacer(minLength: 32)
                    Button(action: continueFlow) {
                        Text("המשך").font(.system(size: 18, weight: .semibold))
                            .frame(maxWidth: .infinity, minHeight: 54)
                            .foregroundStyle(.white)
                            .background(Color(red: 36/255, green: 51/255, blue: 65/255),
                                        in: RoundedRectangle(cornerRadius: 16))
                    }.buttonStyle(.plain).disabled(model.busy)
                }
                .frame(minHeight: max(0, geometry.size.height - 24))
                .frame(maxWidth: 440).padding(.horizontal, 16).padding(.vertical, 12)
                .frame(maxWidth: .infinity)
            }.scrollDismissesKeyboard(.interactively)
        }
        .environment(\.layoutDirection, .rightToLeft)
    }

    private func continueFlow() {
        guard !model.busy else { return }
        nameFocused = false
        Task {
            // A second queued tap must not submit the next (not yet implemented) step.
            await model.next(from: 1)
        }
    }
}
