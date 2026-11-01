import Foundation
#if !canImport(Combine)
protocol ObservableObject: AnyObject {}
@propertyWrapper struct Published<Value> { var wrappedValue: Value; init(wrappedValue: Value) { self.wrappedValue = wrappedValue } }
#endif

@MainActor final class HistoryMock: HistoryGateway {
    var vehiclesIdentity: ChatIdentity? = ChatIdentity(owner: UUID(), user: 1, family: 2, generation: 0, version: 0)
    var page: HistoryPage!
    var vehicles: [HistoryVehicle] = []
    var catalog: [ManagedVehicle] = []
    var failures = Set<String>()
    var pause = false
    var continuation: CheckedContinuation<Void, Never>?
    var calls: [(HistoryFilters, UUID?)] = []
    func historyRequest(identity: ChatIdentity, operation: HistoryOperation) async throws -> HistoryReply {
        switch operation {
        case .page(let filters, let cursor):
            calls.append((filters, cursor)); let captured = page!
            if pause { await withCheckedContinuation { continuation = $0 } }
            if failures.contains("page") { throw AuthFailure.invalidResponse }
            return .page(captured)
        case .current:
            if failures.contains("current") { throw AuthFailure.invalidResponse }
            return .current(vehicles)
        case .members:
            if failures.contains("members") { throw AuthFailure.invalidResponse }
            return .members([])
        }
    }
    func vehiclesRequest(identity: ChatIdentity, operation: VehiclesOperation) async throws -> VehiclesReply {
        if failures.contains("images") { throw AuthFailure.invalidResponse }
        return .list(catalog)
    }
    func release() { pause = false; continuation?.resume(); continuation = nil }
}
@main struct HistoryChecks {
    @MainActor static var count = 0
    @MainActor static func check(_ value: Bool, _ label: String) { precondition(value, label); count += 1 }
    static let vehicle = "00000000-0000-4000-8000-000000000001"
    static let member = "00000000-0000-4000-8000-000000000002"
    static let first = "00000000-0000-4000-8000-000000000003"
    static let second = "00000000-0000-4000-8000-000000000004"
    static func usage(_ id: String) -> [String: Any] {
        ["session_ref": id, "vehicle_ref": vehicle, "member_ref": member, "vehicle_name": "Synthetic vehicle", "name": "Synthetic",
         "started_at": "2026-10-31T12:13:00+02:00", "ended_at": "2026-10-31T12:14:00+02:00"]
    }
    static func decode<T: Decodable>(_ type: T.Type, _ value: Any) throws -> T {
        try JSONDecoder().decode(type, from: JSONSerialization.data(withJSONObject: value))
    }
    static func page(_ ids: [String], more: Bool = false) throws -> HistoryPage {
        try decode(HistoryPage.self, ["recent_usage": ids.map(usage), "has_more": more,
                                     "next_cursor": more ? ids.last! as Any : NSNull()])
    }
    @MainActor static func rejects<T: Decodable>(_ type: T.Type, _ value: Any, _ label: String) {
        do { _ = try decode(type, value); preconditionFailure(label) } catch { count += 1 }
    }
    @MainActor static func settle() async { for _ in 0..<100 { await Task.yield() }; try? await Task.sleep(for: .milliseconds(10)) }
    @MainActor static func main() async throws {
        check(try page([]).recent_usage.isEmpty, "empty page")
        let row = try page([first]).recent_usage[0]
        check(row.id == UUID(uuidString: first) && row.vehicle == UUID(uuidString: vehicle), "stable identity")
        check(row.end.timeIntervalSince(row.start) == 60, "offset timestamps")
        var malformed = usage(first)
        for key in ["session_ref", "vehicle_ref", "member_ref", "started_at", "ended_at", "name", "vehicle_name"] {
            var missing = malformed; missing.removeValue(forKey: key); rejects(HistoryUsage.self, missing, "missing mandatory field")
        }
        malformed["started_at"] = NSNull(); rejects(HistoryUsage.self, malformed, "null time")
        malformed = usage(first); malformed["ended_at"] = "not a date"; rejects(HistoryUsage.self, malformed, "invalid time")
        malformed["ended_at"] = "2026-10-31T12:00:00+02:00"; rejects(HistoryUsage.self, malformed, "backwards interval")
        malformed = usage(first); malformed["started_at"] = "2026-10-31T12:13:00"
        rejects(HistoryUsage.self, malformed, "offset required")
        rejects(HistoryPage.self, ["recent_usage": [], "has_more": true, "next_cursor": first], "empty continuation")
        rejects(HistoryPage.self, ["recent_usage": [usage(first)], "has_more": true, "next_cursor": second], "cursor must match final row")
        rejects(HistoryPage.self, ["recent_usage": [], "has_more": false, "next_cursor": first], "terminal cursor")
        rejects(HistoryPage.self, ["recent_usage": [], "has_more": false], "missing cursor")
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        check(HistoryFilters().valid && HistoryFilters().empty, "empty filters")
        check(HistoryFilters(from: now, to: now).valid, "equal range")
        check(!HistoryFilters(from: now, to: now.addingTimeInterval(-1)).valid, "reverse range")
        let filters = HistoryFilters(vehicle: UUID(uuidString: vehicle), member: UUID(uuidString: member), from: now, to: now)
        let query = filters.query(cursor: UUID(uuidString: first))
        check(query.count == 6 && query[0].value == "50", "all query parameters")
        check(try HistoryTime.parse(query.first { $0.name == "from_datetime" }!.value!) == now, "wire offset preserves instant")
        check(abs(try HistoryTime.parse(HistoryTime.wire(now.addingTimeInterval(0.125))).timeIntervalSince(now) - 0.125) < 0.001, "fractional boundary preserved")
        let utc = TimeZone(secondsFromGMT: 0)!
        check(HistoryTime.interval(row.start, row.end, zone: utc) == "10:13–10:14", "24h local display")
        check(HistoryTime.interval(row.start, row.end.addingTimeInterval(86400), zone: utc).contains("\n"), "overnight dates")
        var current: [String: Any] = ["vehicle_ref": vehicle, "display_name": "Synthetic", "retired_at": NSNull(),
                                    "in_use": false, "current_driver": NSNull(), "started_at": NSNull()]
        check(try !decode(HistoryVehicle.self, current).inUse, "available vehicle")
        current["in_use"] = true; rejects(HistoryVehicle.self, current, "used missing driver and time")
        current["current_driver"] = "Synthetic"; current["started_at"] = "2026-10-31T12:13:00+02:00"
        let active = try decode(HistoryVehicle.self, current)
        check(active.inUse && active.start != nil, "active vehicle")
        current["retired_at"] = "2026-10-31T12:13:00Z"; rejects(HistoryVehicle.self, current, "current excludes retired")
        for category in VehicleCategory.allCases {
            check(VehicleCategory.illustration(category) == category.asset, "shared five category mapping")
        }
        check(VehicleCategory.illustration(nil) == "icons/archive/single_car_icon.png", "neutral fallback")
        let api = HistoryMock(); api.page = try page([first], more: true); api.vehicles = [active]
        let model = HistoryModel(gateway: api)
        check(!model.current && model.visibleRows.isEmpty, "no identity no data")
        model.start(); model.start(); await settle()
        check(api.calls.count == 1 && model.loaded && model.rows.count == 1, "one initial page")
        check(model.currentStatus == .ready && model.active.count == 1, "active separate state")
        check(model.illustration(active.id) == VehicleCategory.illustration(nil), "missing catalog safe")
        var historical: [String: Any] = ["vehicle_ref": vehicle, "display_name": "Synthetic", "created_at": "2026-01-01T00:00:00Z",
            "retired_at": "2026-10-31T12:13:00Z", "category": "suv", "manufacturer_id": NSNull(), "manufacturer_name_he": NSNull(), "model": NSNull(), "license_plate": NSNull()]
        api.catalog = [try decode(ManagedVehicle.self, historical)]; model.refresh(); await settle()
        check(model.illustration(active.id) == VehicleCategory.suv.asset, "retired category resolved by stable UUID")
        check(model.illustration(UUID()) == VehicleCategory.illustration(nil), "unrelated UUID neutral")
        historical["category"] = "future-category"
        api.catalog = [try decode(ManagedVehicle.self, historical)]; model.refresh(); await settle()
        check(model.illustration(active.id) == VehicleCategory.illustration(nil), "unknown category neutral")
        api.calls = []
        api.page = try page([first, second]); model.nearEnd(UUID(uuidString: first)!); model.nearEnd(UUID(uuidString: first)!)
        await settle()
        check(api.calls.count == 1 && api.calls.last!.1 == UUID(uuidString: first), "one continuation correct cursor")
        check(model.rows.count == 2 && !model.hasMore, "dedupe overlap end of pagination")
        model.nearEnd(UUID(uuidString: second)!); await settle(); check(api.calls.count == 1, "no terminal request")
        model.openFilters(); model.draft = filters; check(model.applied.empty && api.calls.count == 1, "draft has no network")
        model.dismissFilters(); check(model.draft.empty && model.applied.empty, "dismiss restores draft")
        model.openFilters(); model.draft = HistoryFilters(from: now, to: now.addingTimeInterval(-1)); model.apply()
        check(model.rangeError && model.sheet && api.calls.count == 1, "invalid range blocks")
        model.draft = filters; model.apply(); await settle()
        check(model.applied == filters && !model.sheet && api.calls.last!.1 == nil, "apply restarts cursor")
        model.openFilters(); model.clear(); await settle(); check(model.sheet && model.applied.empty, "clear applies and keeps sheet")
        model.dismissFilters()
        api.failures = ["current", "members", "images"]; model.refresh(); await settle()
        check(model.currentStatus == .unavailable && model.active.isEmpty, "error never all available")
        check(model.membersError && model.loaded, "options failures do not block rows")
        api.failures = []; api.vehicles = []; model.refreshCurrent(); model.refreshMembers(); await settle()
        check(model.currentStatus == .ready && model.active.isEmpty && !model.membersError, "current retry empty ready")
        api.page = try page([first], more: true); model.refresh(); await settle()
        api.failures = ["page"]; model.nearEnd(UUID(uuidString: first)!); await settle()
        check(model.pageError && model.rows.count == 1 && !model.loading, "page error retains rows")
        let calls = api.calls.count; model.nearEnd(UUID(uuidString: first)!); await settle()
        check(api.calls.count == calls, "error no retry loop")
        api.failures = []; api.page = try page([second]); model.retry(); await settle()
        check(model.rows.count == 2 && !model.pageError, "explicit retry appends")
        api.page = try page([first], more: true); model.refresh(); await settle()
        model.nearEnd(UUID(uuidString: first)!); await settle()
        check(model.pageError && model.rows.count == 1, "repeat cursor rejected")
        api.page = try page([second], more: true); model.retry(); await settle()
        api.page = try page([first], more: true); model.nearEnd(UUID(uuidString: second)!); await settle()
        check(model.pageError && model.rows.count == 2, "cyclic cursor rejected")
        api.pause = true; model.refresh(); await settle()
        check(api.continuation != nil, "late request paused")
        model.openFilters(); model.draft = filters; api.pause = false; api.page = try page([]); model.apply(); await settle()
        api.release(); await settle()
        check(model.rows.isEmpty && model.applied == filters && model.loaded, "late prior filter discarded")
        api.pause = true; model.refresh(); await settle(); let identity = api.vehiclesIdentity
        api.vehiclesIdentity = nil
        check(!model.current && model.visibleRows.isEmpty && model.active.isEmpty, "logout immediately hidden")
        model.stop(); api.release(); await settle()
        check(!model.loaded && model.rows.isEmpty && model.illustrations.isEmpty, "late logout discarded and cleared")
        api.vehiclesIdentity = identity; api.page = try page([first]); model.start(); await settle()
        check(model.loaded && model.rows.count == 1 && model.applied.empty, "reentry loads afresh")
        api.pause = true; model.refresh(); await settle()
        api.vehiclesIdentity = ChatIdentity(owner: UUID(), user: 9, family: 10, generation: 1, version: 1)
        model.stop(); api.pause = false; api.page = try page([]); model.start(); await settle(); api.release(); await settle()
        check(model.loaded && model.rows.isEmpty, "family account change fences old response")
        model.stop()
        print("PASS: \(count) History checks")
    }
}
