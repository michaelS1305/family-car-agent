import Foundation
#if canImport(Combine)
import Combine
#endif

@MainActor final class BookingModel: ObservableObject {
    enum Selection { case none, edit, cancel }
    enum Sheet: String, Identifiable { case editor, filters, cancellation; var id: String { rawValue } }
    @Published private(set) var calendar = BookingPreviewCalendar()
    @Published private(set) var rows: [BookingReservation] = []
    @Published private(set) var loading = false
    @Published private(set) var loaded = false
    @Published private(set) var readError = false
    @Published private(set) var busy = false
    @Published private(set) var notice: String?
    @Published private(set) var pending: BookingPending?
    @Published private(set) var selection = Selection.none
    @Published private(set) var sheet: Sheet?
    @Published private(set) var draft: BookingDraft?
    @Published private(set) var confirmation: BookingReservation?
    @Published private(set) var applied = BookingFilters()
    @Published var filters = BookingFilters()
    @Published private(set) var vehicles: [ManagedVehicle] = []
    @Published private(set) var members: [FamilyMember] = []
    @Published private(set) var catalogLoading = false
    @Published private(set) var catalogLoaded = false
    @Published private(set) var catalogError = false
    private let gateway: any BookingGateway
    private let clock: () -> Date
    private var identity: ChatIdentity?
    private var epoch = 0
    private var readVersion = 0
    private var catalogVersion = 0
    private var readTask: Task<Void, Never>?
    private var catalogTask: Task<Void, Never>?
    private var writeTask: Task<Void, Never>?
    private var loadedQuery: BookingQuery?
    init(gateway: any BookingGateway, now: @escaping () -> Date = { Date() }) {
        self.gateway = gateway; clock = now; calendar = BookingPreviewCalendar(now: now())
    }
    var current: Bool { identity != nil && identity == gateway.vehiclesIdentity }
    var query: BookingQuery { BookingQuery(calendar: calendar, filters: applied) }
    var canWrite: Bool { current && !busy && pending == nil }
    var canSubmitDraft: Bool {
        canWrite && catalogLoaded && !catalogLoading && !catalogError && draft?.valid(now: clock(), vehicles: vehicles) == true
    }
    var canAcknowledge: Bool { current && !busy && !loading && !readError && pending?.inspected == true && pending?.lastQuery == query && loadedQuery == query }
    var visibleRows: [BookingReservation] { current && loadedQuery == query ? rows : [] }
    var dayRows: [BookingReservation] { onDay(calendar.selected) }
    var reservationCountLabel: String { dayRows.count == 1 ? "הזמנה אחת" : "\(dayRows.count) הזמנות" }
    var startLocked: Bool { draft?.original.map { $0.start < clock() } ?? false }
    var activeVehicles: [ManagedVehicle] { vehicles.filter { !$0.retired } }
    func onDay(_ day: Date) -> [BookingReservation] {
        let dayStart = BookingPreviewCalendar.calendar.startOfDay(for: day)
        let start = max(dayStart, query.lower)
        let end = min(BookingPreviewCalendar.calendar.date(byAdding: .day, value: 1, to: dayStart)!, query.upper)
        guard start < end else { return [] }
        return visibleRows.filter { applied.matches($0) && $0.overlaps(start, end) }.sorted {
            $0.start == $1.start ? $0.id.uuidString < $1.id.uuidString : $0.start > $1.start
        }
    }
    func eligible(_ row: BookingReservation) -> Bool { current && row.eligible(at: clock()) }
    func synchronize() {
        guard identity != gateway.vehiclesIdentity else { return }
        epoch += 1; readVersion += 1; catalogVersion += 1
        readTask?.cancel(); catalogTask?.cancel(); writeTask?.cancel()
        identity = gateway.vehiclesIdentity
        rows = []; loadedQuery = nil; loaded = false; loading = false; readError = false
        busy = false; pending = nil; notice = nil; selection = .none; sheet = nil; draft = nil; confirmation = nil
        vehicles = []; members = []; catalogLoaded = false; catalogLoading = false; catalogError = false
        applied = BookingFilters(); filters = applied; calendar = BookingPreviewCalendar(now: clock())
    }
    func enter() { synchronize(); refresh() }
    // Model lives in the authenticated shell. Do not erase in-flight/uncertain writes on navigation.
    func leave() { if !busy { sheet = nil; draft = nil; confirmation = nil }; selection = .none }
    func moveMonth(_ delta: Int) { guard !busy else { return }; calendar.moveMonth(delta); selection = .none; refresh() }
    func select(_ date: Date) {
        guard !busy else { return }
        let old = query; calendar.select(date); selection = .none
        if query != old { refresh() }
    }
    func today() { select(clock()) }
    private func valid(_ version: Int, _ who: ChatIdentity) -> Bool { current && epoch == version && identity == who }
    func refresh() {
        synchronize()
        guard current, let who = identity, !busy else { return }
        readVersion += 1; readTask?.cancel()
        let version = readVersion, context = epoch, key = query
        pending?.lastQuery = nil; loading = true; readError = false; loaded = false
        rows = []; loadedQuery = nil
        if key.empty { loading = false; loaded = true; loadedQuery = key; return }
        readTask = Task { [weak self, gateway] in
            do {
                let data = try await gateway.reservationData(identity: who, method: "GET", cancel: false, query: key.items, body: nil)
                let rows = try BookingReservation.decodeList(data)
                guard let self, self.valid(context, who), self.readVersion == version, self.query == key else { return }
                self.rows = rows; self.loadedQuery = key; self.loaded = true; self.loading = false
                self.pending?.observe(key)
            } catch {
                guard let self, self.valid(context, who), self.readVersion == version else { return }
                self.loading = false; self.readError = true
            }
        }
    }
    func loadChoices() {
        guard current, let who = identity, !catalogLoading else { return }
        catalogVersion += 1
        let version = catalogVersion, context = epoch
        catalogLoading = true; catalogError = false; catalogLoaded = false
        catalogTask = Task { [weak self, gateway] in
            do {
                async let cars = gateway.vehiclesRequest(identity: who, operation: .list)
                async let people = gateway.historyRequest(identity: who, operation: .members)
                let (carReply, peopleReply) = try await (cars, people)
                guard case .list(let cars) = carReply, case .members(let people) = peopleReply else { throw AuthFailure.invalidResponse }
                guard let self, self.valid(context, who), self.catalogVersion == version else { return }
                self.vehicles = cars; self.members = people; self.catalogLoading = false; self.catalogLoaded = true
                if self.draft?.original == nil, self.draft != nil {
                    let active = cars.filter { !$0.retired }
                    if !active.contains(where: { $0.id == self.draft?.vehicle }) { self.draft?.vehicle = active.count == 1 ? active[0].id : nil }
                }
            } catch {
                guard let self, self.valid(context, who), self.catalogVersion == version else { return }
                self.catalogLoading = false; self.catalogError = true
            }
        }
    }
    func openCreate() {
        guard canWrite else { return }
        let times = BookingTime.defaults(selected: calendar.selected, now: clock())
        draft = BookingDraft(start: times.start, end: times.end)
        confirmation = nil; sheet = .editor; notice = nil; selection = .none
        loadChoices()
    }
    var editorDay: Date { max(calendar.selected, BookingPreviewCalendar.calendar.startOfDay(for: clock())) }
    func updateDraft(_ value: BookingDraft) {
        guard canWrite, sheet == .editor, let old = draft, old.original == value.original else { return }
        guard !startLocked || old.start == value.start else { return }
        draft = value; notice = nil
    }
    func selectMode(_ mode: Selection) {
        guard canWrite, sheet == nil else { return }
        selection = selection == mode ? .none : mode; notice = nil
    }
    func choose(_ row: BookingReservation) {
        guard canWrite, eligible(row), visibleRows.contains(row) else { return }
        switch selection {
        case .edit:
            draft = BookingDraft(original: row, vehicle: row.vehicle, start: row.start, end: row.end)
            sheet = .editor; loadChoices()
        case .cancel: confirmation = row; sheet = .cancellation
        case .none: break
        }
    }
    func openFilters() {
        guard current, !busy, sheet == nil else { return }
        filters = applied; sheet = .filters; notice = nil; loadChoices()
    }
    func applyFilters() {
        guard current, !busy, sheet == .filters else { return }
        guard filters.valid else { notice = "יש לבחור טווח תאריכים תקין."; return }
        applied = filters; sheet = nil; selection = .none; refresh()
    }
    func dismiss() { guard !busy else { return }; sheet = nil; draft = nil; confirmation = nil; filters = applied }
    func submit() {
        guard canWrite, let who = identity else { return }
        let operation: BookingWrite
        if let draft, sheet == .editor {
            guard catalogLoaded, !catalogError, !catalogLoading, draft.valid(now: clock(), vehicles: vehicles) else {
                notice = "יש לבחור רכב זמין ושעות תקינות שאינן בעבר."; return
            }
            operation = .save(draft)
        } else if let row = confirmation, sheet == .cancellation, eligible(row) { operation = .cancel(row) }
        else { return }
        let body: Data
        do { body = try operation.body() } catch { notice = "יש לבדוק את פרטי ההזמנה."; return }
        busy = true; pending = BookingPending(operation: operation); notice = nil
        readVersion += 1; readTask?.cancel(); loading = false; loadedQuery = nil; rows = []
        let context = epoch
        writeTask = Task { [weak self, gateway] in
            do {
                let data = try await gateway.reservationData(identity: who, method: operation.method, cancel: operation.isCancel, query: [], body: body)
                var saved: BookingReservation?
                if operation.isCancel {
                    struct Receipt: Decodable { let cancelled: Bool }
                    guard try JSONDecoder().decode(Receipt.self, from: data).cancelled else { throw AuthFailure.invalidResponse }
                } else {
                    let row = try JSONDecoder().decode(BookingReservation.self, from: data)
                    guard row.mine, operation.original == nil || row.id == operation.original?.id else { throw AuthFailure.invalidResponse }
                    saved = row
                }
                guard let self, self.valid(context, who) else { return }
                self.busy = false; self.pending = nil; self.dismiss(); self.selection = .none
                self.notice = saved == nil ? "ההזמנה בוטלה." : "ההזמנה נשמרה."
                if let saved {
                    self.calendar.select(saved.start)
                    if !self.applied.matches(saved) { self.notice = "ההזמנה נשמרה, אך אינה מוצגת תחת המסננים הנוכחיים." }
                }
                self.refresh()
            } catch {
                guard let self, self.valid(context, who) else { return }
                self.busy = false
                if case AuthFailure.rejected(let status, let code) = error, (400..<500).contains(status) {
                    self.pending = nil; self.notice = Self.rejection(code, status: status)
                    if status == 403 || status == 404 { self.dismiss(); self.selection = .none }
                    if code == "VEHICLE_REQUIRED" || code == "VEHICLE_NOT_FOUND_OR_UNAVAILABLE" { self.loadChoices() }
                    self.refresh()
                } else {
                    self.dismiss(); self.selection = .none
                    self.notice = "תוצאת הפעולה אינה ודאית. יש לבדוק את ההזמנות לפני פעולה נוספת. הפעולה לא נשלחה שוב."
                }
            }
        }
    }
    func inspectPending(original: Bool = false) {
        guard current, !busy, let pending else { return }
        applied = BookingFilters(); filters = applied
        calendar.select(original ? pending.operation.original?.start ?? pending.operation.start : pending.operation.start)
        refresh()
    }
    func acknowledge() {
        guard canAcknowledge else { return }
        pending = nil; notice = "אישרת להמשיך למרות אי־הוודאות. הפעולה לא נשלחה שוב."
    }
    static func rejection(_ code: String, status: Int) -> String {
        if status == 403 { return "אין הרשאה לביצוע הפעולה." }
        switch code {
        case "RESERVATION_CONFLICT": return "קיימת הזמנה חופפת לרכב או לטווח שנבחר."
        case "VEHICLE_REQUIRED": return "יש לבחור רכב להזמנה."
        case "VEHICLE_NOT_FOUND_OR_UNAVAILABLE": return "הרכב אינו זמין. יש לבחור רכב פעיל."
        case "RESERVATION_NOT_FOUND_OR_UNAVAILABLE", "RESERVATION_AMBIGUOUS": return "ההזמנה אינה זמינה לעריכה או לביטול."
        case "INVALID_RESERVATION_TIME", "RESERVATION_TIME_IN_PAST": return "יש לבדוק את שעות ההתחלה והסיום. לא ניתן לבחור זמן שכבר עבר."
        default: return "לא ניתן להשלים את הפעולה כרגע."
        }
    }
}
