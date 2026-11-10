
import SwiftUI

struct BookingForms: View {
    @ObservedObject var model: BookingModel
    let sheet: BookingModel.Sheet
    @State private var pickingStart = false
    @State private var pickingEnd = false
    var body: some View {
        NavigationStack {
            Form {
                if let notice = model.notice, sheet != .editor {
                    Text(notice).foregroundStyle(ChatStyle.ink)
                }
                if model.busy { ProgressView("שומר…") }
                switch sheet {
                case .editor: editor
                case .filters: filters
                case .cancellation: EmptyView() // Presented over the Booking Center, never as a form.
                }
            }
            .navigationTitle(sheet == .filters ? "סינון הזמנות" : "פרטי הזמנה")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("חזרה") { model.dismiss() }.disabled(model.busy) }
            }
        }.tint(ChatStyle.ink)
    }
    @ViewBuilder private var catalog: some View {
        if model.catalogLoading { ProgressView("טוען רכבים ובני משפחה…") }
        if model.catalogError {
            Text("לא ניתן לטעון את אפשרויות הבחירה.")
            Button("נסה שוב") { model.loadChoices() }
        }
    }
    @ViewBuilder private var editor: some View {
        catalog
        if let draft = model.draft {
            Picker("רכב", selection: Binding(get: { model.draft?.vehicle }, set: { value in
                guard var draft = model.draft else { return }; draft.vehicle = value; model.updateDraft(draft)
            })) {
                if draft.original?.vehicle == nil || draft.original == nil {
                    Text(model.activeVehicles.isEmpty && model.catalogLoaded ? "הזמנה כללית — ללא רכב" : "בחרו רכב")
                        .tag(Optional<UUID>.none)
                }
                if let old = draft.original, let id = old.vehicle, !model.activeVehicles.contains(where: { $0.id == id }) {
                    Text((old.vehicleName ?? "—") + " (רכב ההזמנה)").tag(Optional(id))
                }
                ForEach(model.activeVehicles) { Text($0.name).tag(Optional($0.id)) }
            }.disabled(model.busy || !model.catalogLoaded || model.catalogError)
            dateInput(start: true)
            dateInput(start: false)
            Button { model.submit() } label: {
                HStack(spacing: 8) {
                    if model.busy { ProgressView().tint(.white) }
                    Text("שמירת הזמנה")
                }
            }.buttonStyle(BookingCapsuleStyle()).disabled(!model.canSubmitDraft)
                .listRowBackground(Color.clear).listRowSeparator(.hidden)
            if model.startLocked { Text("ההזמנה כבר התחילה; לא ניתן לשנות את שעת ההתחלה.").font(.caption) }
        }
    }
    private func dateInput(start: Bool) -> some View {
        VStack(alignment: .leading) {
            Text(start ? "תחילת ההזמנה" : "סיום ההזמנה").font(.headline)
            if (start ? model.draft?.start : model.draft?.end) == nil {
                Button("בחירת תאריך ושעה") {
                    guard var draft = model.draft else { return }
                    let times = BookingTime.defaults(selected: model.editorDay, now: Date())
                    let value = start ? times.start : BookingPreviewCalendar.calendar.date(byAdding: .hour, value: 1, to: draft.start ?? times.start)!
                    if start { draft.start = value } else { draft.end = value }
                    model.updateDraft(draft)
                }.disabled(model.busy)
            } else {
                DatePicker(start ? "מתחיל ב־" : "מסתיים ב־", selection: Binding(get: {
                    (start ? model.draft?.start : model.draft?.end) ?? model.editorDay
                }, set: { value in
                    guard var draft = model.draft else { return }
                    if start { draft.start = value } else { draft.end = value }
                    model.updateDraft(draft)
                }), displayedComponents: [.date, .hourAndMinute])
                    .disabled(model.busy || (start && model.startLocked))
            }
        }
    }
    private var filters: some View {
        Group {
            catalog
            Picker("רכב", selection: $model.filters.vehicle) {
                Text("כל הרכבים").tag(Optional<UUID>.none)
                ForEach(model.vehicles) { Text($0.name).tag(Optional($0.id)) }
            }.disabled(!model.catalogLoaded)
            Picker("בן משפחה", selection: $model.filters.member) {
                Text("כל בני המשפחה").tag(Optional<UUID>.none)
                ForEach(model.members) { Text($0.name).tag(Optional($0.id)) }
            }.disabled(!model.catalogLoaded)
            filterDate(start: true)
            filterDate(start: false)
            HStack(spacing: 12) {
                Button("החלת מסננים") { model.applyFilters() }
                    .buttonStyle(BookingCapsuleStyle()).disabled(model.busy)
                Button("איפוס מסננים") {
                    model.filters = BookingFilters(); pickingStart = false; pickingEnd = false
                }.buttonStyle(BookingCapsuleStyle(secondary: true)).disabled(model.busy)
            }.listRowBackground(Color.clear).listRowSeparator(.hidden)
        }
    }
    private func filterDate(start: Bool) -> some View {
        let value = start ? model.filters.start : model.filters.end
        let picking = start ? pickingStart : pickingEnd
        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                Button {
                    if start { pickingStart.toggle() } else { pickingEnd.toggle() }
                } label: {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(start ? "מתאריך ושעה" : "עד תאריך ושעה")
                        Text(value.map { BookingPreviewCalendar.label($0, format: "dd/MM/yyyy HH:mm") } ?? "בחרו תאריך ושעה")
                            .foregroundStyle(ChatStyle.secondary)
                    }.frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle())
                }.buttonStyle(.plain)
                if value != nil {
                    Button {
                        if start { model.filters.start = nil; pickingStart = false }
                        else { model.filters.end = nil; pickingEnd = false }
                    } label: { Image(systemName: "xmark.circle").frame(minWidth: 44, minHeight: 44) }
                        .buttonStyle(.plain).accessibilityLabel(start ? "ניקוי תאריך התחלה" : "ניקוי תאריך סיום")
                }
            }
            if picking {
                DatePicker(start ? "מתחיל ב־" : "מסתיים ב־", selection: Binding(get: {
                    (start ? model.filters.start : model.filters.end) ?? model.calendar.selected
                }, set: { value in
                    if start { model.filters.start = value } else { model.filters.end = value }
                }), displayedComponents: [.date, .hourAndMinute])

            }
        }
    }
}

struct BookingCapsuleStyle: ButtonStyle {
    var secondary = false
    var destructive = false
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.body.weight(.semibold)).multilineTextAlignment(.center)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, 12).padding(.vertical, 10)
            .frame(maxWidth: .infinity, minHeight: 44)
            .foregroundStyle(destructive ? Color.red : secondary ? ChatStyle.ink : .white)
            .background(secondary || destructive ? Color.white : ChatStyle.ink, in: Capsule())
            .overlay(Capsule().stroke(secondary || destructive ? ChatStyle.border : .clear))
            .opacity(enabled ? (configuration.isPressed ? 0.7 : 1) : 0.45)
    }
}
