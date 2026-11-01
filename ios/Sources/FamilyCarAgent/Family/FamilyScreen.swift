import SwiftUI
import UIKit

struct FamilyScreen: View {
    @ObservedObject var entry: EntryModel
    @StateObject private var model: FamilyModel
    let back: () -> Void
    @State private var copied = false
    @State private var confirmCode = false
    init(entry: EntryModel, back: @escaping () -> Void) {
        self.entry = entry; self.back = back
        _model = StateObject(wrappedValue: FamilyModel(gateway: entry))
    }
    var body: some View {
        VStack(spacing: 0) {
            ZStack {
                AppAssetImage(path: ChatStyle.wordmark).frame(width: 220, height: 58)
                    .blendMode(.multiply).accessibilityHidden(true)
                HStack {
                    circle("chevron.right", label: "חזרה לדשבורד", action: back)
                    Spacer()
                }
            }.frame(height: 76).padding(.horizontal, 18)
            ScrollView {
                VStack(spacing: 18) {
                    AppAssetImage(path: "icons/archive/family_icon.png")
                        .frame(width: 200, height: 200).offset(y: -15)
                        .frame(height: 108).accessibilityLabel("משפחה")
                    if let profile = model.visibleProfile {
                        members(profile)
                        address(profile)
                        code(profile)
                    } else if model.loading {
                        ProgressView("טוען…").padding(24)
                    }
                    if model.loadError {
                        Text("לא ניתן לטעון את פרטי המשפחה")
                        Button("נסה שוב", action: model.refresh)
                    }
                }.padding(.horizontal, 18).padding(.vertical, 10).frame(maxWidth: 620)
                    .frame(maxWidth: .infinity)
            }.scrollDismissesKeyboard(.interactively)
        }
        .background(ChatStyle.background.ignoresSafeArea()).foregroundStyle(ChatStyle.ink)
        .environment(\.layoutDirection, .rightToLeft).preferredColorScheme(.light)
        .toolbar(.hidden, for: .navigationBar)
        .task { model.start() }
        .onChange(of: entry.familyIdentity) { _, _ in copied = false; confirmCode = false; model.start() }
        .onDisappear { copied = false; confirmCode = false; model.stop() }
        .task(id: copied) {
            guard copied else { return }
            try? await Task.sleep(for: .seconds(2.5))
            if !Task.isCancelled { copied = false }
        }
        .sheet(isPresented: Binding(get: { model.current && model.invitation != nil }, set: { if !$0 { model.closeShare() } })) {
            if let message = model.invitation, model.current { FamilyShareSheet(message: message) }
        }
        .confirmationDialog("הקוד הישן יפסיק לעבוד. ליצור קוד חדש?", isPresented: $confirmCode, titleVisibility: .visible) {
            Button("אשר", action: model.regenerate)
            Button("ביטול", role: .cancel) { model.codeConfirmation = false }
        }
    }
    private func members(_ profile: FamilyProfile) -> some View {
        panel {
            HStack {
                Text("אנשי המשפחה").font(.system(size: 21, weight: .bold))
                Spacer()
                circle("plus", label: "הזמנת בן משפחה", action: model.share)
                    .disabled(model.loading || model.loadError || model.codePending || model.invitation != nil)
            }
            if profile.members.isEmpty { Text("אין בני משפחה להצגה") }
            ForEach(profile.members) { member in
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 9) {
                        Text(initials(member.name)).font(.system(size: 16, weight: .heavy))
                            .frame(width: 44, height: 44).background(ChatStyle.selected, in: Circle())
                            .overlay(Circle().stroke(ChatStyle.border)).accessibilityHidden(true)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(member.name).font(.system(size: 17, weight: .bold))
                            if member.admin { Text("מנהל המשפחה").font(.system(size: 12)).foregroundStyle(ChatStyle.secondary) }
                        }.frame(maxWidth: .infinity, alignment: .leading)
                        if profile.can_edit_roles {
                            Menu {
                                ForEach(FamilyRole.allCases, id: \.self) { role in
                                    Button(role.label) { model.role(member.id, role) }
                                }
                            } label: {
                                Text(model.rolePending.contains(member.id) ? "מעדכן…" : member.role.label + " ▾")
                                    .font(.system(size: 12)).padding(6)
                                    .overlay(RoundedRectangle(cornerRadius: 11).stroke(ChatStyle.border))
                            }.disabled(!model.canManage || model.rolePending.contains(member.id))
                                .accessibilityLabel("שינוי תפקיד עבור \(member.name)")
                        } else { Text(member.role.label).font(.system(size: 12)) }
                    }.frame(minHeight: 60)
                    if model.roleErrors.contains(member.id) { Text("לא ניתן לעדכן את התפקיד. נסו שוב.").font(.caption).foregroundStyle(.red) }
                }.padding(10).background(.white.opacity(0.85), in: RoundedRectangle(cornerRadius: 18))
                    .overlay(RoundedRectangle(cornerRadius: 18).stroke(ChatStyle.border))
            }
        }
    }
    private func address(_ profile: FamilyProfile) -> some View {
        panel {
            HStack {
                Text("כתובת").font(.system(size: 21, weight: .bold))
                Spacer()
                if profile.can_edit_roles && model.stage == .view {
                    Button("עריכה", action: model.editAddress).disabled(!model.canManage)
                }
            }
            if model.stage == .view {
                Text(profile.home_address).font(.system(size: 20)).frame(maxWidth: .infinity, alignment: .leading)
                    .padding(14).overlay(RoundedRectangle(cornerRadius: 16).stroke(ChatStyle.border))
            } else if model.stage == .edit || model.stage == .verifying {
                TextField("עיר, רחוב ומספר בית", text: Binding(get: { model.draft }, set: model.changeDraft), axis: .vertical)
                    .multilineTextAlignment(.trailing).environment(\.layoutDirection, .leftToRight)
                    .padding(12).frame(minHeight: 54)
                    .overlay(RoundedRectangle(cornerRadius: 16).stroke(ChatStyle.border))
                    .disabled(model.addressBusy).accessibilityLabel("כתובת הבית")
                HStack {
                    Button(model.addressBusy ? "בודק…" : "אשר", action: model.verifyAddress)
                    Button("ביטול", action: model.cancelAddress)
                }.disabled(model.addressBusy || !model.canManage)
            } else {
                Text("זו הכתובת הנכונה?").fontWeight(.bold)
                Text(model.candidate?.display_address ?? "")
                VerifiedAddressPreview(location: model.candidate?.location)
                    .frame(height: 180).clipShape(RoundedRectangle(cornerRadius: 16))
                    .accessibilityLabel("מפת הכתובת המאומתת")
                HStack {
                    Button(model.addressBusy ? "ממתינים…" : "אשר", action: model.confirmAddress)
                    Button("שנה כתובת", action: model.reviseAddress)
                    Button("ביטול", action: model.cancelAddress)
                }.disabled(model.addressBusy || !model.canManage)
            }
            if let error = model.addressError { Text(error).font(.caption).foregroundStyle(.red) }
        }
    }
    private func code(_ profile: FamilyProfile) -> some View {
        panel {
            Text("קוד משפחתי").font(.system(size: 21, weight: .bold))
            HStack {
                Text(profile.family_code).font(.system(size: 30, weight: .bold)).tracking(4)
                    .environment(\.layoutDirection, .leftToRight).frame(maxWidth: .infinity)
                circle("doc.on.doc", label: "העתקת קוד משפחתי") {
                    guard let code = model.copyCode() else { return }
                    UIPasteboard.general.setItems([[UIPasteboard.typeAutomatic: code]],
                        options: [.localOnly: true, .expirationDate: Date().addingTimeInterval(120)])
                    copied = true
                }.disabled(model.loading || model.loadError || model.codePending)
            }.padding(12).overlay(RoundedRectangle(cornerRadius: 18).stroke(ChatStyle.border))
            if copied { Text("הקוד הועתק").font(.caption) }
            if profile.can_edit_roles {
                Button(model.codePending ? "ממתינים…" : "יצירת קוד חדש") {
                    model.askRegenerate(); confirmCode = model.codeConfirmation
                }
                    .disabled(!model.canManage || model.codePending || model.invitation != nil)
            }
            if model.codeError { Text("לא ניתן לאשר יצירת קוד חדש. נסו שוב.").font(.caption).foregroundStyle(.red) }
        }
    }
    private func panel<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10, content: content).frame(maxWidth: .infinity, alignment: .leading)
            .padding(14).background(.white.opacity(0.72), in: RoundedRectangle(cornerRadius: 18))
            .overlay(RoundedRectangle(cornerRadius: 18).stroke(ChatStyle.border))
    }
    private func circle(_ symbol: String, label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 23)).frame(width: 48, height: 48)
                .background(Color(red: 241/255, green: 245/255, blue: 249/255), in: Circle())
        }.buttonStyle(.plain).accessibilityLabel(label)
    }
    private func initials(_ name: String) -> String {
        let parts = name.split(whereSeparator: { $0.isWhitespace })
        return parts.count > 1 ? parts.prefix(2).compactMap(\.first).map(String.init).joined() : String(name.prefix(2))
    }
}

private struct FamilyShareSheet: UIViewControllerRepresentable {
    let message: String
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [message], applicationActivities: nil)
    }
    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}
