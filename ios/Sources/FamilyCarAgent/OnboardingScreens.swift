import SwiftUI

private let onboardingInk = FCAColors.color(.entryHeading)
private let onboardingSecondary = FCAColors.color(.secondaryText)
private let onboardingOutline = FCAColors.color(.onboardingBorder)

private struct OnboardingField: View {
    let title: String
    let hint: String
    @Binding var text: String
    var code = false
    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title).font(.system(size: 16, weight: .semibold))
            TextField(hint, text: $text)
                .font(.system(size: 18)).multilineTextAlignment(.trailing)
                .environment(\.layoutDirection, .leftToRight)
                .keyboardType(code ? .asciiCapable : .default)
                .textInputAutocapitalization(code ? .never : .sentences)
                .autocorrectionDisabled(code)
                .padding(.horizontal, 12).frame(minHeight: 54)
                .overlay(RoundedRectangle(cornerRadius: 16).stroke(onboardingOutline))
                .accessibilityLabel(title)
        }.foregroundStyle(onboardingInk)
    }
}

private struct OnboardingAction: View {
    let title: String
    let enabled: Bool
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Text(title).font(.system(size: 18, weight: .semibold))
                .frame(maxWidth: .infinity, minHeight: 54).foregroundStyle(FCAColors.color(.onPrimaryAction))
                .background(FCAColors.color(.primaryAction),
                            in: RoundedRectangle(cornerRadius: 16))
        }.buttonStyle(.plain).disabled(!enabled)
    }
}

