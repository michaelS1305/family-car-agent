import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

struct VehicleUploadAuthorization: Sendable {
    let context: VehicleQueueContext
    let generation: Int
    let accessToken: String
}

/// Credentials are supplied per attempt and never serialized with an event.
@MainActor protocol VehicleUploadAuthentication: AnyObject {
    func permits(_ context: VehicleQueueContext) -> Bool
    func permitsVehicle(_ vehicle: UUID, in context: VehicleQueueContext) -> Bool
    func authorization(for context: VehicleQueueContext, forceRefresh: Bool) async throws -> VehicleUploadAuthorization
    func isCurrent(_ authorization: VehicleUploadAuthorization) -> Bool
    func rejectAuthorization(for context: VehicleQueueContext)
}

extension VehicleUploadAuthentication {
    func permitsVehicle(_ vehicle: UUID, in context: VehicleQueueContext) -> Bool { permits(context) }
}

@MainActor final class SessionVehicleAuthentication: VehicleUploadAuthentication {
    private let environment: AppEnvironment
    private let sessions: SessionManager
    private let queueDirectory: URL?
    init(environment: AppEnvironment, sessions: SessionManager, queueDirectory: URL? = nil) {
        self.environment = environment; self.sessions = sessions
        self.queueDirectory = queueDirectory
    }
    func scope(_ c: VehicleQueueContext) -> VehicleSessionScope {
        .init(environment: c.environment, user: c.user, family: c.family, device: c.device)
    }
    func permits(_ c: VehicleQueueContext) -> Bool {
        guard let s = sessions.session else { return false }
        return s.activated && s.owner == c.owner && s.vehicleScope == scope(c)
            && c.environment == environment.backendURL.absoluteString + "|" + environment.supabaseURL.absoluteString
    }
    func permitsVehicle(_ vehicle: UUID, in context: VehicleQueueContext) -> Bool {
        permits(context) && sessions.session?.boundVehicles?[vehicle] != nil && durable(context).contains(vehicle)
    }
    func rejectAuthorization(for context: VehicleQueueContext) {
        guard permits(context), let session = sessions.session else { return }
        // The runtime callback fences recording permits and scheduling synchronously.
        sessions.onInvalidation?(session)
        // Existing setter also narrows memory when Keychain persistence fails.
        try? sessions.authorizeVehicleScope(scope(context), owner: session.owner,
                                           generation: sessions.generation, bindings: [:])
    }
    private func durable(_ context: VehicleQueueContext) -> Set<UUID> {
        guard let namespace = sessions.session?.shortcutNamespace else { return [] }
        return (try? VehicleEventQueue.durableVehicles(directory: queueDirectory ?? VehicleEventQueue.applicationDirectory(), context: context, namespace: namespace)) ?? []
    }
    /// Selection IDs expire on logout even if a second account can use the same vehicle.
    func shortcutVehicles(_ c: VehicleQueueContext) -> [String: UUID] {
        guard permits(c), let session = sessions.session, let namespace = session.shortcutNamespace,
              let bindings = session.boundVehicles else { return [:] }
        return Dictionary(uniqueKeysWithValues: bindings.keys.filter { durable(c).contains($0) }.map { (namespace.uuidString + "/" + $0.uuidString, $0) })
    }
    func isCurrent(_ grant: VehicleUploadAuthorization) -> Bool {
        permits(grant.context) && sessions.generation == grant.generation && sessions.session?.accessToken == grant.accessToken
    }
    func authorization(for c: VehicleQueueContext, forceRefresh: Bool) async throws -> VehicleUploadAuthorization {
        guard permits(c) else { throw AuthFailure.stale }
        let version = sessions.generation
        let token = try await sessions.access(owner: c.owner, force: forceRefresh)
        let grant = VehicleUploadAuthorization(context: c, generation: version, accessToken: token)
        guard isCurrent(grant) else { throw AuthFailure.stale }
        return grant
    }
}

