import Foundation
#if canImport(Combine)
import Combine
#endif

@MainActor final class HistoryModel: ObservableObject {
    enum CurrentStatus { case loading, ready, unavailable }
    @Published private(set) var rows: [HistoryUsage] = []
    @Published private(set) var loading = false
    @Published private(set) var loaded = false
    @Published private(set) var pageError = false
    @Published private(set) var hasMore = false
    @Published private(set) var currentStatus = CurrentStatus.loading
    @Published private(set) var vehicles: [HistoryVehicle] = []
    @Published private(set) var members: [FamilyMember] = []
    @Published private(set) var membersLoading = false
    @Published private(set) var membersError = false
    @Published private(set) var illustrations: [UUID: VehicleCategory] = [:]
    @Published private(set) var applied = HistoryFilters()
    @Published var draft = HistoryFilters()
    @Published var sheet = false
    @Published private(set) var rangeError = false
    private let gateway: any HistoryGateway
    private var identity: ChatIdentity?
    private var generation = 0
    private var pageGeneration = 0
    private var cursor: UUID?
    private var seenCursors = Set<UUID>()
    private var pageTask: Task<Void, Never>?
    private var currentTask: Task<Void, Never>?
    private var membersTask: Task<Void, Never>?
    private var imagesTask: Task<Void, Never>?
    init(gateway: any HistoryGateway) { self.gateway = gateway }
    var current: Bool { identity != nil && identity == gateway.vehiclesIdentity }
    var visibleRows: [HistoryUsage] { current ? rows : [] }
    var active: [HistoryVehicle] { current && currentStatus == .ready ? vehicles.filter(\.inUse) : [] }
    func illustration(_ id: UUID) -> String { VehicleCategory.illustration(current ? illustrations[id] : nil) }
    private func valid(_ value: Int) -> Bool { current && generation == value && !Task.isCancelled }
    func start() {
        guard let who = gateway.vehiclesIdentity else { stop(); return }
        guard identity != who else { return }
        stop(); identity = who; refresh()
    }
    func stop() {
        generation += 1; pageGeneration += 1
        pageTask?.cancel(); currentTask?.cancel(); membersTask?.cancel(); imagesTask?.cancel()
        pageTask = nil; currentTask = nil; membersTask = nil; imagesTask = nil; identity = nil
        rows = []; vehicles = []; members = []; illustrations = [:]
        loading = false; loaded = false; pageError = false; hasMore = false; cursor = nil; seenCursors = []
        membersLoading = false; membersError = false; currentStatus = .loading
        applied = HistoryFilters(); draft = applied; sheet = false; rangeError = false
    }
    func refresh() {
        guard current else { return }
        resetPages(applied); refreshCurrent(); refreshMembers(); refreshImages()
    }
    func openFilters() { guard current else { return }; draft = applied; rangeError = false; sheet = true }
    func dismissFilters() { sheet = false; draft = applied; rangeError = false }
    func apply() {
        guard current else { return }
        guard draft.valid else { rangeError = true; return }
        resetPages(draft); sheet = false; rangeError = false
    }
    func clear() { guard current else { return }; draft = HistoryFilters(); rangeError = false; resetPages(draft) }
    private func resetPages(_ filters: HistoryFilters) {
        pageTask?.cancel(); pageGeneration += 1; pageTask = nil
        applied = filters; rows = []; cursor = nil; seenCursors = []; hasMore = false
        loading = false; loaded = false; pageError = false; loadPage()
    }
    func nearEnd(_ id: UUID) {
        guard current, loaded, hasMore, !pageError, rows.suffix(3).contains(where: { $0.id == id }) else { return }
        loadPage()
    }
    func retry() { guard pageError else { return }; loadPage() }
    private func loadPage() {
        guard current, let who = identity, !loading, !loaded || hasMore else { return }
        let epoch = generation, pageEpoch = pageGeneration, requested = cursor, filters = applied
        loading = true; pageError = false
        pageTask = Task { [weak self, gateway] in
            do {
                let reply = try await gateway.historyRequest(identity: who, operation: .page(filters, requested))
                guard let self, self.valid(epoch), self.pageGeneration == pageEpoch else { return }
                guard case .page(let page) = reply else { throw AuthFailure.invalidResponse }
                if let next = page.next_cursor, next == requested || self.seenCursors.contains(next) { throw AuthFailure.invalidResponse }
                var ids = Set(self.rows.map(\.id))
                self.rows += page.recent_usage.filter { ids.insert($0.id).inserted }
                if let next = page.next_cursor { self.seenCursors.insert(next) }
                self.cursor = page.next_cursor; self.hasMore = page.has_more; self.loaded = true
            } catch {
                guard let self, self.valid(epoch), self.pageGeneration == pageEpoch else { return }
                self.pageError = true
            }
            guard let self, self.valid(epoch), self.pageGeneration == pageEpoch else { return }
            self.loading = false; self.pageTask = nil
        }
    }
    func refreshCurrent() {
        guard current, let who = identity, currentTask == nil else { return }
        let epoch = generation; currentStatus = .loading
        currentTask = Task { [weak self, gateway] in
            do {
                let reply = try await gateway.historyRequest(identity: who, operation: .current)
                guard let self, self.valid(epoch) else { return }
                guard case .current(let values) = reply, Set(values.map(\.id)).count == values.count else { throw AuthFailure.invalidResponse }
                self.vehicles = values; self.currentStatus = .ready
            } catch {
                guard let self, self.valid(epoch) else { return }; self.currentStatus = .unavailable
            }
            guard let self, self.valid(epoch) else { return }; self.currentTask = nil
        }
    }
    func refreshMembers() {
        guard current, let who = identity, membersTask == nil else { return }
        let epoch = generation; membersLoading = true; membersError = false
        membersTask = Task { [weak self, gateway] in
            do {
                let reply = try await gateway.historyRequest(identity: who, operation: .members)
                guard let self, self.valid(epoch) else { return }
                guard case .members(let values) = reply, Set(values.map(\.id)).count == values.count else { throw AuthFailure.invalidResponse }
                self.members = values
            } catch {
                guard let self, self.valid(epoch) else { return }; self.membersError = true
            }
            guard let self, self.valid(epoch) else { return }; self.membersLoading = false; self.membersTask = nil
        }
    }
    private func refreshImages() {
        guard current, let who = identity, imagesTask == nil else { return }
        let epoch = generation
        imagesTask = Task { [weak self, gateway] in
            do {
                let reply = try await gateway.vehiclesRequest(identity: who, operation: .list)
                guard let self, self.valid(epoch) else { return }
                guard case .list(let values) = reply, Set(values.map(\.id)).count == values.count else { throw AuthFailure.invalidResponse }
                self.illustrations = Dictionary(uniqueKeysWithValues: values.compactMap { v in v.category.map { (v.id, $0) } })
            } catch { /* Optional artwork lookup must never block history. */ }
            guard let self, self.valid(epoch) else { return }; self.imagesTask = nil
        }
    }
}
