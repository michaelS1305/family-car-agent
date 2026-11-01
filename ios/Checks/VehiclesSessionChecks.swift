import Foundation

actor VehiclesSessionBackend: BackendTransport, VehiclesTransport, VehicleDetailsTransport {
    var bodies: [Data?] = []
    var unauthorized = true
    var paused = false
    var continuation: CheckedContinuation<Void, Never>?
    func pause() { paused = true }
    func release() { paused = false; continuation?.resume(); continuation = nil }
    func backend<T: Decodable & Sendable>(_ type: T.Type, path: String, token: String, fields: [String: Field]?) async throws -> T {
        guard path == "/api/me" else { throw AuthFailure.invalidResponse }
        return try JSONDecoder().decode(type, from: Data(#"{"user_id":1,"family_id":2,"name":"Mock"}"#.utf8))
    }
    func vehicles(token: String, operation: VehiclesOperation) async throws -> VehiclesReply {
        bodies.append(try operation.body())
        if unauthorized { unauthorized = false; throw AuthFailure.rejected(401, "") }
        if paused { await withCheckedContinuation { continuation = $0 } }
        return .list([])
    }
    func vehicleDetails(token: String, id: UUID, operation: VehicleDetailsOperation) async throws -> VehicleDetailsReply {
        bodies.append(try operation.body())
        if unauthorized { unauthorized = false; throw AuthFailure.rejected(401, "") }
        if paused { await withCheckedContinuation { continuation = $0 } }
        return .saved
    }
}
@MainActor func runVehiclesSessionChecks() async throws {
    let session = AuthSession(owner: UUID(), accessToken: "synthetic", refreshToken: "synthetic", expires: Date().addingTimeInterval(3600))
    let auth = TestTransport(session)
    let backend = VehiclesSessionBackend()
    let entry = EntryModel(sessions: SessionManager(vault: TestVault(), transport: auth), api: backend, providers: TestProvider())
    AuthCheck.check(entry.vehiclesIdentity == nil, "Vehicles blocked before activation")
    await entry.login(apple: false)
    guard let identity = entry.vehiclesIdentity else { preconditionFailure("missing identity") }
    let draft = VehicleDraft(name: "Synthetic", category: .sedan, manufacturer: VehicleManufacturer(id: 1, name_he: "Test"), manufacturerQuery: "Test", model: "Test", plate: "Test")
    let request = VehicleSubmission(requestID: UUID(), draft: draft)
    _ = try await entry.vehiclesRequest(identity: identity, operation: .create(request))
    let bodies = await backend.bodies
    // JSON object key order is not a payload change.
    let decoded = try bodies.map { try JSONSerialization.jsonObject(with: $0!) as! NSDictionary }
    AuthCheck.check(decoded.count == 2 && decoded[0] == decoded[1], "401 preserves exact creation UUID and fields")
    AuthCheck.check(await auth.calls == 2, "Vehicles uses existing refresh once")
    await backend.pause()
    let late = Task { try await entry.vehiclesRequest(identity: identity, operation: .list) }
    while await backend.continuation == nil { await Task.yield() }
    entry.logout(); await backend.release()
    do { _ = try await late.value; preconditionFailure("late response accepted") }
    catch { AuthCheck.check(error as? AuthFailure == .stale, "Vehicles late response rejected") }
    let before = await backend.bodies.count
    do { _ = try await entry.vehiclesRequest(identity: identity, operation: .create(request)); preconditionFailure("stale POST") }
    catch { AuthCheck.check(error as? AuthFailure == .stale, "Vehicles stale POST rejected") }
    AuthCheck.check(await backend.bodies.count == before, "stale POST never sent")
    let detailAuth = TestTransport(session)
    let detailBackend = VehiclesSessionBackend()
    let detailEntry = EntryModel(sessions: SessionManager(vault: TestVault(), transport: detailAuth), api: detailBackend, providers: TestProvider())
    await detailEntry.login(apple: false)
    let detailIdentity = detailEntry.vehiclesIdentity!
    let id = UUID()
    _ = try await detailEntry.vehicleDetailsRequest(identity: detailIdentity, id: id, operation: .edit(draft))
    let editBodies = try await detailBackend.bodies.map { try JSONSerialization.jsonObject(with: $0!) as! NSDictionary }
    AuthCheck.check(editBodies.count == 2 && editBodies[0] == editBodies[1], "Details explicit 401 retries same edit after refresh")
    AuthCheck.check(await detailAuth.calls == 2, "Details reuses SessionManager refresh")
    await detailBackend.pause()
    let lateDetail = Task { try await detailEntry.vehicleDetailsRequest(identity: detailIdentity, id: id, operation: .retire) }
    while await detailBackend.continuation == nil { await Task.yield() }
    detailEntry.logout(); await detailBackend.release()
    do { _ = try await lateDetail.value; preconditionFailure("late Details response accepted") }
    catch { AuthCheck.check(error as? AuthFailure == .stale, "Details late reply fenced") }
    let detailBefore = await detailBackend.bodies.count
    do { _ = try await detailEntry.vehicleDetailsRequest(identity: detailIdentity, id: id, operation: .retire); preconditionFailure("stale retire") }
    catch { AuthCheck.check(error as? AuthFailure == .stale, "Details stale mutation rejected") }
    AuthCheck.check(await detailBackend.bodies.count == detailBefore, "Details stale mutation never dispatched")
}