struct VehicleUploadTask: Sendable {
    enum State: Sendable { case suspended, running, cancelling, completed }
    let identifier: Int64
    let tag: String?
    let state: State
}

struct VehicleUploadCompletion: Sendable {
    let task: Int64
    let tag: String?
    let status: Int?
    let body: Data
    let retryAfter: String?
    let transportFailed: Bool
}

@MainActor protocol VehicleUploadTransport: AnyObject {
    var identifier: String { get }
    func allTasks() async -> [VehicleUploadTask]
    func create(request: URLRequest, file: URL, tag: String) throws -> VehicleUploadTask
    func resume(_ task: Int64)
    func cancel(_ task: Int64)
}

/// All public operations enter one FIFO, including callbacks. MainActor alone is
/// insufficient because queue/auth/getAllTasks calls suspend and allow reentrancy.
@MainActor final class VehicleSyncCoordinator {
    enum Diagnostic: String { case idle, registered, deferred, authenticationRequired, blocked, identityUnavailable, storageFailure, taskConflict, staleCallback }
    private(set) var diagnostic: Diagnostic = .idle
    private let context: VehicleQueueContext
    private let environment: AppEnvironment
    private let queue: VehicleEventQueue
    private let auth: any VehicleUploadAuthentication
    private let transport: any VehicleUploadTransport
    private let files: VehicleUploadFiles
    private let now: () -> Date
    private var tail: Task<Void, Never>?
    private var stopped = false

    static func sessionIdentifier(environment: AppEnvironment, context: VehicleQueueContext) -> String {
        "\(environment.bundleIdentifier).vehicle-sync.v1.\(context.owner.uuidString).\(context.user).\(context.family).\(context.device.uuidString)"
    }

    init(environment: AppEnvironment, context: VehicleQueueContext, queue: VehicleEventQueue,
         authentication: any VehicleUploadAuthentication, transport: any VehicleUploadTransport,
         directory: URL, now: @escaping () -> Date = Date.init) throws {
        guard context.environment == environment.backendURL.absoluteString + "|" + environment.supabaseURL.absoluteString,
              transport.identifier == Self.sessionIdentifier(environment: environment, context: context) else {
            throw VehicleQueueError.contextUnavailable
        }
        self.context = context; self.environment = environment; self.queue = queue
        auth = authentication; self.transport = transport; self.now = now
        files = try VehicleUploadFiles(directory: directory.appendingPathComponent(transport.identifier, isDirectory: true))
    }

    /// Foreground, future BGProcessing and explicit recovery hooks use this method.
    func wake() async {
        await serial { try await self.schedule() }
    }

    func receive(_ completion: VehicleUploadCompletion) async {
        await serial { try await self.consume(completion) }
    }

    /// Immediate scheduling fence; cancellation is not a server-side revocation.
    func fence() { stopped = true }

    func suspend() async {
        stopped = true
        await serial {
            try await self.queue.suspend(self.context)
            for task in await self.transport.allTasks() { self.transport.cancel(task.identifier) }
        }
    }

    private func serial(_ operation: @escaping @MainActor () async throws -> Void) async {
        let previous = tail
        let task = Task { @MainActor in
            await previous?.value
            do { try await operation() }
            catch VehicleQueueError.contextUnavailable {
                self.diagnostic = .identityUnavailable
                for task in await self.transport.allTasks() { self.transport.cancel(task.identifier) }
            }
            catch {
                self.diagnostic = .storageFailure
                for task in await self.transport.allTasks() { self.transport.cancel(task.identifier) }
            }
        }
        tail = task
        await task.value
    }

    private func allowed() async throws {
        guard !stopped, auth.permits(context) else { throw VehicleQueueError.contextUnavailable }
        try await queue.validateActiveContext(context)
        guard !stopped, auth.permits(context) else { throw VehicleQueueError.contextUnavailable }
    }

