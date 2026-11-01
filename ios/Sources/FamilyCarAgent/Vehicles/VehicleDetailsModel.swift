import Foundation
#if canImport(Combine)
import Combine
#endif

enum VehicleDetailsSheet: String, Identifiable { case edit, maintenance, retire, connection; var id: String { rawValue } }

@MainActor final class VehicleDetailsModel: ObservableObject {
    let vehicleID: UUID
    private let gateway: any VehiclesGateway
    private var identity: ChatIdentity?
    private var epoch = 0
    private var tasks: [Task<Void, Never>] = []
    @Published private(set) var detail: VehicleDetail?
    @Published private(set) var loading = false
    @Published private(set) var loadError = false
    @Published private(set) var admin = false
    @Published private(set) var maintenance: [VehicleMaintenance] = []
    @Published private(set) var maintenanceLoading = false
    @Published private(set) var maintenanceError = false
    @Published private(set) var sheet: VehicleDetailsSheet?
    @Published private(set) var busy = false
    @Published private(set) var operationError: String?
    @Published private(set) var requiresReview = false
    @Published private(set) var draft = VehicleDraft()
    @Published private(set) var catalog: [VehicleManufacturer] = []
    @Published private(set) var catalogLoading = false
    @Published private(set) var catalogLoaded = false
    @Published private(set) var catalogError = false
    @Published private(set) var description = ""
    @Published private(set) var day = VehicleDay.today()
    @Published private(set) var maintenanceID: UUID?
    @Published private(set) var deleteConfirmation = false
    init(gateway: any VehiclesGateway, vehicleID: UUID) { self.gateway = gateway; self.vehicleID = vehicleID }
    var current: Bool { identity != nil && identity == gateway.vehiclesIdentity }
    var canManage: Bool { current && admin && detail?.vehicle.retired == false && !loading && !loadError }
    var canWrite: Bool { canManage && !busy && !requiresReview }
    var matches: [VehicleManufacturer] { catalog.filter { $0.name_he.range(of: draft.manufacturerQuery, options: .caseInsensitive) != nil } }
    private func valid(_ version: Int) -> Bool { current && epoch == version && !Task.isCancelled }
    func start() {
        guard let who = gateway.vehiclesIdentity else { stop(); return }
        guard identity != who else { return }
        stop(); identity = who; refresh(); refreshMaintenance()
    }
    func stop() {
        epoch += 1; tasks.forEach { $0.cancel() }; tasks = []; identity = nil
        detail = nil; loading = false; loadError = false; admin = false; maintenance = []
        maintenanceLoading = false; maintenanceError = false; sheet = nil; busy = false
        operationError = nil; requiresReview = false; draft = VehicleDraft(); catalog = []
        catalogLoaded = false; catalogLoading = false; catalogError = false
        description = ""; day = .today(); maintenanceID = nil; deleteConfirmation = false
    }
    private func request(_ operation: VehicleDetailsOperation, who: ChatIdentity) async throws -> VehicleDetailsReply {
        guard let api = gateway as? any VehicleDetailsGateway else { throw AuthFailure.configuration }
        return try await api.vehicleDetailsRequest(identity: who, id: vehicleID, operation: operation)
    }
    func refresh() {
        guard current, let who = identity, !loading, !busy else { return }
        loading = true; loadError = false; admin = false
        let version = epoch
        tasks.append(Task { [weak self, gateway] in
            guard let self else { return }
            do {
                let reply = try await self.request(.detail, who: who)
                let permission = try await gateway.vehiclesRequest(identity: who, operation: .permission)
                guard self.valid(version) else { return }
                guard case .detail(let value) = reply, value.vehicle.id == self.vehicleID,
                      case .permission(let allowed) = permission else { throw AuthFailure.invalidResponse }
                self.detail = value; self.admin = allowed
                if value.vehicle.retired || !allowed { self.sheet = nil; self.deleteConfirmation = false }
            } catch { guard self.valid(version) else { return }; self.loadError = true }
            guard self.valid(version) else { return }; self.loading = false
        })
    }
    func refreshMaintenance() {
        guard current, let who = identity, !maintenanceLoading, !busy else { return }
        let version = epoch; maintenanceLoading = true; maintenanceError = false
        tasks.append(Task { [weak self] in
            guard let self else { return }
            do {
                let reply = try await self.request(.maintenance, who: who)
                guard self.valid(version) else { return }
                guard case .maintenance(let rows) = reply, Set(rows.map(\.id)).count == rows.count else { throw AuthFailure.invalidResponse }
                self.maintenance = rows
            } catch { guard self.valid(version) else { return }; self.maintenanceError = true }
            guard self.valid(version) else { return }; self.maintenanceLoading = false
        })
    }
    func open(_ value: VehicleDetailsSheet) {
        guard current, !busy, !requiresReview, let v = detail?.vehicle, !v.retired else { return }
        if value != .connection && !canManage { return }
        if value == .maintenance && (maintenanceLoading || maintenanceError) { return }
        guard sheet == nil else { return }
        sheet = value; operationError = nil; maintenanceID = nil; description = ""; day = .today(); deleteConfirmation = false
        let maker = v.manufacturerID.flatMap { id in v.manufacturerName.map { VehicleManufacturer(id: id, name_he: $0) } }
        draft = VehicleDraft(name: v.name, category: v.category, manufacturer: maker, manufacturerQuery: maker?.name_he ?? "", model: v.model ?? "", plate: v.plate ?? "")
        if value == .edit { loadCatalog() }
    }
    func openMaintenance(_ item: VehicleMaintenance) {
        guard canWrite, !maintenanceLoading, !maintenanceError, maintenance.contains(item), sheet == nil else { return }
        open(.maintenance)
        guard sheet == .maintenance else { return }
        maintenanceID = item.id; description = item.description; day = item.day
    }
    func close() { guard !busy else { return }; sheet = nil; deleteConfirmation = false }
    func edit(_ value: VehicleDraft) { guard canWrite, sheet == .edit else { return }; draft = value }
    func query(_ value: String) { var d = draft; d.manufacturer = nil; d.manufacturerQuery = value; edit(d) }
    func choose(_ value: VehicleManufacturer) {
        guard catalog.contains(value) else { return }
        var d = draft; d.manufacturer = value; d.manufacturerQuery = value.name_he; edit(d)
    }
    func editMaintenance(_ text: String, day: VehicleDay) {
        guard canWrite, sheet == .maintenance else { return }; description = text; self.day = day
    }
    func loadCatalog() {
        guard current, let who = identity, !catalogLoading, !catalogLoaded else { return }
        let version = epoch; catalogLoading = true; catalogError = false
        tasks.append(Task { [weak self, gateway] in
            guard let self else { return }
            do {
                let reply = try await gateway.vehiclesRequest(identity: who, operation: .manufacturers)
                guard self.valid(version) else { return }
                guard case .manufacturers(let values) = reply, values.allSatisfy({ $0.id > 0 }), Set(values.map(\.id)).count == values.count else { throw AuthFailure.invalidResponse }
                self.catalog = values; self.catalogLoaded = true
            } catch { guard self.valid(version) else { return }; self.catalogError = true }
            guard self.valid(version) else { return }; self.catalogLoading = false
        })
    }
    func requestDelete() { if canWrite && sheet == .maintenance && maintenanceID != nil { deleteConfirmation = true } }
    func cancelDelete() { if !busy { deleteConfirmation = false } }
    func confirmDelete() {
        guard deleteConfirmation, sheet == .maintenance, let id = maintenanceID else { return }
        write(.delete(id))
    }
    func complete() {
        guard sheet == .maintenance, let id = maintenanceID, maintenance.contains(where: { $0.id == id && !$0.completed }) else { return }
        write(.complete(id))
    }
    func submit() {
        switch sheet {
        case .edit:
            guard draft.valid, let maker = draft.manufacturer, catalog.contains(maker) else { return }
            write(.edit(draft))
        case .maintenance:
            guard !description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
            let payload = MaintenanceEdit(description: description, scheduled_date: day)
            if let id = maintenanceID { write(.update(id, payload)) } else { write(.add(payload)) }
        case .retire: write(.retire) // Only the explicit destructive confirmation calls submit.
        default: return
        }
    }
    private func write(_ operation: VehicleDetailsOperation) {
        guard canWrite, !maintenanceLoading, let who = identity else { return }
        let version = epoch; busy = true; operationError = nil
        tasks.append(Task { [weak self] in
            guard let self else { return }
            do {
                guard case .saved = try await self.request(operation, who: who) else { throw AuthFailure.invalidResponse }
                guard self.valid(version) else { return }
                self.busy = false; self.sheet = nil; self.deleteConfirmation = false
                self.refresh(); self.refreshMaintenance()
            } catch {
                guard self.valid(version) else { return }
                self.busy = false; self.requiresReview = true; self.deleteConfirmation = false
                if case AuthFailure.rejected(403, _) = error { self.operationError = "אין הרשאה לביצוע הפעולה" }
                else if case .retire = operation, case AuthFailure.rejected(409, _) = error {
                    self.operationError = "לא ניתן להוציא את הרכב משימוש כעת. ייתכן שהוא בשימוש."
                } else { self.operationError = "לא ניתן לאשר שהשינוי נשמר. רעננו ובדקו את נתוני הרכב והטיפולים לפני פעולה נוספת." }
                // Freeze writes until an explicit reconciliation succeeds. Never replay a non-idempotent POST.
            }
        })
    }
    func reviewServerState() {
        guard current, requiresReview, !busy, !loading, !maintenanceLoading, let who = identity else { return }
        let version = epoch; loading = true; maintenanceLoading = true; admin = false
        tasks.append(Task { [weak self, gateway] in
            guard let self else { return }
            do {
                let detail = try await self.request(.detail, who: who)
                let rows = try await self.request(.maintenance, who: who)
                let permission = try await gateway.vehiclesRequest(identity: who, operation: .permission)
                guard self.valid(version) else { return }
                guard case .detail(let d) = detail, d.vehicle.id == self.vehicleID,
                      case .maintenance(let m) = rows, Set(m.map(\.id)).count == m.count,
                      case .permission(let allowed) = permission else { throw AuthFailure.invalidResponse }
                self.detail = d; self.maintenance = m; self.admin = allowed
                self.requiresReview = false; self.loadError = false; self.maintenanceError = false
                self.sheet = nil; self.operationError = nil // User reviews the refreshed list before opening a new operation.
            } catch { guard self.valid(version) else { return }; self.loadError = true; self.maintenanceError = true }
            guard self.valid(version) else { return }; self.loading = false; self.maintenanceLoading = false
        })
    }
}
