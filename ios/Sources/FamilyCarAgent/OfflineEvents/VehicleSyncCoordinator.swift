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

@MainActor protocol TakeMetadataTransport: AnyObject {
    func fetch(_ request: TakeMetadataRequest, device: UUID, token: String) async throws -> TakeMetadataSnapshot
}

@MainActor final class HTTPMetadataTransport: TakeMetadataTransport {
    private let environment: AppEnvironment
    private let session: URLSession
    init(environment: AppEnvironment) {
        self.environment=environment
        let config=URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest=15
        config.timeoutIntervalForResource=20
        session=URLSession(configuration:config)
    }
    func fetch(_ body: TakeMetadataRequest, device: UUID, token: String) async throws -> TakeMetadataSnapshot {
        var request=URLRequest(url:environment.backendURL.appendingPathComponent("api/devices/\(device.uuidString)/take-session-metadata"))
        request.httpMethod="POST"
        request.setValue("Bearer " + token,forHTTPHeaderField:"Authorization")
        request.setValue("application/json",forHTTPHeaderField:"Content-Type")
        request.httpBody=try JSONEncoder().encode(body)
        let (data,response)=try await session.data(for:request)
        guard (response as? HTTPURLResponse)?.statusCode == 200, data.count <= 131_072 else { throw VehicleQueueError.invalidInput }
        return try JSONDecoder().decode(TakeMetadataSnapshot.self,from:data)
    }
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
    private let retryWait: @MainActor (TimeInterval) async throws -> Void
    private var retryTask: Task<Void, Never>?
    private var tail: Task<Void, Never>?
    private var stopped = false
    private let metadataTransport: (any TakeMetadataTransport)?
    private var metadataTask: Task<Void,Never>?
    private var metadataAgain=false


    static func sessionIdentifier(environment: AppEnvironment, context: VehicleQueueContext) -> String {
        "\(environment.bundleIdentifier).vehicle-sync.v1.\(context.owner.uuidString).\(context.user).\(context.family).\(context.device.uuidString)"
    }

    init(environment: AppEnvironment, context: VehicleQueueContext, queue: VehicleEventQueue,
         authentication: any VehicleUploadAuthentication, transport: any VehicleUploadTransport,
         directory: URL, metadataTransport: (any TakeMetadataTransport)? = nil, now: @escaping () -> Date = Date.init,
         retryWait: @escaping @MainActor (TimeInterval) async throws -> Void = { seconds in
             try await Task.sleep(for: .seconds(min(seconds, 86_400)))
         }) throws {
        guard context.environment == environment.backendURL.absoluteString + "|" + environment.supabaseURL.absoluteString,
              transport.identifier == Self.sessionIdentifier(environment: environment, context: context) else {
            throw VehicleQueueError.contextUnavailable
        }
        self.metadataTransport=metadataTransport
        self.context = context; self.environment = environment; self.queue = queue
        auth = authentication; self.transport = transport; self.now = now
        self.retryWait = retryWait
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
    func fence() { stopped = true; metadataTask?.cancel(); metadataTask=nil; retryTask?.cancel(); retryTask = nil }

    func suspend() async {
        fence()
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

    // Fire-and-forget: neither queue admission nor wake waits for metadata/network.
    private func requestMetadataRefresh() {
        guard !stopped, let metadataTransport else { return }
        if metadataTask != nil { metadataAgain=true; return }
        metadataTask=Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                var visited = Set<UUID>()
                for _ in 0..<4 { // At most 256 distinct references per pass; no network in eligibility.
                    guard let batch=try await queue.metadataBatch(context, excluding:visited) else { break }
                    visited.formUnion(batch.request.takes.map(\.event_id))
                    let grant=try await auth.authorization(for:context,forceRefresh:false)
                    guard !stopped, auth.isCurrent(grant), grant.context == context,
                          batch.request.takes.allSatisfy({ auth.permitsVehicle($0.vehicle_ref,in:context) }) else { throw VehicleQueueError.contextUnavailable }
                    let snapshot=try await metadataTransport.fetch(batch.request,device:context.device,token:grant.accessToken)
                    try Task.checkCancellation()
                    guard !stopped, auth.isCurrent(grant), auth.permits(context) else { throw VehicleQueueError.contextUnavailable }
                    try await queue.applyMetadata(context,batch:batch,snapshot:snapshot)
                }
            } catch {
                // Keep evidence and verified cache. Next lifecycle/connectivity wake retries.
            }
            metadataTask=nil
            if metadataAgain && !stopped { metadataAgain=false; requestMetadataRefresh() }
        }
    }

