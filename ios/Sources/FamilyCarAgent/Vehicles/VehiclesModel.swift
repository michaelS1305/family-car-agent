import Foundation
#if canImport(Combine)
import Combine
#endif

@MainActor final class VehiclesModel: ObservableObject {
    @Published private(set) var rows: [ManagedVehicle] = []
    @Published private(set) var loaded = false
    @Published private(set) var loading = false
    @Published private(set) var loadError = false
    @Published private(set) var canCreate = false
    @Published private(set) var destination: VehiclesDestination?
    @Published private(set) var draft = VehicleDraft()
    @Published private(set) var manufacturers: [VehicleManufacturer] = []
    @Published private(set) var catalogLoaded = false
    @Published private(set) var catalogLoading = false
    @Published private(set) var catalogError = false
    @Published private(set) var pending: VehicleSubmission?
    @Published private(set) var submitting = false
    @Published private(set) var submitError: String?
    @Published private(set) var validationAttempted = false
    var fieldErrors: [VehicleFormField: String] {
        guard current, validationAttempted, pending == nil else { return [:] }
        var errors = draft.validationErrors
        // Catalog availability is a loading failure, not a mistake in user input.
        if !catalogLoaded { errors.removeValue(forKey: .manufacturer) }
        return errors
    }
    var firstInvalidField: VehicleFormField? { VehicleFormField.allCases.first { fieldErrors[$0] != nil } }
    var maySubmit: Bool { current && destination == .add && canCreate && !submitting }
    private let gateway: any VehiclesGateway
    private var identity: ChatIdentity?
    private var epoch = 0
    private var loadTask: Task<Void, Never>?
    private var catalogTask: Task<Void, Never>?
    private var submissionTask: Task<Void, Never>?
    init(gateway: any VehiclesGateway) { self.gateway = gateway }
    func detailsModel(_ id: UUID) -> VehicleDetailsModel { VehicleDetailsModel(gateway: gateway, vehicleID: id) }
    var current: Bool { identity != nil && identity == gateway.vehiclesIdentity }
    var visibleRows: [ManagedVehicle] { current ? rows : [] }
    var active: [ManagedVehicle] { visibleRows.filter { !$0.retired } }
    var retired: [ManagedVehicle] { visibleRows.filter(\.retired) }
    var mayAdd: Bool { current && canCreate && !loading && !loadError }
    var editable: Bool { current && destination == .add && pending == nil && !submitting }
    var matchingManufacturers: [VehicleManufacturer] {
        current ? manufacturers.filter { $0.name_he.range(of: draft.manufacturerQuery, options: .caseInsensitive) != nil } : []
    }
    func start() {
        guard let who = gateway.vehiclesIdentity else { stop(); return }
        guard who != identity else { return }
        stop(); identity = who; refresh()
    }
    func stop() {
        epoch += 1; loadTask?.cancel(); catalogTask?.cancel(); submissionTask?.cancel()
        loadTask = nil; catalogTask = nil; submissionTask = nil; identity = nil
        rows = []; loaded = false; loading = false; loadError = false; canCreate = false
        destination = nil; draft = VehicleDraft(); manufacturers = []; catalogLoaded = false
        catalogLoading = false; catalogError = false; pending = nil; submitting = false; submitError = nil
        validationAttempted = false
    }
    private func valid(_ version: Int) -> Bool { current && epoch == version && !Task.isCancelled }
    func refresh() {
        guard current, let who = identity, !loading, destination == nil else { return }
        let version = epoch
        loading = true; loadError = false; canCreate = false
        loadTask = Task { [weak self, gateway] in
            do {
                async let list = gateway.vehiclesRequest(identity: who, operation: .list)
                async let permission = gateway.vehiclesRequest(identity: who, operation: .permission)
                let replies = try await (list, permission)
                guard let self, self.valid(version) else { return }
                guard case .list(let rows) = replies.0, case .permission(let allowed) = replies.1,
                      Set(rows.map(\.id)).count == rows.count else { throw AuthFailure.invalidResponse }
                self.rows = rows; self.loaded = true; self.canCreate = allowed
            } catch {
                guard let self, self.valid(version) else { return }
                self.loadError = true
            }
            guard let self, self.valid(version) else { return }
            self.loading = false; self.loadTask = nil
        }
    }
    func add() {
        guard mayAdd, destination == nil else { return }
        draft = VehicleDraft(); pending = nil; submitError = nil; destination = .add
        validationAttempted = false
        loadManufacturers()
    }
    func select(_ id: UUID) {
        guard current, destination == nil, visibleRows.contains(where: { $0.id == id }) else { return }
        destination = .details(id)
    }
    func pop() {
        guard destination != nil else { return }
        submissionTask?.cancel(); submissionTask = nil
        destination = nil; draft = VehicleDraft(); pending = nil; submitting = false; submitError = nil
        validationAttempted = false
        // Local cancellation does not undo a POST accepted by the server.
        refresh()
    }
    func edit(_ value: VehicleDraft) {
        guard editable else { return }
        draft = value; submitError = nil
    }
    func queryManufacturer(_ value: String) {
        var valueDraft = draft; valueDraft.manufacturerQuery = value; valueDraft.manufacturer = nil; edit(valueDraft)
    }
    func chooseManufacturer(_ value: VehicleManufacturer) {
        guard manufacturers.contains(value) else { return }
        var valueDraft = draft; valueDraft.manufacturer = value; valueDraft.manufacturerQuery = value.name_he; edit(valueDraft)
    }
    func loadManufacturers() {
        guard current, let who = identity, !catalogLoaded, !catalogLoading, destination == .add else { return }
        let version = epoch
        catalogLoading = true; catalogError = false
        catalogTask = Task { [weak self, gateway] in
            do {
                let reply = try await gateway.vehiclesRequest(identity: who, operation: .manufacturers)
                guard let self, self.valid(version) else { return }
                guard case .manufacturers(let values) = reply, values.allSatisfy({ $0.id > 0 }),
                      Set(values.map(\.id)).count == values.count else { throw AuthFailure.invalidResponse }
                self.manufacturers = values; self.catalogLoaded = true
            } catch {
                guard let self, self.valid(version) else { return }
                self.catalogError = true
            }
            guard let self, self.valid(version) else { return }
            self.catalogLoading = false; self.catalogTask = nil
        }
    }
    func submit() {
        guard maySubmit, let who = identity else { return }
        validationAttempted = true
        guard draft.valid else { return }
        let request = pending ?? VehicleSubmission(requestID: UUID(), draft: draft)
        let version = epoch
        pending = request; submitting = true; submitError = nil
        submissionTask = Task { [weak self, gateway] in
            do {
                let reply = try await gateway.vehiclesRequest(identity: who, operation: .create(request))
                guard let self, self.valid(version), self.pending == request else { return }
                guard case .created = reply else { throw AuthFailure.invalidResponse }
                self.destination = nil; self.draft = VehicleDraft(); self.pending = nil
                self.validationAttempted = false
                self.submitting = false; self.submissionTask = nil; self.refresh()
            } catch {
                guard let self, self.valid(version), self.pending == request else { return }
                self.submitting = false; self.submissionTask = nil
                if case AuthFailure.rejected(403, _) = error { self.submitError = "אין הרשאה להוספת רכב" }
                else { self.submitError = "לא ניתן לאשר את הוספת הרכב. נסו שוב עם אותם הפרטים." }
            }
        }
    }
}
