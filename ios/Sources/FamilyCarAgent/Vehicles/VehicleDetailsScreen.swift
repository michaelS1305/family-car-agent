import SwiftUI

struct VehicleDetailsScreen: View {
    @ObservedObject var list: VehiclesModel
    @StateObject private var model: VehicleDetailsModel
    @Environment(\.scenePhase) private var scenePhase
    init(list: VehiclesModel, vehicleID: UUID) {
        self.list = list; _model = StateObject(wrappedValue: list.detailsModel(vehicleID))
    }
    var body: some View {
        VStack(spacing: 0) {
            VehiclesHeader { model.stop(); list.pop() }
            if list.current && model.current {
                if model.loading { ProgressView("טוען…").padding(32) }
                if model.requiresReview {
                    Text(model.operationError ?? "יש לבדוק את נתוני השרת לפני פעולה נוספת").foregroundStyle(FCAColors.color(.error)).padding()
                    Button("רענון ובדיקת נתוני השרת", action: model.reviewServerState).disabled(model.loading)
                } else if model.loadError {
                    Text("לא ניתן לטעון את פרטי הרכב")
                    Button("נסה שוב", action: model.refresh)
                }
                if let detail = model.detail, !model.loading, !model.loadError {
                    ScrollView {
                        VStack(spacing: 14) {
                            VStack(spacing: 0) {
                                Text(detail.vehicle.name).font(.system(size: 30, weight: .bold))
                                GeometryReader { geometry in
                                    AppAssetImage(path: VehicleCategory.illustration(detail.vehicle.category))
                                        .frame(width: geometry.size.width * 0.9, height: 200)
                                        .frame(maxWidth: .infinity).environment(\.layoutDirection, .leftToRight)
                                        .opacity(detail.vehicle.retired ? 0.55 : 1)
                                }.frame(height: 200).accessibilityHidden(true)
                            }
                            Text(detail.status).fontWeight(.bold).frame(maxWidth: .infinity).padding(10)
                                .foregroundStyle(statusColor(detail)).background(statusColor(detail).opacity(0.10), in: RoundedRectangle(cornerRadius: 16))
                            connection(detail)
                            treatments
                            information(detail.vehicle)
                            if model.canManage {
                                Button { model.open(.retire) } label: {
                                    HStack(spacing: 2) {
                                        icon("trash_icon.png", size: 40)
                                        Text("הוצאת הרכב משימוש")
                                    }.frame(maxWidth: .infinity).padding(6)
                                        .foregroundStyle(FCAColors.color(.retireAction))
                                        .overlay(Capsule().stroke(FCAColors.color(.retireBorder)))
                                }.disabled(!model.canWrite)
                            }
                            if detail.vehicle.retired {
                                panel { HStack { icon("info_icon.png", size: 24); Text("רכב זה אינו פעיל\nלא ניתן לבצע שינויים או פעולות ברכב זה") } }
                            }
                        }.padding(.horizontal, 18).padding(.vertical, 10).frame(maxWidth: 620).frame(maxWidth: .infinity)
                    }
                }
            }
            Spacer(minLength: 0)
        }.modifier(VehiclesAppearance())
            .task { model.start() }
            .onChange(of: list.current) { _, current in if !current { model.stop() } }
            .onChange(of: scenePhase) { _, phase in if phase == .active { model.refresh() } }
            .onDisappear { if model.sheet != .connection { model.stop() } }
            .fullScreenCover(isPresented: Binding(get: {
                list.current && model.current && model.sheet == .connection && model.detail?.vehicle.retired == false
            }, set: { if !$0 { model.close() } })) {
                if let identity = model.connectionIdentity {
                    VehicleConnectionSetupView(identity: identity, vehicle: model.vehicleID,
                                               name: model.detail?.vehicle.name ?? "", close: { model.close() })
                        .id(model.vehicleID)
                }
            }
            .sheet(item: Binding(get: { list.current && model.current && model.sheet != .connection ? model.sheet : nil }, set: { if $0 == nil && model.sheet != .connection { model.close() } })) { sheet in
                VehicleDetailsEditor(model: model, sheet: sheet)
            }
    }
    private func statusColor(_ detail: VehicleDetail) -> Color {
        if detail.vehicle.retired { return FCAColors.color(.retired) }
        return detail.inUse ? FCAColors.color(.warning) : FCAColors.color(.success)
    }
    private func icon(_ name: String, size: CGFloat) -> some View {
        AppAssetImage(path: "icons/archive/" + name, monochromeControl: true).frame(width: size, height: size).accessibilityHidden(true)
    }
    private func panel<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10, content: content).frame(maxWidth: .infinity, alignment: .leading)
            .padding(14).background(FCAColors.color(.surface).opacity(0.72), in: RoundedRectangle(cornerRadius: 18))
            .overlay(RoundedRectangle(cornerRadius: 18).stroke(ChatStyle.border))
    }
    private func heading(_ text: String, symbol: String, action: @escaping () -> Void) -> some View {
        HStack {
            Text(text).font(.system(size: 20, weight: .bold)); Spacer()
            if model.canManage {
                Button(action: action) { Image(systemName: symbol).font(.system(size: 25)).frame(width: 44, height: 44) }
                    .disabled(!model.canWrite).accessibilityLabel(text == "טיפולים" ? "הוספת טיפול" : "עריכת פרטי רכב")
            }
        }
    }
    private func connection(_ detail: VehicleDetail) -> some View {
        panel {
            HStack {
                icon("phone_icon.png", size: 36)
                VStack(alignment: .leading) {
                    Text("חיבור וזיהוי אוטומטי").fontWeight(.bold)
                    Text(detail.vehicle.retired ? "לא פעיל" : "הגדרה והרשאות")
                }.padding(.horizontal, 10).frame(maxWidth: .infinity, alignment: .leading)
                if !detail.vehicle.retired {
                    Button { model.open(.connection) } label: { Image(systemName: "chevron.left").frame(width: 44, height: 44) }
                        .accessibilityLabel("פתיחת חיבור וזיהוי אוטומטי")
                }
            }
            if detail.vehicle.retired { Text("הגדרות הקישור אינן פעילות לרכב זה").font(.system(size: 13)).foregroundStyle(ChatStyle.secondary) }
        }
    }
    private var treatments: some View {
        panel {
            heading("טיפולים", symbol: "plus") { model.open(.maintenance) }
            if model.maintenanceLoading { ProgressView() }
            else if model.maintenanceError {
                Text("לא ניתן לטעון טיפולים"); Button("נסה שוב", action: model.refreshMaintenance)
            } else if model.maintenance.isEmpty { Text("אין טיפולים להצגה").foregroundStyle(ChatStyle.secondary) }
            else {
                ForEach(model.maintenance) { item in
                    Button { model.openMaintenance(item) } label: {
                        HStack {
                            icon("maintenance_icon.png", size: 28)
                            VStack(alignment: .leading) {
                                Text(item.description).fontWeight(.medium)
                                if item.completed { Text("בוצע").foregroundStyle(ChatStyle.secondary) }
                                Label(item.day.label, systemImage: "calendar")
                            }.padding(.leading, 10)
                            Spacer(minLength: 0)
                        }.frame(maxWidth: .infinity, alignment: .leading).padding(12)
                            .overlay(RoundedRectangle(cornerRadius: 14).stroke(ChatStyle.border))
                    }.buttonStyle(.plain).disabled(!model.canWrite)
                }
            }
        }
    }
    private func information(_ vehicle: ManagedVehicle) -> some View {
        panel {
            heading("פרטי רכב", symbol: "pencil") { model.open(.edit) }
            infoRow("שם הרכב", vehicle.name); infoRow("סוג רכב", vehicle.category?.label)
            infoRow("יצרן", vehicle.manufacturerName); infoRow("דגם", vehicle.model); infoRow("מספר רכב", vehicle.plate)
        }
    }
    private func infoRow(_ label: String, _ value: String?) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text(label)
                .multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
                .frame(minWidth: 0, maxWidth: .infinity, alignment: .leading)
            Text(value ?? "—")
                .multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
                .frame(minWidth: 0, maxWidth: .infinity, alignment: .leading)
        }.fixedSize(horizontal: false, vertical: true)
    }
}

