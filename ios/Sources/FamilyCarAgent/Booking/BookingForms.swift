import SwiftUI

struct BookingForms: View {
    @ObservedObject var model: BookingModel
    let sheet: BookingModel.Sheet
    var body: some View {
        NavigationStack {
            Form {
                if let notice = model.notice { Text(notice).foregroundStyle(ChatStyle.ink) }
                if model.busy { ProgressView("שומר…") }
                switch sheet {
                case .editor: editor
                case .filters: filters
                case .cancellation:
                    if let row = model.confirmation {
                        Text("לבטל את ההזמנה?").font(.headline)
                        Text(row.vehicleName ?? "הזמנה כללית")
                        Text(BookingPreviewCalendar.label(row.start, format: "dd/MM/yyyy HH:mm") + " – " + BookingPreviewCalendar.label(row.end, format: "dd/MM/yyyy HH:mm"))
                        Button("אישור ביטול ההזמנה", role: .destructive) { model.submit() }
                            .disabled(!model.canWrite || !model.eligible(row))
                    }
                }
            }
            .navigationTitle(sheet == .filters ? "סינון הזמנות" : sheet == .cancellation ? "ביטול הזמנה" : "פרטי הזמנה")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("חזרה") { model.dismiss() }.disabled(model.busy) } }
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
            if model.startLocked { Text("ההזמנה כבר התחילה; לא ניתן לשנות את שעת ההתחלה.").font(.caption) }
            Button("שמירת הזמנה") { model.submit() }
                .disabled(!model.canSubmitDraft)
            if !model.busy && model.catalogLoaded && !model.catalogError && !model.canSubmitDraft {
                Text("יש לבחור רכב זמין וטווח שעות תקין. בשעת מעבר שעון חוזרת יש לבחור שעה חד־משמעית.").font(.caption)
            }
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
            Button("איפוס מסננים") { model.filters = BookingFilters() }
            Button("החלת מסננים") { model.applyFilters() }.disabled(model.busy)
        }
    }
    private func filterDate(start: Bool) -> some View {
        VStack(alignment: .leading) {
            Toggle(start ? "מתאריך ושעה" : "עד תאריך ושעה", isOn: Binding(get: {
                (start ? model.filters.start : model.filters.end) != nil
            }, set: { enabled in
                if start { model.filters.start = enabled ? model.calendar.selected : nil }
                else { model.filters.end = enabled ? BookingPreviewCalendar.calendar.date(byAdding: .day, value: 1, to: model.calendar.selected) : nil }
            }))
            if (start ? model.filters.start : model.filters.end) != nil {
                DatePicker(start ? "מתחיל ב־" : "מסתיים ב־", selection: Binding(get: {
                    (start ? model.filters.start : model.filters.end) ?? model.calendar.selected
                }, set: { value in
                    if start { model.filters.start = value } else { model.filters.end = value }
                }), displayedComponents: [.date, .hourAndMinute])
            }
        }
    }
}
