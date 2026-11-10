import Foundation
#if !canImport(Combine)
protocol ObservableObject: AnyObject {}
@propertyWrapper struct Published<Value> { var wrappedValue: Value; init(wrappedValue: Value) { self.wrappedValue = wrappedValue } }
#endif

private func reservation(_ id: UUID = UUID(), mine: Bool = true, start: String = "2026-11-12T14:00:00", end: String = "2026-11-12T15:00:00") -> Data {
    try! JSONSerialization.data(withJSONObject: ["reservation_ref": id.uuidString, "member_ref": "11111111-1111-4111-8111-111111111111",
        "owner_name": "Synthetic", "start_time": start, "end_time": end, "is_mine": mine,
        "vehicle_ref": NSNull(), "vehicle_display_name": NSNull(), "vehicle_category": NSNull()])
}
private func list(_ row: Data) -> Data { Data("[".utf8) + row + Data("]".utf8) }

@MainActor private final class BookingMock: BookingGateway {
    var vehiclesIdentity: ChatIdentity? = ChatIdentity(owner: UUID(), user: 1, family: 2, generation: 1, version: 1)
    var reads: [CheckedContinuation<Data, any Error>] = []
    var writes: [CheckedContinuation<Data, any Error>] = []
    var requests: [(String, Bool, [URLQueryItem], Data?)] = []
    var failCatalog = false
    func reservationData(identity: ChatIdentity, method: String, cancel: Bool, query: [URLQueryItem], body: Data?) async throws -> Data {
        precondition(identity == vehiclesIdentity)
        requests.append((method, cancel, query, body))
        return try await withCheckedThrowingContinuation { continuation in
            if method == "GET" { reads.append(continuation) } else { writes.append(continuation) }
        }
    }
    func vehiclesRequest(identity: ChatIdentity, operation: VehiclesOperation) async throws -> VehiclesReply {
        if failCatalog { throw AuthFailure.network }; return .list([])
    }
    func historyRequest(identity: ChatIdentity, operation: HistoryOperation) async throws -> HistoryReply {
        if failCatalog { throw AuthFailure.network }; return .members([])
    }
}
@main struct BookingChecks {
    @MainActor static func wait(_ condition: () -> Bool) async {
        for _ in 0..<5000 { if condition() { return }; await Task.yield() }
        preconditionFailure("Async condition not reached")
    }
    static func rejects(_ operation: () throws -> Void) {
        do { try operation(); preconditionFailure("Expected rejection") } catch { }
    }
    @MainActor static func main() async throws {
        let now = try BookingTime.parse("2026-11-10T12:00:00")
        let defaults = BookingTime.defaults(selected: now, now: now)
        precondition(BookingTime.wire(defaults.start) == "2026-11-10T12:15:00")
        precondition(BookingTime.wire(defaults.end) == "2026-11-10T13:15:00")
        let future = try BookingTime.parse("2026-11-12T00:00:00")
        let futureDefaults = BookingTime.defaults(selected: future, now: now)
        precondition(BookingTime.wire(futureDefaults.start) == "2026-11-12T09:00:00")
        precondition(BookingTime.wire(futureDefaults.end) == "2026-11-12T10:00:00")
        let springStart = try BookingTime.parse("2026-03-27T01:30:00+02:00")
        let springEnd = try BookingTime.parse("2026-03-27T03:30:00+03:00")
        precondition(springEnd.timeIntervalSince(springStart) == 3600)
        precondition(BookingDraft(start: springStart, end: springEnd).valid(now: springStart.addingTimeInterval(-60), vehicles: []))
        rejects { _ = try BookingTime.parse("2026-03-27T02:30:00") }
        rejects { _ = try BookingTime.parse("2026-10-25T01:30:00") }
        let first = try BookingTime.parse("2026-10-25T01:30:00+03:00")
        let second = try BookingTime.parse("2026-10-25T01:30:00+02:00")
        precondition(second.timeIntervalSince(first) == 3600 && BookingTime.wire(first) == BookingTime.wire(second))
        precondition(!BookingTime.unambiguous(first) && !BookingTime.unambiguous(second))
        let firstUTC = try BookingTime.parse("2026-10-24T22:30:00Z")
        precondition(firstUTC == first)
        let earlierWall = try BookingTime.parse("2026-10-25T01:15:00+02:00")
        precondition(earlierWall > first && BookingTime.wire(earlierWall) < BookingTime.wire(first))
        precondition(!BookingDraft(start: first, end: earlierWall).valid(now: first.addingTimeInterval(-60), vehicles: []))
        precondition(!BookingDraft(start: first, end: second).valid(now: first.addingTimeInterval(-60), vehicles: []))
        let after = try BookingTime.parse("2026-10-25T02:30:00+02:00")
        precondition(!BookingDraft(start: second, end: after).valid(now: first, vehicles: []))
        let before = try BookingTime.parse("2026-10-25T00:30:00+03:00")
        precondition(BookingDraft(start: before, end: after).valid(now: before.addingTimeInterval(-60), vehicles: []))
        let rollover = try BookingTime.parse("2026-11-10T23:59:00")
        let rolled = BookingTime.defaults(selected: now, now: rollover)
        precondition(rolled.start > rollover && BookingTime.wire(rolled.start) == "2026-11-11T00:00:00")
        let autumnDefaults = BookingTime.defaults(selected: first, now: first)
        precondition(autumnDefaults.start > first && BookingTime.unambiguous(autumnDefaults.start) && BookingTime.unambiguous(autumnDefaults.end))
        print("PASS: future defaults, midnight rollover, Israel DST gaps/folds, explicit offsets and conservative wall-clock writes")
        let rowData = reservation(), row = try JSONDecoder().decode(BookingReservation.self, from: rowData)
        precondition(row.mine && row.vehicle == nil && row.category == nil && row.owner == "Synthetic")
        let utc = try BookingTime.parse("2026-11-10T10:00:00Z")
        precondition(utc == now)
        precondition(BookingTime.wire(now) == "2026-11-10T12:00:00")
        rejects { _ = try BookingTime.parse("invalid") }
        rejects { _ = try BookingReservation.decodeList(Data("[".utf8) + rowData + Data(",".utf8) + rowData + Data("]".utf8)) }
        rejects { _ = try JSONDecoder().decode(BookingReservation.self, from: reservation(start: "2026-11-12T16:00:00")) }
        let foreign = try JSONDecoder().decode(BookingReservation.self, from: reservation(mine: false))
        precondition(!foreign.eligible(at: now) && row.eligible(at: now) && !row.eligible(at: row.end))
        let vehicle = UUID(), member = UUID()
        let filters = BookingFilters(vehicle: vehicle, member: member, start: row.start, end: row.end)
        let query = BookingQuery(calendar: BookingPreviewCalendar(now: now), filters: filters)
        let items = Dictionary(uniqueKeysWithValues: query.items.map { ($0.name, $0.value!) })
        precondition(items == ["range_start": "2026-11-12T14:00:00", "range_end": "2026-11-12T15:00:00", "scope": "all", "vehicle_ref": vehicle.uuidString.lowercased(), "member_ref": member.uuidString.lowercased()])
        precondition(!filters.matches(row))
        precondition(!BookingFilters(start: row.end, end: row.start).valid)
        var draft = BookingDraft(start: row.start, end: row.end)
        precondition(draft.valid(now: now, vehicles: []))
        let json = try JSONSerialization.jsonObject(with: draft.body()) as! [String: Any]
        precondition(json["vehicle_ref"] == nil && json["request_id"] == nil && json.count == 2)
        draft.start = row.end; precondition(!draft.valid(now: now, vehicles: []))
        draft = BookingDraft(original: row, vehicle: nil, start: row.start, end: row.end)
        precondition(draft.valid(now: row.start.addingTimeInterval(60), vehicles: []))
        draft.start = row.start.addingTimeInterval(60)
        precondition(!draft.valid(now: row.start.addingTimeInterval(120), vehicles: []))
        let cancelBody = try JSONSerialization.jsonObject(with: BookingWrite.cancel(row).body()) as! [String: String]
        precondition(cancelBody == ["reservation_ref": row.id.uuidString.lowercased()])
        let api = try AuthAPI(environment: .development, publicKey: "sb_publishable_synthetic")
        let request = try api.makeReservationRequest(token: "synthetic", method: "GET", cancel: false, query: query.items, body: nil)
        precondition(request.url?.path == "/api/reservations" && request.value(forHTTPHeaderField: "Authorization") == "Bearer synthetic")
        precondition(request.value(forHTTPHeaderField: "apikey") == nil && request.httpBody == nil)
        let cancelRequest = try api.makeReservationRequest(token: "synthetic", method: "POST", cancel: true, query: [], body: BookingWrite.cancel(row).body())
        precondition(cancelRequest.url?.path == "/api/reservations/cancel" && cancelRequest.httpMethod == "POST")
        precondition(AuthAPI.reservationFailure(status: 409, data: Data(#"{"detail":{"code":"RESERVATION_CONFLICT","message":"untrusted"}}"#.utf8)) == .rejected(409, "RESERVATION_CONFLICT"))
        precondition(AuthAPI.reservationFailure(status: 500, data: Data(#"{"detail":{"code":"untrusted"}}"#.utf8)) == .rejected(500, ""))
        let car = try JSONDecoder().decode(ManagedVehicle.self, from: Data("""
        {"vehicle_ref":"\(vehicle)","display_name":"Synthetic","created_at":"2026-01-01T00:00:00Z","retired_at":null,"category":"suv","manufacturer_id":null,"manufacturer_name_he":null,"model":null,"license_plate":null}
        """.utf8))
        let general = BookingDraft(start: row.start, end: row.end)
        precondition(!general.valid(now: now, vehicles: [car]))
        var specific = general; specific.vehicle = vehicle
        precondition(specific.valid(now: now, vehicles: [car]))
        specific.vehicle = UUID(); precondition(!specific.valid(now: now, vehicles: [car]))
        let later = try BookingTime.parse("2027-01-10T14:00:00")
        var pending = BookingPending(operation: .save(BookingDraft(original: row, start: later, end: later.addingTimeInterval(3600))))
        pending.observe(BookingQuery(calendar: BookingPreviewCalendar(now: now), filters: BookingFilters()))
        precondition(!pending.inspected)
        pending.observe(BookingQuery(calendar: BookingPreviewCalendar(now: later), filters: BookingFilters(member: UUID())))
        precondition(!pending.inspected)
        pending.observe(BookingQuery(calendar: BookingPreviewCalendar(now: later), filters: BookingFilters()))
        precondition(pending.inspected)
        print("PASS: reservation decoding, query/filter contract, time offsets, ownership, elapsed/start-lock and write payloads")

        let gateway = BookingMock()
        let sut = BookingModel(gateway: gateway, now: { now })
        sut.enter(); await wait { gateway.reads.count == 1 }
        sut.moveMonth(1); await wait { gateway.reads.count == 2 }
        gateway.reads.removeLast().resume(returning: Data("[]".utf8)); await wait { sut.loaded }
        gateway.reads.removeFirst().resume(returning: list(rowData))
        for _ in 0..<30 { await Task.yield() }
        precondition(sut.visibleRows.isEmpty)
        sut.select(row.start); await wait { gateway.reads.count == 1 }
        gateway.reads.removeFirst().resume(throwing: AuthFailure.network); await wait { sut.readError }
        sut.refresh(); await wait { gateway.reads.count == 1 }
        gateway.reads.removeFirst().resume(returning: list(rowData)); await wait { sut.loaded }
        precondition(sut.dayRows == [row] && sut.onDay(row.end).count == 1)
        sut.selectMode(.cancel); sut.choose(foreign); precondition(sut.confirmation == nil)
        sut.choose(row); precondition(sut.confirmation == row && gateway.writes.isEmpty)
        sut.dismiss(); precondition(gateway.writes.isEmpty)
        sut.selectMode(.edit); sut.choose(row); await wait { sut.catalogLoaded }
        precondition(sut.draft?.original == row)
        sut.submit(); sut.submit(); await wait { gateway.writes.count == 1 }
        precondition(gateway.requests.last?.0 == "PATCH")
        gateway.writes.removeFirst().resume(throwing: AuthFailure.network); await wait { !sut.busy }
        precondition(sut.pending != nil && !sut.canWrite && sut.sheet == nil)
        sut.leave(); sut.enter(); await wait { gateway.reads.count == 1 }
        precondition(sut.pending != nil)
        gateway.reads.removeFirst().resume(returning: list(rowData)); await wait { sut.loaded }
        precondition(sut.canAcknowledge)
        sut.acknowledge(); precondition(sut.pending == nil && sut.canWrite)
        sut.selectMode(.cancel); sut.choose(row); sut.submit(); sut.submit()
        await wait { gateway.writes.count == 1 }
        precondition(gateway.requests.last?.1 == true && sut.visibleRows.isEmpty)
        sut.dismiss()
        precondition(sut.busy && sut.confirmation == row && sut.sheet == .cancellation)
        gateway.writes.removeFirst().resume(returning: Data("{\"cancelled\":true}".utf8))
        await wait { gateway.reads.count == 1 }
        gateway.reads.removeFirst().resume(returning: Data("[]".utf8)); await wait { sut.loaded }
        precondition(sut.pending == nil && sut.dayRows.isEmpty)
        precondition(sut.reservationCountLabel == "0 הזמנות")
        sut.openCreate(); await wait { sut.catalogLoaded && !sut.catalogLoading }
        sut.updateDraft(BookingDraft(start: row.start, end: row.end)); sut.submit(); sut.submit()
        await wait { gateway.writes.count == 1 }
        gateway.writes.removeFirst().resume(throwing: AuthFailure.rejected(409, "RESERVATION_CONFLICT")); await wait { !sut.busy }
        precondition(sut.pending == nil && sut.notice?.contains("חופפת") == true)
        await wait { gateway.reads.count == 1 }; gateway.reads.removeFirst().resume(returning: Data("[]".utf8)); await wait { sut.loaded }
        sut.submit(); await wait { gateway.writes.count == 1 }
        gateway.writes.removeFirst().resume(returning: Data("malformed success".utf8)); await wait { !sut.busy }
        precondition(sut.pending != nil && !sut.canWrite && !sut.canAcknowledge)
        sut.submit(); precondition(gateway.writes.isEmpty)
        sut.inspectPending(); await wait { gateway.reads.count == 1 }
        gateway.vehiclesIdentity = ChatIdentity(owner: UUID(), user: 3, family: 4, generation: 2, version: 2)
        sut.synchronize(); precondition(sut.pending == nil && sut.visibleRows.isEmpty)
        gateway.reads.removeFirst().resume(returning: list(rowData))
        for _ in 0..<30 { await Task.yield() }
        precondition(sut.visibleRows.isEmpty && !sut.loaded)
        // Confirmed creation, list refresh, filter clipping and empty intersections.
        sut.enter(); await wait { gateway.reads.count == 1 }
        gateway.reads.removeFirst().resume(returning: Data("[]".utf8)); await wait { sut.loaded }
        sut.openCreate(); await wait { sut.catalogLoaded && !sut.catalogLoading }
        sut.updateDraft(BookingDraft(start: row.start, end: row.end)); sut.submit()
        await wait { gateway.writes.count == 1 }
        gateway.writes.removeFirst().resume(returning: rowData)
        await wait { gateway.reads.count == 1 }
        gateway.reads.removeFirst().resume(returning: list(rowData)); await wait { sut.loaded }
        precondition(sut.pending == nil && sut.dayRows == [row] && sut.notice == "ההזמנה נשמרה.")
        precondition(sut.reservationCountLabel == "הזמנה אחת")
        sut.openFilters(); sut.filters = BookingFilters(start: row.start, end: row.end); sut.applyFilters()
        await wait { gateway.reads.count == 1 }
        let longRow = reservation(start: "2026-11-11T00:00:00", end: "2026-11-15T00:00:00")
        gateway.reads.removeFirst().resume(returning: list(longRow)); await wait { sut.loaded }
        let nextDay = try BookingTime.parse("2026-11-11T12:00:00")
        precondition(sut.onDay(nextDay).isEmpty)
        precondition(sut.dayRows.count == 1)
        sut.openFilters(); sut.filters = BookingFilters(start: later, end: later.addingTimeInterval(3600)); sut.applyFilters()
        precondition(sut.loaded && sut.visibleRows.isEmpty && gateway.reads.isEmpty)
        sut.openFilters(); sut.filters = BookingFilters(); sut.applyFilters()
        await wait { gateway.reads.count == 1 }; gateway.reads.removeFirst().resume(returning: list(rowData)); await wait { sut.loaded }
        sut.selectMode(.edit); sut.choose(row); await wait { sut.catalogLoaded && !sut.catalogLoading }
        sut.submit(); await wait { gateway.writes.count == 1 }
        gateway.writes.removeFirst().resume(returning: rowData)
        await wait { gateway.reads.count == 1 }; gateway.reads.removeFirst().resume(returning: list(rowData)); await wait { sut.loaded }
        precondition(sut.pending == nil && sut.sheet == nil)
        sut.selectMode(.cancel); sut.choose(row); sut.submit(); await wait { gateway.writes.count == 1 }
        gateway.writes.removeFirst().resume(throwing: AuthFailure.rejected(403, "FAMILY_ACCESS_DENIED")); await wait { !sut.busy }
        precondition(sut.sheet == nil && sut.confirmation == nil && sut.pending == nil)
        sut.submit(); precondition(gateway.writes.isEmpty)
        await wait { gateway.reads.count == 1 }; gateway.reads.removeFirst().resume(returning: list(rowData)); await wait { sut.loaded }
        sut.openCreate(); await wait { sut.catalogLoaded && !sut.catalogLoading }
        sut.updateDraft(BookingDraft(start: row.start, end: row.end)); sut.submit(); await wait { gateway.writes.count == 1 }
        gateway.vehiclesIdentity = nil; sut.synchronize()
        gateway.writes.removeFirst().resume(returning: rowData)
        for _ in 0..<30 { await Task.yield() }
        precondition(!sut.current && sut.visibleRows.isEmpty && sut.notice == nil && gateway.reads.isEmpty)
        var optionalFilters = BookingFilters(vehicle: vehicle, member: member, start: row.start, end: row.end)
        optionalFilters.start = nil
        precondition(optionalFilters.end == row.end && optionalFilters.vehicle == vehicle && optionalFilters.member == member)
        optionalFilters.end = nil
        precondition(optionalFilters.start == nil && optionalFilters.vehicle == vehicle && optionalFilters.member == member)
        let formGateway = BookingMock()
        let form = BookingModel(gateway: formGateway, now: { now })
        form.synchronize(); form.openCreate()
        precondition(!form.canSubmitDraft)
        await wait { form.catalogLoaded }
        precondition(form.canSubmitDraft && form.draft?.start == defaults.start && form.draft?.end == defaults.end)
        var manual = form.draft!; manual.end = defaults.start
        form.updateDraft(manual)
        precondition(!form.canSubmitDraft && form.draft?.start == defaults.start)
        form.submit(); precondition(formGateway.writes.isEmpty)
        manual.end = defaults.end; form.updateDraft(manual)
        form.loadChoices(); await wait { form.catalogLoaded }
        precondition(form.canSubmitDraft && form.draft == manual)
        manual.start = nil; form.updateDraft(manual)
        precondition(!form.canSubmitDraft)
        form.dismiss(); formGateway.failCatalog = true; form.openCreate()
        await wait { form.catalogError }
        precondition(!form.canSubmitDraft)
        print("PASS: form validity, catalog failure, defaults and preservation of manual values")
        print("PASS: stale reads, errors/retry, edit/cancel selection, explicit confirmation, duplicate writes, uncertainty across navigation, reconciliation, rejection and identity isolation")
    }
}
