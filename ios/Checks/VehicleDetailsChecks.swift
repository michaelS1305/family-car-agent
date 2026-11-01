import Foundation
#if !canImport(Combine)
protocol ObservableObject: AnyObject {}
@propertyWrapper struct Published<Value> { var wrappedValue: Value; init(wrappedValue: Value) { self.wrappedValue = wrappedValue } }
#endif

@MainActor final class DetailMock: VehicleDetailsGateway {
    var vehiclesIdentity: ChatIdentity? = ChatIdentity(owner: UUID(), user: 1, family: 2, generation: 0, version: 0)
    var detail: VehicleDetail
    var rows: [VehicleMaintenance] = []
    var allowed = true
    var failures: Set<String> = []
    var failure: AuthFailure = .network
    var pause: String?
    var continuation: CheckedContinuation<Void, Never>?
    var calls: [String] = []
    var operations: [VehicleDetailsOperation] = []
    var catalog = [VehicleManufacturer(id: 1, name_he: "בדיקה")]
    init() throws { detail = try VehicleDetailsChecks.detail() }
    func vehiclesRequest(identity: ChatIdentity, operation: VehiclesOperation) async throws -> VehiclesReply {
        switch operation {
        case .permission: if failures.contains("permission") { throw AuthFailure.network }; return .permission(allowed)
        case .manufacturers: return .manufacturers(catalog)
        case .list: return .list([detail.vehicle])
        default: throw AuthFailure.invalidResponse
        }
    }
    func vehicleDetailsRequest(identity: ChatIdentity, id: UUID, operation: VehicleDetailsOperation) async throws -> VehicleDetailsReply {
        let key: String; let reply: VehicleDetailsReply
        switch operation {
        case .detail: key = "detail"; reply = .detail(detail)
        case .maintenance: key = "maintenance"; reply = .maintenance(rows)
        default: key = "write"; operations.append(operation); reply = .saved
        }
        calls.append(key)
        if pause == key { await withCheckedContinuation { continuation = $0 } }
        if failures.contains(key) { throw failure }
        return reply
    }
    func release() { pause = nil; continuation?.resume(); continuation = nil }
}
@main struct VehicleDetailsChecks {
    static let id = UUID(uuidString: "00000000-0000-4000-8000-000000000001")!
    @MainActor static var count = 0
    @MainActor static func check(_ condition: Bool, _ message: String) { precondition(condition, message); count += 1 }
    static func detail(retired: Bool = false, inUse: Bool = false) throws -> VehicleDetail {
        try JSONDecoder().decode(VehicleDetail.self, from: Data("""
        {"vehicle_ref":"\(id)","display_name":"Synthetic","created_at":"2026-01-01T00:00:00Z",
        "retired_at":\(retired ? "\"2026-02-01T00:00:00Z\"" : "null"),"category":"suv",
        "manufacturer_id":1,"manufacturer_name_he":"בדיקה","model":"Model","license_plate":"0000123","in_use":\(inUse)}
        """.utf8))
    }
    static func item(completed: Bool = false) throws -> VehicleMaintenance {
        try JSONDecoder().decode(VehicleMaintenance.self, from: Data("""
        {"maintenance_ref":"\(id)","description":"Synthetic service","scheduled_date":"2028-02-29","created_at":"2026-01-01T00:00:00Z","completed":\(completed)}
        """.utf8))
    }
    @MainActor static func settle() async { for _ in 0..<100 { await Task.yield() }; try? await Task.sleep(for: .milliseconds(10)) }
    @MainActor static func main() async throws {
        check(try detail().status == "פנוי", "free")
        check(try detail(inUse: true).status == "בשימוש", "in use")
        check(try detail(retired: true, inUse: true).status == "לא פעיל", "retired precedence")
        check(try detail().vehicle.plate == "0000123", "leading zeroes")
        check(try detail().vehicle.category?.asset == VehicleCategory.suv.asset, "same illustration")
        let malformedDetails = [
            "{\"vehicle_ref\":\"\(id)\"}",
            "{\"in_use\":null}", "{\"in_use\":\"false\"}"
        ]
        for json in malformedDetails {
            do { _ = try JSONDecoder().decode(VehicleDetail.self, from: Data(json.utf8)); preconditionFailure("missing detail accepted") }
            catch { check(true, "missing detail/status never defaults to available") }
        }
        for bad in ["2026-02-29", "2026-13-01", "2026-1-01", "2026-01-01T00:00:00Z", "2026-00-01"] {
            do { _ = try VehicleDay(bad); preconditionFailure("invalid day") } catch { check(true, "invalid day rejected") }
        }
        let day = try VehicleDay("2028-02-29")
        check(VehicleDay.string(day.date) == day.rawValue && day.label == "29/02/2028", "UTC calendar round trip")
        check(VehicleDay.calendar.timeZone.secondsFromGMT() == 0, "picker calendar uses explicit UTC")
        let edit = MaintenanceEdit(description: "Synthetic", scheduled_date: day)
        let payload = try JSONSerialization.jsonObject(with: VehicleDetailsOperation.add(edit).body()!) as! [String: Any]
        check(payload.count == 2 && payload["scheduled_date"] as? String == "2028-02-29", "date only no request id")
        let operations: [VehicleDetailsOperation] = [.detail, .maintenance, .retire, .add(edit), .update(id, edit), .delete(id), .complete(id)]
        let suffix = ["", "/maintenance", "/retire", "/maintenance", "/maintenance/" + id.uuidString.lowercased(), "/maintenance/" + id.uuidString.lowercased(), "/maintenance/" + id.uuidString.lowercased() + "/complete"]
        for (op, end) in zip(operations, suffix) { check(op.path(id) == "/api/vehicles/" + id.uuidString.lowercased() + end, "exact scoped path") }
        check(operations.map(\.method) == ["GET", "GET", "POST", "POST", "PUT", "DELETE", "POST"], "exact methods")
        let api = try DetailMock(); let model = VehicleDetailsModel(gateway: api, vehicleID: id)
        model.start(); await settle()
        check(model.detail?.vehicle.id == id && model.canManage, "scoped loading permission")
        check(model.maintenance.isEmpty && !model.maintenanceError, "empty maintenance")
        model.open(.retire); check(api.operations.isEmpty, "retire opening is not destructive"); model.close()
        model.open(.edit); await settle()
        check(model.draft.plate == "0000123" && model.draft.manufacturer == api.catalog[0], "edit prefill")
        let draftPayload = try JSONSerialization.jsonObject(with: VehicleDetailsOperation.edit(model.draft).body()!) as! [String: Any]
        check(draftPayload.count == 5 && draftPayload["request_id"] == nil, "edit exact contract")
        var invalid = model.draft; invalid.name = " "; model.edit(invalid); model.submit()
        check(api.operations.isEmpty, "invalid edit blocked")
        invalid.name = "Updated"; model.edit(invalid); model.query("arbitrary"); model.submit()
        check(api.operations.isEmpty, "maker must be selected")
        model.choose(api.catalog[0]); api.pause = "write"; model.submit(); model.submit(); await settle()
        check(api.operations.count == 1 && model.busy, "duplicate write blocked")
        model.close(); check(model.sheet == .edit, "busy sheet retained")
        api.release(); await settle(); check(model.sheet == nil && !model.busy, "edit confirmed then reload")
        model.open(.maintenance); model.submit(); check(api.operations.count == 1, "blank treatment blocked")
        model.editMaintenance("New", day: day); model.submit(); await settle()
        check(api.operations.count == 2 && model.sheet == nil, "add treatment")
        api.rows = [try item()]; model.refreshMaintenance(); await settle(); model.openMaintenance(api.rows[0])
        model.editMaintenance("Changed", day: day); model.submit(); await settle()
        if case .update(let ref, let p) = api.operations.last! { check(ref == id && p.description == "Changed", "update targeted") } else { preconditionFailure() }
        model.openMaintenance(api.rows[0]); model.complete(); await settle()
        if case .complete(let ref) = api.operations.last! { check(ref == id, "complete targeted") } else { preconditionFailure() }
        model.openMaintenance(api.rows[0]); let before = api.operations.count
        model.confirmDelete(); check(api.operations.count == before, "delete requires confirmation")
        model.requestDelete(); check(api.operations.count == before, "delete prompt read only")
        model.confirmDelete(); await settle()
        if case .delete(let ref) = api.operations.last! { check(ref == id, "explicit delete") } else { preconditionFailure() }
        api.rows = [try item(completed: true)]; model.refreshMaintenance(); await settle(); model.openMaintenance(api.rows[0])
        let completedCount = api.operations.count; model.complete(); check(api.operations.count == completedCount, "completed no repeat")
        model.close(); model.open(.retire); model.submit(); await settle()
        if case .retire = api.operations.last! { check(true, "retire explicit") } else { preconditionFailure() }
        api.failures = ["write"]; model.open(.maintenance); model.editMaintenance("Uncertain", day: day); model.submit(); await settle()
        let uncertainCount = api.operations.count
        check(model.requiresReview && model.description == "Uncertain", "uncertain result freezes preserved form")
        model.submit(); await settle(); check(api.operations.count == uncertainCount, "no automatic or immediate retry")
        api.failures.insert("maintenance"); model.reviewServerState(); await settle()
        check(model.requiresReview, "failed reconciliation remains locked")
        api.failures = []; model.reviewServerState(); await settle()
        check(!model.requiresReview && model.sheet == nil, "reconcile forces list review")
        for status in [403, 409] {
            api.failures = ["write"]; api.failure = .rejected(status, "")
            model.open(.retire); model.submit(); await settle()
            check(model.requiresReview && model.detail?.vehicle.retired == false, "failed retirement never optimistic")
            check(model.operationError == (status == 403 ? "אין הרשאה לביצוע הפעולה" : "לא ניתן להוציא את הרכב משימוש כעת. ייתכן שהוא בשימוש."), "safe actionable status error")
            api.failures = []; model.reviewServerState(); await settle()
        }
        api.detail = try detail(retired: true); model.refresh(); await settle(); model.open(.edit); model.open(.connection)
        check(!model.canManage && model.sheet == nil, "retired management and connection blocked")
        api.detail = try detail(); api.allowed = false; model.refresh(); await settle(); model.open(.retire)
        check(!model.canManage && model.sheet == nil, "regular member no mutations")
        model.open(.connection); check(model.sheet == .connection, "regular member future connection information only"); model.close()
        api.allowed = true; api.failures = ["permission"]; model.refresh(); await settle()
        check(!model.canManage && model.loadError, "partial load fails closed")
        api.failures = []; api.pause = "detail"; model.refresh(); await settle()
        api.vehiclesIdentity = ChatIdentity(owner: UUID(), user: 3, family: 4, generation: 1, version: 1)
        api.release(); await settle(); check(!model.current && !model.canManage, "identity late response rejected")
        model.stop(); check(model.detail == nil && model.maintenance.isEmpty && model.draft == VehicleDraft(), "stop clears sensitive state")
        model.start(); await settle(); api.pause = "write"; model.open(.retire); model.submit(); await settle()
        model.stop(); api.release(); await settle(); check(model.detail == nil && !model.busy, "late mutation after logout ignored")
        let wrong = VehicleDetailsModel(gateway: api, vehicleID: UUID()); wrong.start(); await settle()
        check(wrong.loadError && wrong.detail == nil, "wrong vehicle response rejected")
        wrong.stop()
        api.pause = "maintenance"
        let leaving = VehicleDetailsModel(gateway: api, vehicleID: id); leaving.start(); await settle()
        api.vehiclesIdentity = nil; leaving.stop(); api.release(); await settle()
        check(leaving.maintenance.isEmpty && leaving.detail == nil, "late maintenance after logout discarded")
        print("Vehicle Details checks passed: \(count). Synthetic only.")
    }
}
