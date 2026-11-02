import Foundation
#if !canImport(Combine)
protocol ObservableObject: AnyObject {}
@propertyWrapper struct Published<Value> { var wrappedValue: Value; init(wrappedValue: Value) { self.wrappedValue = wrappedValue } }
#endif

@MainActor final class VehiclesMock: VehiclesGateway {
    var vehiclesIdentity: ChatIdentity? = ChatIdentity(owner: UUID(), user: 1, family: 2, generation: 0, version: 0)
    var rows: [ManagedVehicle] = []
    var allowed = true
    var catalog = [VehicleManufacturer(id: 1, name_he: "יצרן בדיקה")]
    var failures = Set<String>()
    var pause: String?
    var continuation: CheckedContinuation<Void, Never>?
    var requests: [VehicleSubmission] = []
    var calls: [String] = []
    var forbidden = false
    func vehiclesRequest(identity: ChatIdentity, operation: VehiclesOperation) async throws -> VehiclesReply {
        let key: String
        let reply: VehiclesReply
        switch operation {
        case .list: key = "list"; reply = .list(rows)
        case .permission: key = "permission"; reply = .permission(allowed)
        case .manufacturers: key = "catalog"; reply = .manufacturers(catalog)
        case .create(let request): key = "create"; requests.append(request); reply = .created(rows[0])
        }
        calls.append(key)
        if pause == key { await withCheckedContinuation { continuation = $0 } }
        if failures.contains(key) { throw forbidden ? AuthFailure.rejected(403, "") : AuthFailure.network }
        return reply
    }
    func release() { pause = nil; continuation?.resume(); continuation = nil }
}
@main struct VehiclesChecks {
    @MainActor static var count = 0
    @MainActor static func check(_ value: Bool, _ label: String) { precondition(value, label); count += 1 }
    @MainActor static func settle() async { for _ in 0..<80 { await Task.yield() }; try? await Task.sleep(for: .milliseconds(5)) }
    static func row(_ n: Int, retired: Bool = false, category: String? = nil) throws -> ManagedVehicle {
        let json = """
        {"vehicle_ref":"00000000-0000-0000-0000-\(String(format: "%012d", n))","display_name":"רכב \(n)",
        "created_at":"2026-10-13T10:00:00.123+00:00","retired_at":\(retired ? "\"2026-10-14T10:00:00Z\"" : "null"),
        "category":\(category.map { "\"\($0)\"" } ?? "null"),"manufacturer_id":null,"manufacturer_name_he":null,"model":null,"license_plate":null}
        """
        return try JSONDecoder().decode(ManagedVehicle.self, from: Data(json.utf8))
    }
    static func draft() -> VehicleDraft {
        VehicleDraft(name: "  רכב !  ", category: .sedan, manufacturer: VehicleManufacturer(id: 1, name_he: "יצרן בדיקה"), manufacturerQuery: "יצרן בדיקה", model: " דגם/自由 ", plate: " AB- 12 ")
    }
    @MainActor static func main() async throws {
        check(VehicleCategory.allCases.map(\.rawValue) == ["hatchback", "sedan", "crossover", "minivan", "suv"], "categories exact")
        let expected = ["vehicles/hatchback/vehicle_hatchback.png", "vehicles/sedan/vehicle_sedan.png", "vehicles/crossover/vehicle_crossover.png", "vehicles/van/modern_silver_minivan.png", "vehicles/suv/suv_silver.png"]
        for (category, asset) in zip(VehicleCategory.allCases, expected) {
            check(VehicleCategory.illustration(category) == asset, "category asset")
            check(try row(1, category: category.rawValue).category == category, "category decode")
        }
        check(try row(1, category: "future").category == nil, "unknown category neutral")
        check(VehicleCategory.illustration(nil) == "icons/archive/single_car_icon.png", "neutral asset")
        check(try row(1, retired: true).retired, "retired timestamp")
        check(draft().valid, "no invented plate regex or normalization")
        for key in [\VehicleDraft.name, \.model, \.plate] {
            var d = draft(); d[keyPath: key] = " \t"; check(!d.valid, "mandatory text")
        }
        var d = draft(); d.category = nil; check(!d.valid, "category mandatory")
        d = draft(); d.manufacturer = nil; check(!d.valid, "manufacturer mandatory")
        d = draft(); d.manufacturerQuery = "arbitrary"; check(!d.valid, "catalog selection exact")
        let submission = VehicleSubmission(requestID: UUID(), draft: draft())
        let body = try JSONSerialization.jsonObject(with: JSONEncoder().encode(submission)) as! [String: Any]
        check(body.count == 6 && body["display_name"] as? String == draft().name && body["license_plate"] as? String == draft().plate, "exact body six fields")
        check(body["manufacturer_id"] as? Int == 1 && body["request_id"] as? String == submission.requestID.uuidString.lowercased(), "numeric manufacturer and UUID")
        let apiClient = try AuthAPI(environment: .development, publicKey: "sb_publishable_synthetic")
        check(apiClient.vehiclesURL(.list).path == "/api/vehicles" && apiClient.vehiclesURL(.list).query == "include_retired=true", "query separate from path")
        check(VehiclesOperation.permission.path == "/api/family" && VehiclesOperation.manufacturers.path == "/api/reference/manufacturers", "GET endpoints")
        check(VehiclesOperation.create(submission).method == "POST", "POST create")
        let api = VehiclesMock(); let model = VehiclesModel(gateway: api)
        model.start(); model.start(); await settle()
        check(api.calls.count == 2 && model.loaded && model.visibleRows.isEmpty && model.mayAdd, "empty admin atomic load once")
        api.allowed = false; model.refresh(); await settle(); model.add()
        check(model.destination == nil && !model.mayAdd, "empty member no add")
        api.allowed = true; api.rows = try [row(3, category: "suv"), row(1, retired: true), row(2)]
        model.refresh(); await settle()
        check(model.active.map(\.id) == [api.rows[0].id, api.rows[2].id] && model.retired.map(\.id) == [api.rows[1].id], "partition preserves server order")
        model.select(api.rows[1].id); check(model.destination == .details(api.rows[1].id), "retired details placeholder exact id")
        model.pop(); await settle(); check(model.destination == nil, "details back list")
        api.failures = ["permission"]; model.refresh(); await settle()
        check(model.loadError && !model.mayAdd && model.rows == api.rows, "permission failure fail closed preserve rows")
        api.failures = ["list"]; model.refresh(); await settle()
        check(model.loadError && !model.mayAdd, "list failure no partial permission")
        api.failures = []; model.refresh(); await settle(); model.add(); model.add(); await settle()
        check(model.destination == .add && model.catalogLoaded && api.calls.filter { $0 == "catalog" }.count == 1, "add catalog once")
        check(model.fieldErrors.isEmpty && model.maySubmit, "empty form enabled without premature errors")
        let callsBeforeValidation = api.calls.count
        model.submit()
        check(model.fieldErrors.count == 5 && model.firstInvalidField == .name, "all errors in visual order")
        check(model.pending == nil && !model.submitting && api.calls.count == callsBeforeValidation, "invalid form no UUID or API")
        var partial = VehicleDraft(); partial.name = "Synthetic"; model.edit(partial)
        check(model.fieldErrors[.name] == nil && model.fieldErrors.count == 4, "repair one retains other errors")
        for key in [\VehicleDraft.name, \.model, \.plate] {
            var invalid = draft(); invalid[keyPath: key] = " \t"; model.edit(invalid); model.submit()
            check(model.fieldErrors.count == 1 && model.pending == nil, "blank required field localized error")
        }
        var noCategory = draft(); noCategory.category = nil; model.edit(noCategory); model.submit()
        check(model.fieldErrors[.category] == "יש לבחור סוג רכב" && model.pending == nil, "category error no request")
        model.edit(draft()); model.queryManufacturer("בדיקה")
        check(model.draft.manufacturer == nil && !model.draft.valid && model.matchingManufacturers.count == 1, "query clears selection")
        model.submit()
        check(model.fieldErrors[.manufacturer] == "יש לבחור יצרן מהרשימה" && api.calls.count == callsBeforeValidation, "typed maker explains selection without API")
        model.chooseManufacturer(VehicleManufacturer(id: 99, name_he: "fake"))
        check(model.draft.manufacturer == nil, "foreign manufacturer blocked")
        model.chooseManufacturer(api.catalog[0]); check(model.draft.valid, "catalog choice")
        check(model.fieldErrors.isEmpty, "choice clears validation immediately")
        model.queryManufacturer(api.catalog[0].name_he)
        check(model.fieldErrors[.manufacturer] != nil, "even identical typed query invalidates explicit selection")
        model.chooseManufacturer(api.catalog[0])
        api.failures = ["create"]; model.submit(); model.submit(); await settle()
        check(api.requests.count == 1 && model.pending != nil && model.submitError != nil, "duplicate taps blocked")
        check(model.fieldErrors.isEmpty && model.submitError != nil, "server error separate from fields")
        let pending = model.pending!
        check(model.maySubmit, "ambiguous network failure allows retry")
        model.edit(VehicleDraft()); model.queryManufacturer("changed")
        check(model.draft == pending.draft && !model.editable, "uncertain submission locks payload")
        model.submit(); await settle()
        check(api.requests.count == 2 && api.requests[0] == api.requests[1], "retry identical UUID and payload")
        api.failures = []; model.submit(); await settle()
        check(api.requests[2] == pending && model.destination == nil && model.pending == nil && model.loaded, "success refreshes list not details")
        model.add(); await settle(); check(model.draft == VehicleDraft(), "new add empty draft")
        check(api.calls.filter { $0 == "catalog" }.count == 1, "catalog reused")
        model.edit(draft()); api.failures = ["create"]; api.forbidden = true; model.submit(); await settle()
        check(model.submitError == "אין הרשאה להוספת רכב", "403 exact message")
        let deniedCount = api.requests.count
        model.edit(VehicleDraft()); model.submit(); model.submit(); await settle()
        check(!model.maySubmit && !model.editable && model.pending == nil && model.draft == draft(), "403 locks current form")
        check(api.requests.count == deniedCount, "403 prevents further POSTs")
        api.allowed = false
        let beforeBack = api.calls.filter { $0 == "list" }.count
        model.pop(); await settle()
        check(api.calls.filter { $0 == "list" }.count == beforeBack + 1 && model.pending == nil, "uncertain back refresh")
        api.failures = []; api.forbidden = false
        model.add()
        check(!model.mayAdd && model.destination == nil, "refreshed denial prevents re-entry")
        api.allowed = true; model.refresh(); await settle()
        model.add(); await settle(); model.edit(draft()); api.pause = "create"; model.submit(); await settle()
        check(api.continuation != nil, "create paused")
        model.pop(); api.release(); await settle()
        check(model.destination == nil && model.pending == nil && !model.submitting, "late create after back ignored")
        check(!model.validationAttempted && model.fieldErrors.isEmpty, "back clears validation")
        model.stop(); api.pause = "list"; model.start(); await settle()
        check(!model.mayAdd && !model.loaded && api.calls.contains("permission"), "parallel permission cannot grant early")
        let old = api.vehiclesIdentity!
        api.vehiclesIdentity = ChatIdentity(owner: old.owner, user: old.user, family: 9, generation: 0, version: 0)
        check(model.visibleRows.isEmpty && !model.mayAdd, "family switch hides data immediately")
        model.stop(); api.release(); await settle()
        check(model.rows.isEmpty && !model.loaded, "late list discarded")
        model.start(); await settle(); api.pause = "catalog"; model.add(); await settle()
        api.vehiclesIdentity = nil; model.stop(); api.release(); await settle()
        check(model.manufacturers.isEmpty && model.pending == nil && model.destination == nil, "logout late catalog discarded")
        api.vehiclesIdentity = old; api.failures = ["catalog"]; model.start(); await settle(); model.add(); await settle()
        check(model.catalogError && !model.catalogLoaded, "catalog error")
        api.failures = []; model.loadManufacturers(); await settle()
        check(model.catalogLoaded && !model.catalogError, "catalog retry")
        model.edit(draft()); api.pause = "create"; model.submit(); await settle()
        let lastRequest = api.requests.last!
        api.vehiclesIdentity = nil
        check(!model.current && !model.editable && model.visibleRows.isEmpty, "logout hides pending form")
        model.stop(); api.release(); await settle()
        check(model.pending == nil && model.rows.isEmpty && !model.submitting, "late create after logout discarded")
        api.vehiclesIdentity = old; model.start(); await settle(); model.add(); await settle(); model.edit(draft())
        api.failures = ["create"]; model.submit(); await settle()
        check(model.pending?.requestID != lastRequest.requestID, "new logical attempt never reuses discarded UUID")
        model.stop()
        let unavailable = VehiclesMock(); unavailable.failures = ["catalog"]
        let offline = VehiclesModel(gateway: unavailable); offline.start(); await settle(); offline.add(); await settle()
        offline.submit()
        check(offline.catalogError && offline.fieldErrors[.manufacturer] == nil, "catalog failure not user validation blame")
        check(offline.pending == nil && unavailable.requests.isEmpty, "catalog failure no creation")
        unavailable.failures = []; offline.loadManufacturers(); await settle()
        check(offline.catalogLoaded && offline.fieldErrors[.manufacturer] == "יש לבחור יצרן", "catalog retry restores actionable selection")
        unavailable.vehiclesIdentity = nil
        offline.submit(); check(!offline.maySubmit && offline.fieldErrors.isEmpty && unavailable.requests.isEmpty, "stale identity blocks and hides errors")
        offline.stop(); check(!offline.validationAttempted, "session stop resets validation")
        print("PASS: \(count) Vehicles checks")
    }
}
