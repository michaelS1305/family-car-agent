import SwiftUI

struct AddVehicleScreen: View {
    @ObservedObject var model: VehiclesModel
    @FocusState private var focused: Field?
    private typealias Field = VehicleFormField
    @AccessibilityFocusState private var errorFocus: Field?
    var body: some View {
        VStack(spacing: 0) {
            VehiclesHeader { focused = nil; model.pop() }
            if model.current {
                HStack(spacing: 12) {
                    AppAssetImage(path: "icons/archive/single_car_icon.png").frame(width: 40, height: 40)
                    Text("הוספת רכב").font(.system(size: 27, weight: .bold))
                }.padding(.top, 12).padding(.bottom, 24)
                ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        field("שם הרכב", hint: "לדוגמה: הרכב של אבא", icon: "single_car_icon.png", focus: .name,
                              value: binding(\.name))
                        Text("סוג רכב").id(Field.category)
                        categoryPicker
                        fieldError(.category)
                        field("יצרן", hint: "בחרו יצרן", icon: "manufacturer_icon.png", focus: .manufacturer,
                              value: Binding(get: { model.draft.manufacturerQuery }, set: model.queryManufacturer))
                        Text("יש לבחור יצרן מתוך הרשימה").font(.footnote).foregroundStyle(ChatStyle.secondary)
                        if model.catalogLoading { ProgressView("טוען יצרנים…") }
                        if model.catalogError {
                            HStack { Text("לא ניתן לטעון יצרנים"); Button("נסה שוב", action: model.loadManufacturers) }
                        } else if model.catalogLoaded && !model.draft.manufacturerQuery.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && model.draft.manufacturer == nil {
                            if model.matchingManufacturers.isEmpty { Text("לא נמצאו יצרנים").foregroundStyle(ChatStyle.secondary) }
                            else {
                                ScrollView {
                                    LazyVStack {
                                        ForEach(model.matchingManufacturers) { manufacturer in
                                            Button { model.chooseManufacturer(manufacturer); focused = .model } label: {
                                                Text(manufacturer.name_he).frame(maxWidth: .infinity, minHeight: 44, alignment: .leading).padding(.horizontal, 12)
                                            }.disabled(!model.editable)
                                        }
                                    }
                                }.frame(height: min(144, CGFloat(model.matchingManufacturers.count) * 48))
                                    .overlay(RoundedRectangle(cornerRadius: 16).stroke(ChatStyle.border))
                            }
                        }
                        field("דגם", hint: "דגם", icon: "single_car_icon.png", focus: .model, value: binding(\.model))
                        field("מספר רכב", hint: "לדוגמה: 123-45-678", icon: "license_plate.png", focus: .plate, value: binding(\.plate))
                        if let error = model.submitError { Text(error).foregroundStyle(.red) }
                        else if !model.canCreate { Text("אין הרשאה להוספת רכב").foregroundStyle(.red) }
                        Button {
                            focused = nil; model.submit()
                            if let first = model.firstInvalidField {
                                // Scroll only for an explicit submission, after errors enter the layout.
                                DispatchQueue.main.async {
                                    guard model.current, model.destination == .add else { return }
                                    proxy.scrollTo(first, anchor: .top); errorFocus = first
                                }
                            }
                        } label: {
                            Group {
                                if model.submitting { ProgressView().tint(.white).accessibilityLabel("ממתינים לאישור הוספת הרכב") }
                                else { Text(model.pending == nil ? "הוספת רכב" : "נסה שוב").font(.system(size: 20)) }
                            }.frame(maxWidth: .infinity, minHeight: 56).foregroundStyle(.white)
                                .background(ChatStyle.ink, in: RoundedRectangle(cornerRadius: 20))
                        }.disabled(!model.maySubmit)
                        Spacer(minLength: 8)
                    }.padding(.horizontal, 20).padding(.vertical, 8).frame(maxWidth: 620).frame(maxWidth: .infinity)
                }.scrollDismissesKeyboard(.interactively)
                }
            }
        }.modifier(VehiclesAppearance())
    }
    private var categoryPicker: some View {
        HStack(spacing: 4) {
            ForEach(VehicleCategory.allCases, id: \.self) { category in
                Button {
                    var draft = model.draft; draft.category = category; model.edit(draft)
                } label: {
                    VStack(spacing: 2) {
                        AppAssetImage(path: category.asset).frame(height: 44)
                        Text(category.label).font(.system(size: 5)).lineSpacing(2).lineLimit(2)
                    }.padding(2).frame(maxWidth: .infinity).frame(height: 86)
                        .background(model.draft.category == category ? ChatStyle.selected : .white.opacity(0.6), in: RoundedRectangle(cornerRadius: 18))
                        .overlay(RoundedRectangle(cornerRadius: 18).stroke(model.fieldErrors[.category] != nil ? .red : model.draft.category == category ? ChatStyle.ink : ChatStyle.border, lineWidth: model.draft.category == category ? 2 : 1))
                }.buttonStyle(.plain).disabled(!model.editable)
                    .accessibilityLabel(category.label).accessibilityAddTraits(model.draft.category == category ? .isSelected : [])
            }
        }.environment(\.layoutDirection, .leftToRight)
    }
    private func binding(_ key: WritableKeyPath<VehicleDraft, String>) -> Binding<String> {
        Binding(get: { model.draft[keyPath: key] }, set: { value in
            var draft = model.draft; draft[keyPath: key] = value; model.edit(draft)
        })
    }
    private func field(_ label: String, hint: String, icon: String, focus: Field, value: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(label)
            HStack(spacing: 10) {
                AppAssetImage(path: "icons/archive/" + icon).frame(width: 24, height: 24).accessibilityHidden(true)
                TextField(hint, text: value).font(.system(size: 16)).multilineTextAlignment(.trailing)
                    .environment(\.layoutDirection, .leftToRight).focused($focused, equals: focus)
                    .accessibilityLabel(label).submitLabel(focus == .plate ? .done : .next)
                    .onSubmit {
                        switch focus { case .name: focused = .manufacturer; case .manufacturer: focused = .model; case .model: focused = .plate; case .plate, .category: focused = nil }
                    }
            }.padding(.horizontal, 12).frame(minHeight: 56)
                .background(.white.opacity(0.65), in: RoundedRectangle(cornerRadius: 20))
                .overlay(RoundedRectangle(cornerRadius: 20).stroke(model.fieldErrors[focus] == nil ? ChatStyle.border : .red))
                .disabled(!model.editable)
            fieldError(focus)
        }.id(focus)
    }
    @ViewBuilder private func fieldError(_ field: Field) -> some View {
        if let message = model.fieldErrors[field] {
            Text(message).font(.footnote).foregroundStyle(.red)
                .accessibilityLabel("שגיאה: " + message).accessibilityFocused($errorFocus, equals: field)
        }
    }
}
