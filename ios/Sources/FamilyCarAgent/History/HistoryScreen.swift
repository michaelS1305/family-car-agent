import SwiftUI

struct HistoryScreen: View {
    @ObservedObject var entry: EntryModel
    @StateObject private var model: HistoryModel
    @Environment(\.scenePhase) private var phase
    @ScaledMetric(relativeTo: .body) private var textScale = 1.0
    let back: () -> Void
    init(entry: EntryModel, back: @escaping () -> Void) {
        self.entry = entry; self.back = back
        _model = StateObject(wrappedValue: HistoryModel(gateway: entry))
    }
    var body: some View {
        VStack(spacing: 0) {
            VehiclesHeader(back: back)
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(spacing: 18) {
                        AppAssetImage(path: "icons/archive/history_icon.png")
                            .frame(width: 200, height: 200).offset(y: -15).frame(height: 108)
                            .accessibilityLabel("היסטוריה").id("history-top")
                        if model.current {
                            currentUse.padding(.top, 16)
                            Button(action: model.openFilters) {
                                HStack(spacing: 12) {
                                    Image(systemName: "chevron.left")
                                    Text(model.applied.empty ? "הכול" : "מסונן").foregroundStyle(ChatStyle.secondary)
                                    Spacer()
                                    Text("סינון").fontWeight(.semibold)
                                    Image(systemName: "line.3.horizontal.decrease")
                                }.font(.system(size: 20 * textScale)).padding(.horizontal, 18).padding(.vertical, 15)
                                    .background(.white.opacity(0.88), in: Capsule())
                                    .overlay(Capsule().stroke(ChatStyle.border))
                            }.buttonStyle(.plain).accessibilityLabel("סינון היסטוריה")
                            Text("שימושים אחרונים").font(.system(size: 19 * textScale, weight: .semibold))
                                .foregroundStyle(ChatStyle.secondary).frame(maxWidth: .infinity, alignment: .leading)
                            LazyVStack(spacing: 10) {
                                ForEach(model.visibleRows) { row in
                                    usage(row).onAppear { model.nearEnd(row.id) }
                                }
                            }
                            if model.loading { ProgressView("טוען שימושים…").padding() }
                            if model.pageError {
                                VStack(spacing: 8) {
                                    Text("לא ניתן לטעון את ההיסטוריה כרגע")
                                    Button("נסה שוב", action: model.retry)
                                }.padding()
                            } else if model.loaded && model.visibleRows.isEmpty {
                                Text("לא נמצאו שימושים").foregroundStyle(ChatStyle.secondary).padding(.vertical, 24)
                            }
                        } else { ProgressView("טוען…") }
                    }.padding(.horizontal, 18).padding(.vertical, 10).frame(maxWidth: 620).frame(maxWidth: .infinity)
                }
                .refreshable { model.refresh() }
                .onChange(of: model.applied) { _, _ in proxy.scrollTo("history-top", anchor: .top) }
            }
        }
        .modifier(VehiclesAppearance())
        .task { model.start() }
        .onChange(of: entry.chatIdentity) { _, _ in model.stop(); model.start() }
        .onChange(of: phase) { _, value in if value == .active { model.refresh() } }
        .onDisappear { model.stop() }
        .sheet(isPresented: Binding(get: { model.current && model.sheet }, set: { if !$0 { model.dismissFilters() } }), onDismiss: model.dismissFilters) {
            filters.presentationDetents([.medium, .large]).presentationDragIndicator(.visible)
                .environment(\.layoutDirection, .rightToLeft).preferredColorScheme(.light)
        }
    }
    @ViewBuilder private var currentUse: some View {
        switch model.currentStatus {
        case .loading: ProgressView("טוען מצב רכבים…").frame(maxWidth: .infinity).padding(.vertical, 12)
        case .unavailable:
            VStack(spacing: 8) {
                Text("מצב הרכבים אינו זמין כרגע").foregroundStyle(ChatStyle.secondary)
                Button("נסה שוב", action: model.refreshCurrent)
            }.padding(.vertical, 12)
        case .ready:
            if model.active.isEmpty {
                HStack(spacing: 10) {
                    Circle().fill(Color(red: 39/255, green: 151/255, blue: 89/255)).frame(width: 8, height: 8)
                    VStack(alignment: .leading, spacing: 6) {
                        Text("כל הרכבים פנויים").font(.system(size: 22 * textScale, weight: .semibold))
                            .foregroundStyle(Color(red: 49/255, green: 93/255, blue: 101/255))
                        Text("אין רכבים בשימוש כרגע").foregroundStyle(ChatStyle.secondary)
                    }
                    Spacer(minLength: 0)
                }.padding(.vertical, 10)
            } else {
                VStack(alignment: .leading, spacing: 10) {
                    Text("רכבים בשימוש").font(.system(size: 19 * textScale, weight: .semibold)).foregroundStyle(ChatStyle.secondary)
                    ForEach(model.active) { vehicle in
                        HStack(spacing: 8) {
                            AppAssetImage(path: model.illustration(vehicle.id)).frame(width: 66, height: 44).accessibilityHidden(true)
                            avatar(vehicle.driver ?? "")
                            VStack(alignment: .leading, spacing: 14) {
                                Text(vehicle.name + " — " + (vehicle.driver ?? ""))
                                    .font(.system(size: 16 * textScale, weight: .semibold)).fixedSize(horizontal: false, vertical: true)
                                if let start = vehicle.start {
                                    Text("בשימוש מ " + HistoryTime.display(start, format: "HH:mm"))
                                        .font(.system(size: 14 * textScale)).foregroundStyle(ChatStyle.secondary)
                                }
                            }.frame(maxWidth: .infinity, alignment: .leading)
                        }.padding(.horizontal, 10).padding(.vertical, 16).frame(minHeight: 96)
                            .modifier(HistoryCard())
                    }
                }
            }
        }
    }
    private func usage(_ row: HistoryUsage) -> some View {
        HStack(alignment: .center, spacing: 7) {
            VStack(spacing: 2) {
                AppAssetImage(path: model.illustration(row.vehicle)).frame(width: 70, height: 48).accessibilityHidden(true)
                Text(row.vehicleName).font(.system(size: 13 * textScale)).foregroundStyle(ChatStyle.secondary)
                    .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
            }.frame(width: 76)
            avatar(row.name)
            VStack(alignment: .leading, spacing: 9) {
                Text(row.name).font(.system(size: 16 * textScale, weight: .semibold)).fixedSize(horizontal: false, vertical: true)
                Text(HistoryTime.display(row.start, format: "dd/MM/yyyy")).font(.system(size: 13 * textScale)).foregroundStyle(ChatStyle.secondary)
            }.frame(maxWidth: .infinity, alignment: .leading)
            Text(HistoryTime.interval(row.start, row.end)).font(.system(size: 12 * textScale))
                .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
                .environment(\.layoutDirection, .leftToRight)
        }.padding(.horizontal, 10).padding(.vertical, 12).frame(minHeight: 104).modifier(HistoryCard())
    }
    private func avatar(_ name: String) -> some View {
        Text(String((name.split(whereSeparator: { $0.isWhitespace }).first ?? "").prefix(2)))
            .font(.system(size: 16 * textScale, weight: .bold)).frame(width: 34, height: 34)
            .background(ChatStyle.selected, in: Circle()).overlay(Circle().stroke(ChatStyle.border))
            .accessibilityHidden(true)
    }
    private var filters: some View {
        VStack(spacing: 0) {
            HStack {
                Text("סינון").font(.headline)
                Spacer()
                Button("סגירה", action: model.dismissFilters)
            }.padding(20)
            Form {
                Section {
                    Picker("רכב", selection: $model.draft.vehicle) {
                        Text("הכול").tag(UUID?.none)
                        if let selected = model.draft.vehicle, !model.vehicles.contains(where: { $0.id == selected }) {
                            Text("נבחר").tag(Optional(selected))
                        }
                        ForEach(model.vehicles) { Text($0.name).tag(Optional($0.id)) }
                    }.pickerStyle(.menu)
                    Picker("משתמש", selection: $model.draft.member) {
                        Text("הכול").tag(UUID?.none)
                        if let selected = model.draft.member, !model.members.contains(where: { $0.id == selected }) {
                            Text("נבחר").tag(Optional(selected))
                        }
                        ForEach(model.members) { Text($0.name).tag(Optional($0.id)) }
                    }.pickerStyle(.menu)
                    if model.membersLoading { ProgressView("טוען משתמשים…") }
                    if model.membersError { Button("לא ניתן לטעון משתמשים — נסה שוב", action: model.refreshMembers) }
                    if model.currentStatus != .ready { Button("רענון רשימת רכבים", action: model.refreshCurrent) }
                }
                Section {
                    dateFilter("מתאריך", value: $model.draft.from)
                    dateFilter("עד תאריך", value: $model.draft.to)
                    if model.rangeError {
                        Text("זמן ההתחלה חייב להיות לפני זמן הסיום או זהה לו").foregroundStyle(.red)
                    }
                }
                Section {
                    Button("הצג תוצאות", action: model.apply).disabled(!model.current)
                    Button("נקה סינון", action: model.clear).disabled(!model.current)
                }
            }
        }
    }
    private func dateFilter(_ label: String, value: Binding<Date?>) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Toggle(label, isOn: Binding(get: { value.wrappedValue != nil }, set: { value.wrappedValue = $0 ? Date() : nil }))
            if value.wrappedValue != nil {
                DatePicker(label, selection: Binding(get: { value.wrappedValue ?? Date() }, set: { value.wrappedValue = $0 }),
                           displayedComponents: [.date, .hourAndMinute]).labelsHidden()
                    .environment(\.locale, Locale(identifier: "he_IL"))
            }
        }
    }
}
private struct HistoryCard: ViewModifier {
    func body(content: Content) -> some View {
        content.background(.white.opacity(0.82), in: RoundedRectangle(cornerRadius: 18))
            .overlay(RoundedRectangle(cornerRadius: 18).stroke(ChatStyle.border))
    }
}