struct OnboardingStepsScreen: View {
    @ObservedObject var model: EntryModel
    private var title: String {
        switch model.displayStep {
        case 2: "מה כתובת הבית?"
        case 3: "זו הכתובת הנכונה?"
        case 4 where model.route == .join: "מה קוד המשפחה?"
        default: "איך קוראים לך?"
        }
    }
    private var actionTitle: String {
        if model.displayStep == 3 { return "כן, המשך" }
        if model.displayStep == model.totalSteps { return model.route == .create ? "יצירת המשפחה" : "הצטרפות למשפחה" }
        return "המשך"
    }
    var body: some View {
        GeometryReader { geometry in
            let compact = geometry.size.height < 620
            let currentStep = model.displayStep
            ScrollView {
                VStack(spacing: 0) {
                    if model.canGoBack {
                        EntryBackHeader(title: "\(currentStep) מתוך \(model.totalSteps)") {
                            Task { await model.backOnboarding() }
                        }
                    } else {
                        Text("\(currentStep) מתוך \(model.totalSteps)")
                            .font(.system(size: 16, weight: .semibold)).foregroundStyle(onboardingSecondary)
                            .frame(maxWidth: .infinity, minHeight: 48)
                    }
                    Text(title).font(.system(size: 28, weight: .bold))
                        .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
                        .padding(.top, compact ? 24 : 48)
                    stepContent(compact: compact).padding(.top, 16).disabled(model.busy)
                    Spacer(minLength: 32)
                    OnboardingAction(title: actionTitle, enabled: !model.busy) {
                        Task { await model.next(from: currentStep) }
                    }
                    if currentStep == 3 {
                        Button { Task { await model.changeAddress() } } label: {
                            Text("שנה כתובת").font(.system(size: 18, weight: .semibold))
                                .frame(maxWidth: .infinity, minHeight: 50)
                                .overlay(RoundedRectangle(cornerRadius: 16).stroke(onboardingOutline))
                        }.buttonStyle(.plain).disabled(model.busy).padding(.top, 10)
                    }
                }
                .frame(minHeight: max(0, geometry.size.height - 24))
                .frame(maxWidth: 440).padding(.horizontal, 16).padding(.vertical, 12)
                .frame(maxWidth: .infinity)
            }.scrollDismissesKeyboard(.interactively)
        }.foregroundStyle(onboardingInk).environment(\.layoutDirection, .rightToLeft)
            .publicWebsiteLinks()
    }
    @ViewBuilder private func stepContent(compact: Bool) -> some View {
        switch model.displayStep {
        case 2:
            VStack(spacing: compact ? 16 : 30) {
                supporting("הכתובת נדרשת לאימות המשפחה ולבדיקת ניתוק הרכב האופציונלית בקרבת הבית.")
                OnboardingField(title: "כתובת הבית", hint: "תל אביב, דיזנגוף, 120", text: $model.address)
                supporting("אפשר להזין עיר, רחוב ומספר בית גם ללא פסיקים.\nבשלב הבא יש לבדוק ולאשר את הכתובת שנמצאה.")
            }
        case 3:
            VStack(spacing: 10) {
                supporting("בדקו את הפרטים לפני שממשיכים.")
                Text(model.resolvedAddress).font(.system(size: 16, weight: .semibold))
                    .multilineTextAlignment(.center).frame(maxWidth: .infinity).padding(12)
                    .overlay(RoundedRectangle(cornerRadius: 16).stroke(onboardingOutline))
                VerifiedAddressPreview(location: model.addressLocation)
                    .frame(height: compact ? 150 : 180).clipShape(RoundedRectangle(cornerRadius: 16))
            }
        case 4 where model.route == .join:
            VStack(spacing: 24) {
                supporting("הקוד בן 6 תווים מופיע במסך המשפחה של אחד מבני המשפחה.")
                OnboardingField(title: "קוד המשפחה", hint: "", text: $model.familyCode, code: true)
                supporting("שימו לב, יש מספר ניסיונות מוגבל")
            }
        default:
            VStack(spacing: 10) {
                OnboardingField(title: "השם שלך", hint: "הקלד את שמך", text: $model.userName)
                HStack(alignment: .top, spacing: 8) {
                    Button { model.consent.toggle() } label: {
                        Image(systemName: model.consent ? "checkmark.square.fill" : "square")
                            .font(.system(size: 22)).frame(minWidth: 44, minHeight: 44)
                    }.buttonStyle(.plain).accessibilityLabel(OnboardingValidation.legalAcceptance)
                        .accessibilityValue(model.consent ? "מאושר" : "לא מאושר")
                    Text(EntryLegalDocument.linkedAcceptance).font(.system(size: 11))
                        .foregroundStyle(onboardingSecondary).tint(onboardingInk)
                        .multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
                }.frame(maxWidth: .infinity, alignment: .leading).padding(12)
                    .overlay(RoundedRectangle(cornerRadius: 16).stroke(onboardingOutline))
            }
        }
    }
    private func supporting(_ text: String) -> some View {
        Text(text).font(.system(size: 16)).foregroundStyle(onboardingSecondary)
            .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
    }
}

struct OnboardingSuccessScreen: View {
    @ObservedObject var model: EntryModel
    var body: some View {
        GeometryReader { geometry in
            ScrollView {
                VStack(spacing: 24) {
                    Spacer(minLength: 36)
                    AppAssetImage(path: "branding/app-icon/family-car-agent-logo.png").frame(height: 100)
                    Text(model.route == .create ? "המשפחה נוצרה בהצלחה" : "הצטרפת למשפחה בהצלחה")
                        .font(.system(size: 28, weight: .bold)).multilineTextAlignment(.center)
                    if model.route == .create {
                        Text("קוד המשפחה:").foregroundStyle(onboardingSecondary)
                        Text(model.createdCode).font(.system(size: 30, weight: .bold))
                            .environment(\.layoutDirection, .leftToRight)
                    }
                    Spacer(minLength: 40)
                    OnboardingAction(title: "המשך", enabled: !model.busy, action: model.enter)
                }.frame(minHeight: max(0, geometry.size.height - 24))
                    .frame(maxWidth: 440).padding(.horizontal, 16).padding(.vertical, 12).frame(maxWidth: .infinity)
            }
        }.foregroundStyle(onboardingInk)
    }
}