private struct VehicleDetailsEditor: View {
    @ObservedObject var model: VehicleDetailsModel
    let sheet: VehicleDetailsSheet
    @State private var showDelete = false
    @FocusState private var focused: VehicleFormField?
    var body: some View {
        ScrollView {
            if model.current {
                VStack(alignment: .leading, spacing: 14) {
                    Text(title).font(.system(size: 23, weight: .bold))
                    switch sheet {
                    case .connection:
                        EmptyView() // Connection has its own full-screen flow.
                    case .retire:
                        AppAssetImage(path: "icons/archive/trash_icon.png", monochromeControl: true).frame(height: 36).frame(maxWidth: .infinity)
                        Text("הרכב יישאר בהיסטוריה ולא יהיה זמין לשימוש ולהזמנות חדשות. הזמנות פעילות שטרם הסתיימו, כולל הזמנות עתידיות, יבוטלו. לא ניתן להחזיר את הרכב לפעילות.")
                    case .edit: editFields
                    case .maintenance:
                        field("תיאור הטיפול", value: Binding(get: { model.description }, set: { model.editMaintenance($0, day: model.day) }))
                        DatePicker("תאריך הטיפול", selection: Binding(get: { model.day.date }, set: {
                            if let day = try? VehicleDay(VehicleDay.string($0)) { model.editMaintenance(model.description, day: day) }
                        }), displayedComponents: .date)
                        .environment(\.calendar, VehicleDay.calendar).environment(\.timeZone, TimeZone(secondsFromGMT: 0)!)
                        .disabled(!model.canWrite)
                    }
                    if let error = model.operationError { Text(error).foregroundStyle(FCAColors.color(.error)) }
                    if model.requiresReview {
                        Button("רענון ובדיקת נתוני השרת", action: model.reviewServerState).disabled(model.loading || model.maintenanceLoading)
                    } else if sheet != .connection {
                        Button(action: model.submit) {
                            Text(model.busy ? "ממתינים לאישור…" : sheet == .retire ? "הוצאה משימוש" : sheet == .maintenance && model.maintenanceID == nil ? "הוספת טיפול" : "שמירה")
                                .frame(maxWidth: .infinity, minHeight: 50).foregroundStyle(FCAColors.color(sheet == .retire ? .onDestructiveAction : .onPrimaryAction))
                                .background(sheet == .retire ? FCAColors.color(.destructiveAction) : FCAColors.color(.primaryAction), in: RoundedRectangle(cornerRadius: 20))
                        }.disabled(!model.canWrite || !valid || model.maintenanceLoading)
                    }
                    if sheet == .maintenance, let id = model.maintenanceID {
                        if model.maintenance.contains(where: { $0.id == id && !$0.completed }) {
                            Button(action: model.complete) {
                                Label("סימון הטיפול כבוצע", systemImage: "checkmark.circle")
                            }.buttonStyle(MaintenanceActionStyle()).disabled(!model.canWrite)
                        } else { Text("הטיפול בוצע") }
                        Button(role: .destructive) { model.requestDelete(); showDelete = model.deleteConfirmation } label: {
                            Label("מחיקת טיפול", systemImage: "trash")
                        }.buttonStyle(MaintenanceActionStyle(destructive: true)).disabled(!model.canWrite)
                    }
                    if sheet == .maintenance, model.maintenanceID != nil {
                        Button("ביטול", action: model.close)
                            .buttonStyle(MaintenanceActionStyle(neutral: true)).disabled(model.busy)
                    } else {
                        Button(sheet == .connection ? "סגירה" : "ביטול", action: model.close).disabled(model.busy).frame(maxWidth: .infinity, minHeight: 44)
                    }
                }.padding(20)
            }
        }.scrollDismissesKeyboard(.interactively).modifier(VehiclesAppearance())
            .interactiveDismissDisabled(model.busy)
            .alert("למחוק את הטיפול?", isPresented: $showDelete) {
                Button("מחיקה", role: .destructive, action: model.confirmDelete)
                Button("ביטול", role: .cancel, action: model.cancelDelete)
            } message: { Text("הטיפול יימחק מהרכב. לא ניתן לבטל את המחיקה.") }
    }
    private var title: String {
        switch sheet { case .edit: "עריכת פרטי רכב"; case .maintenance: model.maintenanceID == nil ? "הוספת טיפול" : "עריכת טיפול"; case .retire: "להוציא את הרכב משימוש?"; case .connection: "חיבור וזיהוי אוטומטי" }
    }
    private var valid: Bool {
        switch sheet {
        case .edit: model.draft.valid && model.catalog.contains(where: { $0 == model.draft.manufacturer })
        case .maintenance: !model.description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        default: true
        }
    }
    private func binding(_ key: WritableKeyPath<VehicleDraft, String>) -> Binding<String> {
        Binding(get: { model.draft[keyPath: key] }, set: { value in var d = model.draft; d[keyPath: key] = value; model.edit(d) })
    }
    private func field(_ label: String, value: Binding<String>, focus: VehicleFormField = .name) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(label)
            TextField(label, text: value).multilineTextAlignment(.trailing).environment(\.layoutDirection, .leftToRight)
                .focused($focused, equals: focus)
                .accessibilityLabel(label).padding(12).frame(minHeight: 56)
                .overlay(RoundedRectangle(cornerRadius: 20).stroke(ChatStyle.border)).disabled(!model.canWrite)
        }
    }
    private var editFields: some View {
        Group {
            field("שם הרכב", value: binding(\.name))
            Text("סוג רכב")
            HStack(spacing: 4) {
                ForEach(VehicleCategory.allCases, id: \.self) { category in
                    Button { var d = model.draft; d.category = category; model.edit(d) } label: {
                        VStack {
                            AppAssetImage(path: category.asset).frame(height: 42)
                            Text(category.label).font(.system(size: 9)).lineLimit(2)
                        }.padding(3).frame(maxWidth: .infinity)
                            .overlay(RoundedRectangle(cornerRadius: 12).stroke(model.draft.category == category ? ChatStyle.ink : ChatStyle.border, lineWidth: model.draft.category == category ? 2 : 1))
                    }.disabled(!model.canWrite).accessibilityLabel(category.label).accessibilityAddTraits(model.draft.category == category ? .isSelected : [])
                }
            }.environment(\.layoutDirection, .leftToRight)
            field("יצרן", value: Binding(get: { model.draft.manufacturerQuery }, set: { value in model.query(value) }), focus: .manufacturer)
            if model.catalogLoading { ProgressView("טוען יצרנים…") }
            if model.catalogError { Button("טעינת יצרנים מחדש", action: model.loadCatalog) }
            if model.catalogLoaded && !model.draft.manufacturerQuery.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && model.draft.manufacturer == nil {
                ScrollView {
                    LazyVStack {
                        ForEach(model.matches) { maker in
                            Button { model.choose(maker); focused = .model } label: {
                                Text(maker.name_he).frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                                    .contentShape(Rectangle())
                            }.buttonStyle(.plain).disabled(!model.canWrite)
                        }
                    }
                }.frame(height: min(144, CGFloat(model.matches.count) * 44))
            }
            field("דגם", value: binding(\.model), focus: .model); field("מספר רכב", value: binding(\.plate), focus: .plate)
        }
    }
}

/// Scoped to the maintenance editor; shared colors and the existing Save corner radius.
private struct MaintenanceActionStyle: ButtonStyle {
    var destructive = false
    var neutral = false
    @Environment(\.isEnabled) private var enabled
    private var foreground: Color {
        FCAColors.color(neutral ? .text : destructive ? .error : .secondaryAction)
    }
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.body).multilineTextAlignment(.center)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, 12).padding(.vertical, 10)
            .frame(maxWidth: .infinity, minHeight: 50)
            .foregroundStyle(foreground)
            .background(neutral ? FCAColors.color(.elevated) : .clear, in: RoundedRectangle(cornerRadius: 20))
            .overlay(RoundedRectangle(cornerRadius: 20).stroke(neutral ? .clear : foreground, lineWidth: 1))
            .contentShape(RoundedRectangle(cornerRadius: 20))
            .opacity(enabled ? (configuration.isPressed ? 0.7 : 1) : 0.45)
    }
}
