import SwiftUI

private struct BookingPeekDetent: CustomPresentationDetent {
    static func height(in context: Context) -> CGFloat? {
        min(context.maxDetentValue * 0.8, context.dynamicTypeSize.isAccessibilitySize ? 440 : 250)
    }
}

struct BookingCenterPreview: View {
    @ObservedObject var model: BookingModel
    @Environment(\.scenePhase) private var phase
    let back: () -> Void
    private var calendar: BookingPreviewCalendar { model.calendar }
    @State private var presented = false
    @State private var leaving = false
    @State private var detent = PresentationDetent.custom(BookingPeekDetent.self)
    private let peek = PresentationDetent.custom(BookingPeekDetent.self)

    var body: some View {
        VStack(spacing: 0) {
            VehiclesHeader(back: leave)
            ScrollView {
                VStack(spacing: 18) {
                    AppAssetImage(path: "icons/archive/booking_center_icon.png")
                        .frame(width: 200, height: 200).offset(y: -15).frame(height: 130)
                        .accessibilityLabel("מרכז הזמנות")
                    monthGrid
                    // Allow the last calendar row to scroll above the persistent sheet.
                    Color.clear.frame(height: 300).accessibilityHidden(true)
                }.padding(18).frame(maxWidth: 620).frame(maxWidth: .infinity)
            }
        }
        .modifier(VehiclesAppearance())
        .onAppear { if !leaving { presented = true } }
        .task { model.enter() }
        .onDisappear { model.leave() }
        .onChange(of: phase) { _, value in if value == .active { model.refresh() } }
        .sheet(isPresented: $presented, onDismiss: { if leaving { back() } }) {
            previewSheet
                .presentationDetents([peek, .large], selection: $detent)
                .presentationDragIndicator(.visible)
                .presentationBackgroundInteraction(.enabled(upThrough: peek))
                .presentationContentInteraction(.resizes)
                .interactiveDismissDisabled()
                .presentationBackground(ChatStyle.incoming)
                .environment(\.layoutDirection, .rightToLeft)
                .preferredColorScheme(.light)
                .sheet(item: Binding(get: { model.current ? model.sheet : nil }, set: { if $0 == nil { model.dismiss() } })) { sheet in
                    BookingForms(model: model, sheet: sheet)
                        .environment(\.layoutDirection, .rightToLeft)
                        .environment(\.timeZone, BookingPreviewCalendar.calendar.timeZone)
                        .environment(\.calendar, BookingPreviewCalendar.calendar)
                        .environment(\.locale, Locale(identifier: "he_IL"))
                        .preferredColorScheme(.light).interactiveDismissDisabled(model.busy)
                }
        }
    }

    private func leave() {
        leaving = true
        if presented { presented = false } else { back() }
    }