    private func schedule() async throws {
        try await allowed()
        let tasks = await transport.allTasks()
        try await allowed()
        let rows = try await queue.records(context)
        guard let head = rows.first(where: { $0.state != .accepted && $0.state != .terminal }) else {
            for task in tasks { transport.cancel(task.identifier) }
            diagnostic = .idle; return
        }
        guard auth.permitsVehicle(head.event.vehicle, in: context),
              try await queue.authorizedVehicles(context).contains(head.event.vehicle) else {
            for task in tasks { transport.cancel(task.identifier) }
            diagnostic = .blocked; return // Preserve the head and sequence; never skip an unbound vehicle.
        }
        // Never register a replacement while any task still exists in this session.
        if !tasks.isEmpty {
            guard tasks.count == 1, let task = tasks.first, let attempt = head.attempt,
                  task.tag == Self.tag(head.event.id, attempt),
                  [.preparing, .registered].contains(head.state),
                  head.state != .registered || (head.sessionIdentifier == transport.identifier && head.taskIdentifier == task.identifier)
            else {
                for task in tasks { transport.cancel(task.identifier) }
                diagnostic = .taskConflict; return
            }
            if task.state == .cancelling || task.state == .completed { diagnostic = .deferred; return }
            // Covers termination after create/taskDescription but before mapping commit.
            if head.state == .preparing {
                try await queue.markRegistered(context, event: head.event.id, attempt: attempt,
                                               sessionIdentifier: transport.identifier, taskIdentifier: task.identifier)
            }
            try await allowed()
            guard auth.permitsVehicle(head.event.vehicle, in: context),
              try await queue.authorizedVehicles(context).contains(head.event.vehicle) else {
                transport.cancel(task.identifier); diagnostic = .blocked; return
            }
            if task.state == .suspended { transport.resume(task.identifier) }
            diagnostic = .registered; return
        }
        if try files.notBefore(head.event.id).map({ $0 > now() }) == true { diagnostic = .deferred; return }
        let needsRefresh = head.state == .awaitingAuthentication
        if needsRefresh, try files.refreshExhausted(head.event.id) { diagnostic = .authenticationRequired; return }
        if head.state == .blocked && head.reason != VehicleEventQueue.Failure.deliveryUnknown.rawValue {
            diagnostic = .blocked; return
        }
        // Obtain credentials before claiming a new pending head, avoiding a stranded
        // preparing record when the provider cannot refresh while locked/offline.
        let grant: VehicleUploadAuthorization
        do { grant = try await auth.authorization(for: context, forceRefresh: needsRefresh) }
        catch { try files.deferUntil(head.event.id, date: now().addingTimeInterval(60)); diagnostic = .authenticationRequired; return }
        try await allowed()
        guard grant.context == context, auth.isCurrent(grant), !grant.accessToken.isEmpty,
              !grant.accessToken.contains("\r"), !grant.accessToken.contains("\n") else {
            diagnostic = .identityUnavailable; return
        }
        // Recheck after the asynchronous auth operation before inferring no task.
        guard await transport.allTasks().isEmpty else { diagnostic = .deferred; return }
        if needsRefresh { try files.reserveRefresh(head.event.id) }
        if head.state != .pending {
            guard let attempt = head.attempt else { throw VehicleQueueError.invalidTransition }
            try await queue.retryAfterTaskReconciliation(context, event: head.event.id, attempt: attempt)
        }
        guard let claim = try await queue.prepareNext(context), let attempt = claim.attempt else {
            diagnostic = .blocked; return
        }
        let file = try files.payload(claim.event)
        let route = claim.event.kind == .take ? "take" : "return"
        let url = environment.backendURL.appendingPathComponent("api/devices/\(context.device.uuidString)/events/\(route)")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer " + grant.accessToken, forHTTPHeaderField: "Authorization")
        try await allowed()
        guard auth.isCurrent(grant), auth.permitsVehicle(claim.event.vehicle, in: context) else { diagnostic = .identityUnavailable; return }
        let task = try transport.create(request: request, file: file, tag: Self.tag(claim.event.id, attempt))
        do {
            try await queue.markRegistered(context, event: claim.event.id, attempt: attempt,
                                           sessionIdentifier: transport.identifier, taskIdentifier: task.identifier)
            try await allowed()
            guard auth.isCurrent(grant), auth.permitsVehicle(claim.event.vehicle, in: context) else { transport.cancel(task.identifier); diagnostic = .identityUnavailable; return }
            transport.resume(task.identifier)
            diagnostic = .registered
        } catch {
            transport.cancel(task.identifier)
            throw error
        }
    }

