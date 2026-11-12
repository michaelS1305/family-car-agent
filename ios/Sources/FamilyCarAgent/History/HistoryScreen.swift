
import SwiftUI

struct HistoryScreen: View {
    @ObservedObject var entry: EntryModel
    @StateObject private var model: HistoryModel
    @Environment(\.scenePhase) private var phase
    @ScaledMetric(relativeTo: .body) private var textScale = 1.0
    @State private var pickingStart = false
    @State private var pickingEnd = false

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
                            .frame(width: 200, height: 200)
                            .offset(y: -15)
                            .frame(height: 108)
                            .accessibilityLabel("היסטוריה")
                            .id("history-top")

                        if model.current {
                            currentUse.padding(.top, 16)

                            Button(action: model.openFilters) {
                                HStack(spacing: 12) {
                                    Image(systemName: "chevron.left")
                                    Text(model.applied.empty ? "הכול" : "מסונן")
                                        .foregroundStyle(ChatStyle.secondary)
                                    Spacer()
                                    Text("סינון").fontWeight(.semibold)
                                    Image(systemName: "line.3.horizontal.decrease")
                                }
                                .font(.system(size: 20 * textScale))
                                .padding(.horizontal, 18)
                                .padding(.vertical, 15)
                                .background(.white.opacity(0.88), in: Capsule())
                                .overlay(Capsule().stroke(ChatStyle.border))
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("סינון היסטוריה")

                            Text("שימושים אחרונים")
                                .font(.system(size: 19 * textScale, weight: .semibold))
                                .foregroundStyle(ChatStyle.secondary)
                                .frame(maxWidth: .infinity, alignment: .leading)

                            LazyVStack(spacing: 10) {
                                ForEach(model.visibleRows) { row in
                                    usage(row).onAppear { model.nearEnd(row.id) }
                                }
                            }

                            if model.loading {
                                ProgressView("טוען שימושים…").padding()
                            }

                            if model.pageError {
                                VStack(spacing: 8) {
                                    Text("לא ניתן לטעון את ההיסטוריה כרגע")
                                    Button("נסה שוב", action: model.retry)
                                }.padding()
                            } else if model.loaded && model.visibleRows.isEmpty {
                                Text("לא נמצאו שימושים")
                                    .foregroundStyle(ChatStyle.secondary)
                                    .padding(.vertical, 24)
                            }
                        } else {
                            ProgressView("טוען…")
                        }
                    }
                    .padding(.horizontal, 18)
                    .padding(.vertical, 10)
                    .frame(maxWidth: 620)
                    .frame(maxWidth: .infinity)
                }
                .refreshable { model.refresh() }
                .onChange(of: model.applied) { _, _ in
                    proxy.scrollTo("history-top", anchor: .top)
                }
            }
        }
        .modifier(VehiclesAppearance())
        .task { model.start() }
        .onChange(of: entry.chatIdentity) { _, _ in
            model.stop()
            model.start()
        }
        .onChange(of: phase) { _, value in
            if value == .active { model.refresh() }
        }
        .onDisappear { model.stop() }
        .sheet(
            isPresented: Binding(
                get: { model.current && model.sheet },
                set: { if !$0 { model.dismissFilters() } }
            ),
            onDismiss: model.dismissFilters
        ) {
            filters
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
                .environment(\.layoutDirection, .rightToLeft)
                .preferredColorScheme(.light)
        }
    }

    @ViewBuilder private var currentUse: some View {
        switch model.currentStatus {
        case .loading:
            ProgressView("טוען מצב רכבים…")
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)

        case .unavailable:
            VStack(spacing: 8) {
                Text("מצב הרכבים אינו זמין כרגע")
                    .foregroundStyle(ChatStyle.secondary)
                Button("נסה שוב", action: model.refreshCurrent)
            }
            .padding(.vertical, 12)

        case .ready:
            if model.active.isEmpty {
                HStack(spacing: 10) {
                    Circle()
                        .fill(Color(
                            red: 39/255,
                            green: 151/255,
                            blue: 89/255
                        ))
                        .frame(width: 8, height: 8)

                    VStack(alignment: .leading, spacing: 6) {
                        Text("כל הרכבים פנויים")
                            .font(.system(size: 22 * textScale, weight: .semibold))
                            .foregroundStyle(Color(
                                red: 49/255,
                                green: 93/255,
                                blue: 101/255
                            ))

                        Text("אין רכבים בשימוש כרגע")
                            .foregroundStyle(ChatStyle.secondary)
                    }

                    Spacer(minLength: 0)
                }
                .padding(.vertical, 10)
            } else {
                VStack(alignment: .leading, spacing: 10) {
                    Text("רכבים בשימוש")
                        .font(.system(size: 19 * textScale, weight: .semibold))
                        .foregroundStyle(ChatStyle.secondary)

                    ForEach(model.active) { vehicle in
                        HStack(spacing: 8) {
                            AppAssetImage(path: model.illustration(vehicle.id))
                                .frame(width: 66, height: 44)
                                .accessibilityHidden(true)

                            avatar(vehicle.driver ?? "")

                            VStack(alignment: .leading, spacing: 14) {
                                Text(vehicle.name + " — " + (vehicle.driver ?? ""))
                                    .font(.system(
                                        size: 16 * textScale,
                                        weight: .semibold
                                    ))
                                    .fixedSize(horizontal: false, vertical: true)

                                if let start = vehicle.start {
                                    Text("בשימוש מ " + HistoryTime.display(
                                        start,
                                        format: "HH:mm"
                                    ))
                                    .font(.system(size: 14 * textScale))
                                    .foregroundStyle(ChatStyle.secondary)
                                }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .padding(.horizontal, 10)
                        .padding(.vertical, 16)
                        .frame(minHeight: 96)
                        .modifier(HistoryCard())
                    }
                }
            }
        }
    }

    private func usage(_ row: HistoryUsage) -> some View {
        HStack(alignment: .center, spacing: 7) {
            VStack(spacing: 2) {
                AppAssetImage(path: model.illustration(row.vehicle))
                    .frame(width: 70, height: 48)
                    .accessibilityHidden(true)

                Text(row.vehicleName)
                    .font(.system(size: 13 * textScale))
                    .foregroundStyle(ChatStyle.secondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(width: 76)

            avatar(row.name)

            VStack(alignment: .leading, spacing: 9) {
                Text(row.name)
                    .font(.system(size: 16 * textScale, weight: .semibold))
                    .fixedSize(horizontal: false, vertical: true)

                Text(HistoryTime.display(
                    row.start,
                    format: "dd/MM/yyyy"
                ))
                .font(.system(size: 13 * textScale))
                .foregroundStyle(ChatStyle.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Text(HistoryTime.interval(row.start, row.end))
                .font(.system(size: 12 * textScale))
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .environment(\.layoutDirection, .leftToRight)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 12)
        .frame(minHeight: 104)
        .modifier(HistoryCard())
    }

    private func avatar(_ name: String) -> some View {
        Text(String(
            (name.split(whereSeparator: { $0.isWhitespace }).first ?? "")
                .prefix(2)
        ))
        .font(.system(size: 16 * textScale, weight: .bold))
        .frame(width: 34, height: 34)
        .background(ChatStyle.selected, in: Circle())
        .overlay(Circle().stroke(ChatStyle.border))
        .accessibilityHidden(true)
    }

    // MARK: - History Filters

    private var filters: some View {
        NavigationStack {
            Form {
                Picker("רכב", selection: $model.draft.vehicle) {
                    Text("כל הרכבים").tag(UUID?.none)

                    if let selected = model.draft.vehicle,
                       !model.vehicles.contains(where: { $0.id == selected }) {
                        Text("נבחר").tag(Optional(selected))
                    }

                    ForEach(model.vehicles) { vehicle in
                        Text(vehicle.name).tag(Optional(vehicle.id))
                    }
                }

                Picker("בן משפחה", selection: $model.draft.member) {
                    Text("כל בני המשפחה").tag(UUID?.none)

                    if let selected = model.draft.member,
                       !model.members.contains(where: { $0.id == selected }) {
                        Text("נבחר").tag(Optional(selected))
                    }

                    ForEach(model.members) { member in
                        Text(member.name).tag(Optional(member.id))
                    }
                }

                if model.membersLoading {
                    ProgressView("טוען בני משפחה…")
                }

                if model.membersError {
                    Button("לא ניתן לטעון בני משפחה — נסה שוב") {
                        model.refreshMembers()
                    }
                }

                if model.currentStatus != .ready {
                    Button("רענון רשימת רכבים") {
                        model.refreshCurrent()
                    }
                }

                filterDate(start: true)
                filterDate(start: false)

                if model.rangeError {
                    Text("זמן ההתחלה חייב להיות לפני זמן הסיום או זהה לו")
                        .foregroundStyle(.red)
                }

                HStack(spacing: 12) {
                    Button("החלת מסננים") {
                        model.apply()
                    }
                    .buttonStyle(BookingCapsuleStyle())
                    .disabled(!model.current)

                    Button("איפוס מסננים") {
                        model.draft = HistoryFilters()
                        pickingStart = false
                        pickingEnd = false
                    }
                    .buttonStyle(BookingCapsuleStyle(secondary: true))
                    .disabled(!model.current)
                }
                .listRowBackground(Color.clear)
                .listRowSeparator(.hidden)
            }
            .navigationTitle("סינון היסטוריה")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("חזרה") {
                        model.dismissFilters()
                    }
                }
            }
        }
        .tint(ChatStyle.ink)
        .onAppear {
            pickingStart = false
            pickingEnd = false
        }
    }

    // MARK: - Date Filters

    private func filterDate(start: Bool) -> some View {
        let value = start ? model.draft.from : model.draft.to
        let picking = start ? pickingStart : pickingEnd

        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                Button {
                    if start {
                        pickingStart.toggle()
                    } else {
                        pickingEnd.toggle()
                    }
                } label: {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(start ? "מתאריך ושעה" : "עד תאריך ושעה")

                        Text(
                            value.map {
                                HistoryTime.display(
                                    $0,
                                    format: "dd/MM/yyyy HH:mm"
                                )
                            } ?? "בחרו תאריך ושעה"
                        )
                        .foregroundStyle(ChatStyle.secondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)

                if value != nil {
                    Button {
                        if start {
                            model.draft.from = nil
                            pickingStart = false
                        } else {
                            model.draft.to = nil
                            pickingEnd = false
                        }
                    } label: {
                        Image(systemName: "xmark.circle")
                            .frame(minWidth: 44, minHeight: 44)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(
                        start
                            ? "ניקוי תאריך התחלה"
                            : "ניקוי תאריך סיום"
                    )
                }
            }

            if picking {
                DatePicker(
                    start ? "מתחיל ב־" : "מסתיים ב־",
                    selection: Binding(
                        get: {
                            (start ? model.draft.from : model.draft.to) ?? Date()
                        },
                        set: { date in
                            if start {
                                model.draft.from = date
                            } else {
                                model.draft.to = date
                            }
                        }
                    ),
                    displayedComponents: [.date, .hourAndMinute]
                )
                .environment(\.locale, Locale(identifier: "he_IL"))
            }
        }
    }
}

private struct HistoryCard: ViewModifier {
    func body(content: Content) -> some View {
        content
            .background(
                .white.opacity(0.82),
                in: RoundedRectangle(cornerRadius: 18)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 18)
                    .stroke(ChatStyle.border)
            )
    }
}
