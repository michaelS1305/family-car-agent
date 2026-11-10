import SwiftUI

#if DEBUG
private struct BookingPeekDetent: CustomPresentationDetent {
    static func height(in context: Context) -> CGFloat? {
        min(context.maxDetentValue * 0.8, context.dynamicTypeSize.isAccessibilitySize ? 440 : 280)
    }
}

/// Phase A only: synthetic data, no booking operations or network access.
struct BookingCenterPreview: View {
    let back: () -> Void
    @State private var calendar = BookingPreviewCalendar()
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
                    Text("תצוגת ניסיון בלבד · נתוני דוגמה, ללא הזמנות אמיתיות")
                        .font(.caption).foregroundStyle(ChatStyle.secondary)
                    Button("הצגת יום עם הזמנת דוגמה") { calendar.select(calendar.sampleDay) }
                    // Allow the last calendar row to scroll above the persistent sheet.
                    Color.clear.frame(height: 300).accessibilityHidden(true)
                }.padding(18).frame(maxWidth: 620).frame(maxWidth: .infinity)
            }
        }
        .modifier(VehiclesAppearance())
        .onAppear { if !leaving { presented = true } }
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
        }
    }

    private func leave() {
        leaving = true
        if presented { presented = false } else { back() }
    }

    private var monthGrid: some View {
        VStack(spacing: 12) {
            HStack {
                Button { calendar.moveMonth(1) } label: { Image(systemName: "chevron.right").frame(minWidth: 44, minHeight: 44) }
                    .accessibilityLabel("החודש הבא")
                Text(BookingPreviewCalendar.label(calendar.month, format: "MMMM yyyy"))
                    .font(.title2.bold()).multilineTextAlignment(.center).frame(maxWidth: .infinity)
                Button { calendar.moveMonth(-1) } label: { Image(systemName: "chevron.left").frame(minWidth: 44, minHeight: 44) }
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
        return Button { calendar.select(day) } label: {
            Text(BookingPreviewCalendar.label(day, format: "d"))
                .font(.title3).frame(maxWidth: .infinity, minHeight: 44)
                .foregroundStyle(selected ? .white : currentMonth ? ChatStyle.ink : ChatStyle.secondary.opacity(0.6))
                .background(selected ? Color.blue : .clear, in: Circle())
        }.buttonStyle(.plain)
            .accessibilityLabel(BookingPreviewCalendar.label(day, format: "EEEE d MMMM yyyy"))
            .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private var previewSheet: some View {
        VStack(spacing: 12) {
            ScrollView(.horizontal) {
                HStack(spacing: 14) {
                    toolbarButton("סינון — לא זמין בניסוי", symbol: "line.3.horizontal.decrease")
                    toolbarButton("עריכה — לא זמינה בניסוי", symbol: "pencil")
                    toolbarButton("מחיקה — לא זמינה בניסוי", symbol: "trash")
                    toolbarButton("הוספה — לא זמינה בניסוי", symbol: "plus")
                    Text(BookingPreviewCalendar.label(calendar.selected, format: "d"))
                        .font(.title2.bold()).frame(width: 48, height: 48).background(.white, in: Circle())
                        .accessibilityLabel("היום הנבחר")
                }.padding(.horizontal, 18)
            }.fixedSize(horizontal: false, vertical: true)
            ScrollView {
                VStack(spacing: 16) {
                    Text(BookingPreviewCalendar.label(calendar.selected, format: "EEEE, d MMMM yyyy"))
                        .font(.title2.bold()).multilineTextAlignment(.center)
                    Text(calendar.hasSample ? "הזמנת דוגמה אחת · לא נתוני שרת" : "0 הזמנות דוגמה")
                        .foregroundStyle(ChatStyle.secondary)
                    Text("תצוגת ניסיון בלבד · פעולות ההזמנה אינן זמינות")
                        .font(.caption).foregroundStyle(ChatStyle.secondary)
                    if calendar.hasSample { sampleCard }
                    else { Text("אין הזמנות דוגמה לתאריך זה").padding(.vertical, 12) }
                    Button(detent == peek ? "הרחבה" : "צמצום") {
                        withAnimation { detent = detent == peek ? .large : peek }
                    }.frame(minHeight: 44)
                    Button("חזרה לדשבורד", action: leave).frame(minHeight: 44)
                }.padding(.horizontal, 18).padding(.bottom, 20).frame(maxWidth: .infinity)
            }
        }.padding(.top, 28).foregroundStyle(ChatStyle.ink)
    }

    private func toolbarButton(_ label: String, symbol: String) -> some View {
        Button {} label: {
            Image(systemName: symbol).font(.title2).frame(width: 48, height: 48)
                .background(.white.opacity(0.85), in: Circle())
        }.buttonStyle(.plain).disabled(true).opacity(0.5).accessibilityLabel(label)
    }

    private var sampleCard: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 14) { sampleVehicle; sampleMember; sampleTime }
            VStack(spacing: 14) { sampleVehicle; sampleMember; sampleTime }
        }.padding(18).frame(maxWidth: .infinity)
            .background(.white.opacity(0.9), in: RoundedRectangle(cornerRadius: 22))
            .overlay(RoundedRectangle(cornerRadius: 22).stroke(ChatStyle.border))
    }
    private var sampleVehicle: some View {
        VStack {
            AppAssetImage(path: "vehicles/suv/suv_silver.png").frame(width: 80, height: 54).accessibilityHidden(true)
            Text("רכב לדוגמה").font(.caption).foregroundStyle(ChatStyle.secondary)
        }
    }
    private var sampleMember: some View {
        HStack {
            Text("דג").padding(10).background(ChatStyle.selected, in: Circle())
            Text("משתמש לדוגמה").font(.headline)
        }
    }
    private var sampleTime: some View {
        Label("14:00–15:00", systemImage: "clock").font(.callout)
            .environment(\.layoutDirection, .leftToRight).fixedSize()
    }
}
#endif