    private func schedule() async throws {
        retryTask?.cancel(); retryTask = nil
        try await allowed()
        requestMetadataRefresh()
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
        if head.state == .blocked, let recovery = try await queue.recovery(context, event: head.event.id) {
            try await scheduleRecovery(head, recovery: recovery, tasks: tasks)
            return
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
        if let deadline = try files.notBefore(head.event.id), deadline > now() {
            diagnostic = .deferred; retry(at: deadline); return
        }
        let needsRefresh = head.state == .awaitingAuthentication
        if needsRefresh, try files.refreshExhausted(head.event.id) { diagnostic = .authenticationRequired; return }
        if head.state == .blocked && head.reason != VehicleEventQueue.Failure.deliveryUnknown.rawValue {
            diagnostic = .blocked; return
        }
        // Obtain credentials before claiming a new pending head, avoiding a stranded
        // preparing record when the provider cannot refresh while locked/offline.
        let grant: VehicleUploadAuthorization
        do { grant = try await auth.authorization(for: context, forceRefresh: needsRefresh) }
        catch {
            let deadline = now().addingTimeInterval(60)
            try files.deferUntil(head.event.id, date: deadline)
            diagnostic = .authenticationRequired; retry(at: deadline); return
        }
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
        if let head = rows.first(where: { $0.state != .accepted && $0.state != .terminal }),
           let recovery = try await queue.recovery(context, event: head.event.id),
           recovery.state == .registered, recovery.task == result.task,
           recovery.session == transport.identifier, result.tag == Self.recoveryTag(recovery) {
            try await consumeRecovery(result, head: head, recovery: recovery)
            return
        }
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
        try await queue.recordFailure(context, event: row.event.id, attempt: attempt, failure: .preAdmissionRejection,
                                      rejectionCode: status == 409 ? Self.errorCode(result.body) : nil)
        diagnostic = .blocked
    }

    private static func recoveryTag(_ r: VehicleRecoveryRecord) -> String { (r.reconciliation ? "reconciliation/" : "recovery/") + r.event.uuidString + "/" + r.id.uuidString }

    static func errorCode(_ body: Data) -> String? {
        struct Envelope: Decodable {
            struct Detail: Decodable { let code: String }
            let detail: Detail
        }
        guard body.count <= 65_536 else { return nil }
        return (try? JSONDecoder().decode(Envelope.self, from: body))?.detail.code
    }

    private func scheduleRecovery(_ head: VehicleQueueRecord, recovery r: VehicleRecoveryRecord,
                                  tasks: [VehicleUploadTask]) async throws {
        guard r.state != .blocked else { diagnostic = .blocked; return }
        if !tasks.isEmpty {
            guard tasks.count == 1, let task = tasks.first, task.tag == Self.recoveryTag(r),
                  [.preparing, .registered].contains(r.state),
                  r.state != .registered || (r.session == transport.identifier && r.task == task.identifier)
            else {
                for task in tasks { transport.cancel(task.identifier) }
                diagnostic = .taskConflict; return // Cancellation is not completion; wait for reconciliation.
            }
            if task.state == .cancelling || task.state == .completed { diagnostic = .deferred; return }
            if r.state == .preparing {
                try await queue.updateRecovery(context, event: r.event, id: r.id, state: .registered,
                                               session: transport.identifier, task: task.identifier)
            }
            try await allowed()
            guard auth.permitsVehicle(head.event.vehicle, in: context) else { transport.cancel(task.identifier); return }
            if task.state == .suspended { transport.resume(task.identifier) }
            diagnostic = .registered; return
        }
        if let deadline = try files.notBefore(r.id), deadline > now() {
            diagnostic = .deferred; retry(at: deadline); return
        }
        let refresh = r.state == .awaitingAuthentication
        if refresh, try files.refreshExhausted(r.id) { diagnostic = .authenticationRequired; return }
        let grant: VehicleUploadAuthorization
        do { grant = try await auth.authorization(for: context, forceRefresh: refresh) }
        catch {
            let deadline = now().addingTimeInterval(60)
            try files.deferUntil(r.id, date: deadline)
            diagnostic = .authenticationRequired; retry(at: deadline); return
        }
        try await allowed()
        guard grant.context == context, auth.isCurrent(grant), auth.permitsVehicle(head.event.vehicle, in: context),
              !grant.accessToken.isEmpty, !grant.accessToken.contains("\r"), !grant.accessToken.contains("\n") else {
            diagnostic = .identityUnavailable; return
        }
        guard await transport.allTasks().isEmpty else { diagnostic = .deferred; return }
        if refresh { try files.reserveRefresh(r.id) }
        try await queue.updateRecovery(context, event: r.event, id: r.id, state: .preparing)
        let file = try files.recoveryPayload(r)
        var request = URLRequest(url: environment.backendURL.appendingPathComponent(
            "api/devices/\(context.device.uuidString)/events/return/\(r.event.uuidString)/\(r.reconciliation ? "reconciliation" : "recovery")"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer " + grant.accessToken, forHTTPHeaderField: "Authorization")
        try await allowed()
        guard auth.isCurrent(grant), auth.permitsVehicle(head.event.vehicle, in: context) else { diagnostic = .identityUnavailable; return }
        let task = try transport.create(request: request, file: file, tag: Self.recoveryTag(r))
        do {
            try await queue.updateRecovery(context, event: r.event, id: r.id, state: .registered,
                                           session: transport.identifier, task: task.identifier)
            try await allowed()
            guard auth.isCurrent(grant), auth.permitsVehicle(head.event.vehicle, in: context) else {
                transport.cancel(task.identifier); diagnostic = .identityUnavailable; return
            }
            transport.resume(task.identifier); diagnostic = .registered
        } catch { transport.cancel(task.identifier); throw error }
    }

    private func consumeRecovery(_ result: VehicleUploadCompletion, head: VehicleQueueRecord,
                                 recovery r: VehicleRecoveryRecord) async throws {
        let status = result.status ?? 0
        if result.transportFailed || result.status == nil || status == 429 || (500...599).contains(status) {
            try await deferRecovery(r, after: result.retryAfter); return
        }
        if status == 401 {
            try await queue.updateRecovery(context, event: r.event, id: r.id, state: .awaitingAuthentication)
            try await schedule(); return
        }
        if Self.isAuthorizationRejection(status: status, body: result.body) {
            try await queue.updateRecovery(context, event: r.event, id: r.id, state: .blocked, reason: "authorizationRejected")
            stopped = true; auth.rejectAuthorization(for: context)
            for task in await transport.allTasks() { transport.cancel(task.identifier) }
            diagnostic = .blocked; return
        }
        if (200...299).contains(status), r.reconciliation {
            struct Resolution: Decodable {
                let kind: String
                let event_id: UUID
                let reconciliation_id: UUID
                let operation_id: UUID
                let device_sequence: Int64
                let last_processed_sequence: Int64
                let historical_receipt: VehicleAdmissionReceipt
                let effective_at: String
                let session_effect: String
            }
            guard result.body.count <= 65_536,
                  let receipt = try? JSONDecoder().decode(Resolution.self, from: result.body),
                  receipt.kind == "resolved_current_state", receipt.event_id == r.event,
                  receipt.device_sequence == head.event.sequence,
                  receipt.last_processed_sequence == head.event.sequence,
                  receipt.historical_receipt.kind == "terminal",
                  receipt.historical_receipt.admission_outcome == "before_finalized_boundary",
                  receipt.session_effect == "closed_linked_session", !receipt.effective_at.isEmpty else {
                try await deferRecovery(r, after: nil); return
            }
            try await queue.updateRecovery(context, event: r.event, id: r.id, state: .accepted, acknowledgment: String(decoding: result.body, as: UTF8.self))
            try? files.removeResolved(r.id)
            try? files.removeResolved(head.event.id)
            try await schedule(); return
        }
        if (200...299).contains(status) {
            struct Receipt: Decodable {
                let kind: String
                let admission_outcome: String
                let recovery_outcome: String
                let event_id: UUID
                let recovery_id: UUID
                let verified_at: String
            }
            guard result.body.count <= 65_536,
                  let receipt = try? JSONDecoder().decode(Receipt.self, from: result.body),
                  receipt.kind == "accepted", receipt.admission_outcome == "accepted",
                  receipt.recovery_outcome == "recovered", receipt.event_id == r.event,
                  receipt.recovery_id == r.id, !receipt.verified_at.isEmpty else {
                try await deferRecovery(r, after: nil); return
            }
            try await queue.updateRecovery(context, event: r.event, id: r.id, state: .accepted)
            try? files.removeResolved(r.id)
            try? files.removeResolved(head.event.id)
            try await schedule(); return
        }
        // Only known safe fresh-evidence refusals permit a NEW explicit attempt.
        let reconciliationCodes: Set<String> = ["RETURN_RECONCILIATION_NOT_FINALIZED", "RETURN_RECONCILIATION_NOT_ELIGIBLE",
            "RETURN_RECONCILIATION_SEQUENCE_CONFLICT", "RETURN_RECONCILIATION_EVIDENCE_MISMATCH",
            "RETURN_RECONCILIATION_IDEMPOTENCY_CONFLICT", "RETURN_RECONCILIATION_VERIFICATION_EXPIRED",
            "RETURN_RECONCILIATION_STATE_CHANGED", "RETURN_RECONCILIATION_INVALID_CHRONOLOGY"]
        let known = ReturnRecoveryPolicy.renewable.union(r.reconciliation ? reconciliationCodes : []).union([
            "RETURN_RECOVERY_LEGACY_UNVERIFIED", "RETURN_RECOVERY_ORDER_CONFLICT",
            "RETURN_RECOVERY_NOT_ELIGIBLE", "RETURN_RECOVERY_EVIDENCE_MISMATCH", "RETURN_RECOVERY_IDEMPOTENCY_CONFLICT"])
        let code = status == 409 ? Self.errorCode(result.body) : nil
        try await queue.updateRecovery(context, event: r.event, id: r.id, state: .blocked,
            reason: code.flatMap { known.contains($0) ? $0 : nil } ?? "unrecognizedRecoveryRejection")
        diagnostic = .blocked
    }

    private func deferRecovery(_ r: VehicleRecoveryRecord, after: String?) async throws {
        let deadline = Self.retryDate(after, now: now())
        try files.deferUntil(r.id, date: deadline)
        try await queue.updateRecovery(context, event: r.event, id: r.id, state: .preparing, reason: "deliveryUnknown")
        diagnostic = .deferred; retry(at: deadline)
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
        let deadline = Self.retryDate(after, now: now())
        try files.deferUntil(row.event.id, date: deadline)
        try await queue.recordFailure(context, event: row.event.id, attempt: attempt, failure: .deliveryUnknown)
        diagnostic = .deferred
        retry(at: deadline)
    }

    /// Best effort while this process can run. Durable cooldowns remain authoritative
    /// after suspension/relaunch; this is not an iOS background execution guarantee.
    private func retry(at deadline: Date) {
        retryTask?.cancel()
        guard !stopped else { return }
        let delay = max(1, deadline.timeIntervalSince(now()))
        let wait = retryWait
        retryTask = Task { @MainActor [weak self] in
            do { try await wait(delay); try Task.checkCancellation() }
            catch { return }
            guard let self, !self.stopped else { return }
            self.retryTask = nil
            await self.wake()
        }
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
    func recoveryPayload(_ recovery: VehicleRecoveryRecord) throws -> URL {
        let url = directory.appendingPathComponent(recovery.id.uuidString + ".json")
        if FileManager.default.fileExists(atPath: url.path) {
            guard try Data(contentsOf: url) == recovery.payload else { throw VehicleQueueError.conflict }
        } else {
            // Write a complete protected staging file, then publish it with an
            // exclusive same-volume link. A crash cannot expose a partial body;
            // another process cannot overwrite an existing upload's bytes.
            let staging = directory.appendingPathComponent(UUID().uuidString + ".recovery-staging")
            defer { try? FileManager.default.removeItem(at: staging) }
            try write(recovery.payload, to: staging)
            do { try FileManager.default.linkItem(at: staging, to: url) }
            catch {
                guard try Data(contentsOf: url) == recovery.payload else { throw VehicleQueueError.storage }
            }
        }
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
        try VehicleEventWire.encode(event)
    }
}
