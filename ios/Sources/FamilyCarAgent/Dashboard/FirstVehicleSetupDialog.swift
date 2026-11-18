import SwiftUI

struct FirstVehicleSetupDialog: View {
    let dismiss: () -> Void
    let configure: () -> Void
    @AccessibilityFocusState private var focused: Bool

    var body: some View {
        ZStack {
            Color.black.opacity(0.4).ignoresSafeArea()
            ScrollView {
                VStack(spacing: 20) {
                    HStack {
                        Button(action: dismiss) {
                            Image(systemName: "chevron.left")
                                .font(.body.weight(.semibold))
                                .frame(width: 44, height: 44)
                                .background(FCAColors.color(.selection), in: Circle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("סגירת ההזמנה להגדרת רכב")
                        Spacer()
                    }
                    .environment(\.layoutDirection, .leftToRight)
                    Text("שנתחבר?").font(.largeTitle.bold())
                        .accessibilityAddTraits(.isHeader).accessibilityFocused($focused)
                    Text("זה לוקח דקה והסוכן מחובר לרכב ומעדכן אוטומטית")
                        .font(.title3).fixedSize(horizontal: false, vertical: true)
                    AppAssetImage(path: "illustrations/first_vehicle_setup.png")
                        .aspectRatio(1672.0 / 941.0, contentMode: .fit)
                        .accessibilityHidden(true)
                        .environment(\.layoutDirection, .leftToRight)
                    Button(action: configure) {
                        HStack(spacing: 12) {
                            Text("להגדרה")
                            Image(systemName: "chevron.right").accessibilityHidden(true)
                        }
                        .environment(\.layoutDirection, .leftToRight)
                    }
                    .buttonStyle(ErrorPrimaryButtonStyle())
                }
                .multilineTextAlignment(.center).padding(24)
                .frame(maxWidth: 420)
                .background(FCAColors.color(.dialog), in: RoundedRectangle(cornerRadius: 30))
                .overlay(RoundedRectangle(cornerRadius: 30).stroke(FCAColors.color(.border)))
                .padding(24).frame(maxWidth: .infinity)
            }
            .scrollBounceBehavior(.basedOnSize)
            .defaultScrollAnchor(.center)
        }
        .foregroundStyle(FCAColors.color(.text))
        .environment(\.layoutDirection, .rightToLeft)
        .accessibilityAddTraits(.isModal)
        .accessibilityAction(.escape, dismiss)
        .onAppear { focused = true }
    }
}