    private var monthGrid: some View {
        VStack(spacing: 12) {
            HStack {
                Button { model.moveMonth(1) } label: { Image(systemName: "chevron.right").frame(minWidth: 44, minHeight: 44) }
                    .accessibilityLabel("החודש הבא")
                Text(BookingPreviewCalendar.label(calendar.month, format: "MMMM yyyy"))
                    .font(.title2.bold()).multilineTextAlignment(.center).frame(maxWidth: .infinity)
                Button { model.moveMonth(-1) } label: { Image(systemName: "chevron.left").frame(minWidth: 44, minHeight: 44) }
                    .accessibilityLabel("החודש הקודם")
            }
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 0), count: 7), spacing: 8) {
                ForEach(["א", "ב", "ג", "ד", "ה", "ו", "ש"], id: \.self) { Text($0).foregroundStyle(ChatStyle.secondary) }
                ForEach(calendar.days, id: \.self) { day in
                    dayButton(day)
                }
            }
        }.padding(12).background(.white.opacity(0.88), in: RoundedRectangle(cornerRadius: 22))
            .overlay(RoundedRectangle(cornerRadius: 22).stroke(ChatStyle.border))
    }

    private func dayButton(_ day: Date) -> some View {
        let selected = BookingPreviewCalendar.calendar.isDate(day, inSameDayAs: calendar.selected)
        let currentMonth = BookingPreviewCalendar.calendar.isDate(day, equalTo: calendar.month, toGranularity: .month)
        return Button { model.select(day) } label: {
            Text(BookingPreviewCalendar.label(day, format: "d"))
                .font(.title3).frame(maxWidth: .infinity, minHeight: 44)
                .foregroundStyle(selected ? .white : currentMonth ? ChatStyle.ink : ChatStyle.secondary.opacity(0.6))
                .background(selected ? Color.blue : .clear, in: Circle())
                .overlay(alignment: .bottom) {
                    if !model.onDay(day).isEmpty { Circle().fill(selected ? Color.white : Color.blue).frame(width: 5, height: 5) }
                }
        }.buttonStyle(.plain)
            .accessibilityLabel(BookingPreviewCalendar.label(day, format: "EEEE d MMMM yyyy"))
            .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private var previewSheet: some View {
        VStack(spacing: 12) {
            GeometryReader { geometry in
              ScrollView(.horizontal) {
                HStack(spacing: 14) {
                    toolbarButton("סינון", symbol: "line.3.horizontal.decrease", enabled: model.current && !model.busy, active: !model.applied.empty) { model.openFilters() }
                    toolbarButton("עריכה", symbol: "pencil", enabled: model.canWrite, active: model.selection == .edit) {
                        model.selectMode(.edit); detent = .large
                    }
                    toolbarButton("ביטול הזמנה", symbol: "trash", enabled: model.canWrite, active: model.selection == .cancel) {
                        model.selectMode(.cancel); detent = .large
                    }
                    toolbarButton("הוספה", symbol: "plus", enabled: model.canWrite) { model.openCreate() }
                    Button { model.today() } label: {
                        Text(BookingPreviewCalendar.label(calendar.selected, format: "d"))
                            .font(.title2.bold()).frame(width: 48, height: 48).background(.white, in: Circle())
                    }.buttonStyle(.plain).disabled(model.busy).accessibilityLabel("מעבר להיום")
                }.padding(.horizontal, 18).frame(minWidth: geometry.size.width)
            }.scrollBounceBehavior(.basedOnSize, axes: .horizontal)
                .defaultScrollAnchor(.center)
            }.frame(height: 48)
            ScrollView {
                VStack(spacing: 16) {
                    Text(BookingPreviewCalendar.label(calendar.selected, format: "EEEE, d MMMM yyyy"))
                        .font(.title2.bold()).multilineTextAlignment(.center)
                    if model.loading { ProgressView("טוען הזמנות…") }
                    else if model.readError {
                        Text("לא ניתן לטעון הזמנות כרגע")
                        Button("נסה שוב") { model.refresh() }
                    } else if model.loaded {
                        Text("\(model.dayRows.count) הזמנות").foregroundStyle(ChatStyle.secondary)
                    }
                    if let notice = model.notice { Text(notice).font(.callout) }
                    if let pending = model.pending, !model.busy {
                        Text("פעולה שטרם הובררה: " + BookingPreviewCalendar.label(pending.operation.start, format: "dd/MM/yyyy HH:mm"))
                            .font(.callout)
                        Button("בדיקת הטווח המבוקש בשרת") { model.inspectPending() }
                        if pending.operation.original != nil {
                            Button("בדיקת הטווח המקורי בשרת") { model.inspectPending(original: true) }
                        }
                        Button("בדקתי את ההזמנות; להמשיך למרות אי־הוודאות") { model.acknowledge() }
                            .disabled(!model.canAcknowledge)
                    }
                    if model.selection != .none {
                        Text(model.selection == .edit ? "בחרו הזמנה שלכם לעריכה" : "בחרו הזמנה שלכם לביטול")
                        Button("סיום בחירה") { model.selectMode(model.selection) }
                    }
                    if model.busy { ProgressView("שומר…") }
                    ForEach(model.dayRows) { row in
                        Button { model.choose(row) } label: { reservationCard(row) }
                            .buttonStyle(.plain)
                            .disabled(model.selection == .none || !model.canWrite || !model.eligible(row))
                            .accessibilityHint(model.eligible(row) ? "ניתן לבחור במצב עריכה או ביטול" : "הזמנה לקריאה בלבד")
                    }
                    if model.loaded && !model.readError && model.dayRows.isEmpty { Text("אין הזמנות לתאריך זה תחת המסננים הנוכחיים").padding(.vertical, 12) }
                    Button(detent == peek ? "הרחבה" : "צמצום") {
                        withAnimation { detent = detent == peek ? .large : peek }
                    }.frame(minHeight: 44)
                    Button("חזרה לדשבורד", action: leave).frame(minHeight: 44)
                }.padding(.horizontal, 18).padding(.bottom, 20).frame(maxWidth: .infinity)
            }
        }.padding(.top, 28).foregroundStyle(ChatStyle.ink)
    }
    private func toolbarButton(_ label: String, symbol: String, enabled: Bool, active: Bool = false, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol).font(.title2).frame(width: 48, height: 48)
                .background(active ? ChatStyle.selected : .white.opacity(0.85), in: Circle())
        }.buttonStyle(.plain).disabled(!enabled).opacity(enabled ? 1 : 0.5).accessibilityLabel(label)
    }
    private func reservationCard(_ row: BookingReservation) -> some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 14) { vehicle(row); member(row); times(row) }
            VStack(spacing: 14) { vehicle(row); member(row); times(row) }
        }.padding(18).frame(maxWidth: .infinity)
            .background(.white.opacity(0.9), in: RoundedRectangle(cornerRadius: 22))
            .overlay(RoundedRectangle(cornerRadius: 22).stroke(ChatStyle.border))
    }
    private func vehicle(_ row: BookingReservation) -> some View {
        VStack {
            AppAssetImage(path: VehicleCategory.illustration(row.category)).frame(width: 80, height: 54).accessibilityHidden(true)
            Text(row.vehicleName ?? (row.vehicle == nil ? "הזמנה כללית" : "—")).font(.caption).foregroundStyle(ChatStyle.secondary)
        }
    }
    private func member(_ row: BookingReservation) -> some View {
        HStack {
            Text(String(row.owner.prefix(2))).padding(10).background(ChatStyle.selected, in: Circle())
            Text(row.owner).font(.headline)
        }
    }
    private func times(_ row: BookingReservation) -> some View {
        let sameDay = BookingPreviewCalendar.calendar.isDate(row.start, inSameDayAs: row.end)
        let format = sameDay ? "HH:mm" : "dd/MM/yyyy HH:mm"
        return Label(BookingPreviewCalendar.label(row.start, format: format) + "–" + BookingPreviewCalendar.label(row.end, format: format), systemImage: "clock")
            .font(.callout).environment(\.layoutDirection, .leftToRight).fixedSize(horizontal: false, vertical: true)
    }
}