    private func consume(_ result: VehicleUploadCompletion) async throws {
        try await allowed()
        let rows = try await queue.records(context)
        guard let row = rows.first(where: {
            guard let attempt = $0.attempt else { return false }
            return $0.state == .registered && $0.taskIdentifier == result.task
                && $0.sessionIdentifier == transport.identifier && result.tag == Self.tag($0.event.id, attempt)
        }), let attempt = row.attempt else { diagnostic = .staleCallback; return }
        if result.transportFailed || result.status == nil {
            try await deferRetry(row, after: nil); return
        }
        guard let status = result.status else { return }
        if Self.isAuthorizationRejection(status: status, body: result.body) {
            stopped = true
            auth.rejectAuthorization(for: context)
            for task in await transport.allTasks() { transport.cancel(task.identifier) }
            try await queue.rejectAuthorization(context, event: row.event.id, attempt: attempt)
            diagnostic = .blocked
            return
        }
        if status == 401 {
            try await queue.recordFailure(context, event: row.event.id, attempt: attempt, failure: .authentication)
            try await schedule(); return
        }
        if status == 429 || (500...599).contains(status) {
            try await deferRetry(row, after: result.retryAfter); return
        }
        if (200...299).contains(status) {
            do {
                guard !result.body.isEmpty, result.body.count <= 65_536 else { throw VehicleQueueError.invalidInput }
                let receipt = try JSONDecoder().decode(VehicleAdmissionReceipt.self, from: result.body)
                try await queue.applyAdmission(context, event: row.event.id, attempt: attempt, receipt: receipt)
            } catch VehicleQueueError.invalidInput {
                try await deferRetry(row, after: nil); return
            } catch is DecodingError {
                try await deferRetry(row, after: nil); return
            }
            let updated = try await queue.records(context).first(where: { $0.event.id == row.event.id })
            if updated?.state == .accepted || updated?.state == .terminal {
                // Failed cleanup is safe: acknowledgement is already durable.
                try? files.removeResolved(row.event.id)
                try await schedule()
            } else { diagnostic = .blocked }
            return
        }
        try await queue.recordFailure(context, event: row.event.id, attempt: attempt, failure: .preAdmissionRejection)
        diagnostic = .blocked
    }

    /// FastAPI's documented envelope; neither HTTP status nor arbitrary text is evidence.
    static func isAuthorizationRejection(status: Int, body: Data) -> Bool {
        struct Envelope: Decodable {
            struct Detail: Decodable { let code: String }
            let detail: Detail
        }
        guard body.count <= 65_536, let response = try? JSONDecoder().decode(Envelope.self, from: body) else { return false }
        return (status == 404 && response.detail.code == "DEVICE_OR_VEHICLE_UNAVAILABLE")
            || (status == 403 && response.detail.code == "IDENTITY_UNAVAILABLE")
    }

    private func deferRetry(_ row: VehicleQueueRecord, after: String?) async throws {
        guard let attempt = row.attempt else { throw VehicleQueueError.invalidTransition }
        // Persist the cooldown before changing queue state; process death cannot
        // turn a Retry-After response into an immediate retry loop.
        try files.deferUntil(row.event.id, date: Self.retryDate(after, now: now()))
        try await queue.recordFailure(context, event: row.event.id, attempt: attempt, failure: .deliveryUnknown)
        diagnostic = .deferred
    }

    static func retryDate(_ value: String?, now: Date) -> Date {
        let baseline = now.addingTimeInterval(60)
        guard let value else { return baseline }
        if let seconds = Double(value), seconds.isFinite, seconds >= 0 {
            let date = now.addingTimeInterval(seconds)
            return date.timeIntervalSince1970.isFinite ? max(baseline, date) : .distantFuture
        }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX"); formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "EEE',' dd MMM yyyy HH':'mm':'ss zzz"
        return formatter.date(from: value).map { max(baseline, $0) } ?? baseline
    }

    private static func tag(_ event: UUID, _ attempt: UUID) -> String { event.uuidString + "/" + attempt.uuidString }
}

/// Files contain immutable event bodies and cooldown dates only, never headers.
private struct VehicleUploadFiles {
    let directory: URL
    init(directory: URL) throws {
        guard directory.isFileURL else { throw VehicleQueueError.invalidInput }
        self.directory = directory
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        #if os(iOS)
        try FileManager.default.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication], ofItemAtPath: directory.path)
        var url = directory; var values = URLResourceValues(); values.isExcludedFromBackup = true
        try url.setResourceValues(values)
        #endif
    }
    func payload(_ event: QueuedVehicleEvent) throws -> URL {
        let url = directory.appendingPathComponent(event.id.uuidString + ".json")
        // Existing bytes are authoritative for retry, including across app upgrades.
        if FileManager.default.fileExists(atPath: url.path) {
            let data = try Data(contentsOf: url)
            guard data == (try Self.encode(event)) else { throw VehicleQueueError.conflict }
        } else { try write(Self.encode(event), to: url) }
        return url
    }
    private func write(_ data: Data, to url: URL) throws {
        try data.write(to: url, options: .atomic)
        #if os(iOS)
        try FileManager.default.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication], ofItemAtPath: url.path)
        #endif
    }
    private func retryFile(_ id: UUID) -> URL { directory.appendingPathComponent(id.uuidString + ".retry") }
    func deferUntil(_ id: UUID, date: Date) throws { try write(JSONEncoder().encode(date), to: retryFile(id)) }
    func notBefore(_ id: UUID) throws -> Date? {
        guard FileManager.default.fileExists(atPath: retryFile(id).path) else { return nil }
        return try JSONDecoder().decode(Date.self, from: Data(contentsOf: retryFile(id)))
    }
    private func authFile(_ id: UUID) -> URL { directory.appendingPathComponent(id.uuidString + ".auth-retry") }
    func refreshExhausted(_ id: UUID) throws -> Bool {
        guard FileManager.default.fileExists(atPath: authFile(id).path) else { return false }
        guard try Data(contentsOf: authFile(id)) == Data([1]) else { throw VehicleQueueError.storage }
        return true
    }
    func reserveRefresh(_ id: UUID) throws { try write(Data([1]), to: authFile(id)) }
    func removeResolved(_ id: UUID) throws {
        for file in [directory.appendingPathComponent(id.uuidString + ".json"), retryFile(id), authFile(id)] {
            if FileManager.default.fileExists(atPath: file.path) { try FileManager.default.removeItem(at: file) }
        }
    }
    static func encode(_ event: QueuedVehicleEvent) throws -> Data {
        var body: [String: Any] = ["event_id": event.id.uuidString, "vehicle_ref": event.vehicle.uuidString,
                                   "device_sequence": event.sequence, "occurred_at": timestamp(event.occurredAt)]
        if event.kind == .returning {
            guard let cause = event.takeID, let location = event.location else { throw VehicleQueueError.invalidInput }
            body["take_event_id"] = cause.uuidString; body["latitude"] = location.latitude
            body["longitude"] = location.longitude; body["accuracy_m"] = location.accuracy
            body["location_at"] = timestamp(location.measuredAt)
        }
        return try JSONSerialization.data(withJSONObject: body, options: [.sortedKeys])
    }
    private static func timestamp(_ date: Date) -> String {
        let value = date.timeIntervalSince1970, seconds = floor(value)
        let formatter = ISO8601DateFormatter()
        let base = formatter.string(from: Date(timeIntervalSince1970: seconds)).dropLast()
        return String(base) + String(format: ".%09dZ", Int((value - seconds) * 1_000_000_000))
    }
}
