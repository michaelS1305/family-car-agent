import Foundation
import SQLite3
#if os(Linux)
import Glibc
#else
import Darwin
#endif

private func sql(_ directory: URL, _ statement: String) throws {
    var db: OpaquePointer?
    guard sqlite3_open(directory.appendingPathComponent("vehicle-events.sqlite").path, &db) == SQLITE_OK else {
        throw VehicleQueueError.storage
    }
    defer { sqlite3_close_v2(db) }
    guard sqlite3_exec(db, statement, nil, nil, nil) == SQLITE_OK else { throw VehicleQueueError.storage }
}

@main struct VehicleEventQueueChecks {
    @MainActor static func fails(_ body: () async throws -> Void) async {
        do { try await body(); fatalError("Expected rejection") } catch { }
    }

    static func crash(_ directory: URL, mode: String) throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: CommandLine.arguments[0])
        process.arguments = [mode, directory.path]
        try process.run(); process.waitUntilExit()
        precondition(process.terminationStatus == 73)
    }

    static func authorize(_ queue: VehicleEventQueue, _ context: VehicleQueueContext, _ vehicles: Set<UUID>) async throws {
        let generation = try await queue.beginVerification(context)
        try await queue.completeVerification(context, generation: generation, vehicles: vehicles)
    }

    static func main() async throws {
        if CommandLine.arguments.count == 6 {
            let args = CommandLine.arguments
            let directory = URL(fileURLWithPath: args[2])
            let c = try VehicleQueueContext(environment: .development,
                identity: .init(owner: UUID(uuidString: args[3])!, user: 1, family: 2, generation: 0, version: 0),
                device: UUID(uuidString: args[4])!)
            if args[1] == "crash-pending" {
                let q = try VehicleEventQueue(directory: directory)
                _ = try await q.beginVerification(c)
                _exit(73)
            }
            if args[1] == "revoke" { try VehicleEventQueue.revokeAuthorization(directory: directory, context: c) }
            else {
                let q = try VehicleEventQueue(directory: directory)
                _ = try await q.enqueueTake(c, vehicle: UUID(uuidString: args[5])!, occurredAt: Date(timeIntervalSince1970: 1_800_000_000))
            }
            return
        }
        if CommandLine.arguments.count == 3 {
            // Abrupt process death with an open rollback journal, not a caught Swift error.
            var db: OpaquePointer?
            let path = URL(fileURLWithPath: CommandLine.arguments[2]).appendingPathComponent("vehicle-events.sqlite").path
            precondition(sqlite3_open(path, &db) == SQLITE_OK)
            let statement = CommandLine.arguments[1] == "crash-create"
                ? "BEGIN IMMEDIATE; UPDATE devices SET last_sequence=last_sequence+1; INSERT INTO events SELECT 'crashed',context,last_sequence,'v',NULL,'{}','pending',NULL,NULL,NULL,NULL FROM devices LIMIT 1;"
                : "BEGIN IMMEDIATE; UPDATE events SET state='registered',session='crashed.session',task=99;"
            precondition(sqlite3_exec(db, statement, nil, nil, nil) == SQLITE_OK)
            _exit(73)
        }
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("fca-queue-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let identity = ChatIdentity(owner: UUID(), user: 1, family: 2, generation: 0, version: 0)
        let context = try VehicleQueueContext(environment: .development, identity: identity, device: UUID())
        let queue = try VehicleEventQueue(directory: root)
        try await queue.initializeFreshDevice(context)
        let vehicle = UUID(), otherVehicle = UUID()
        try await authorize(queue, context, [vehicle, otherVehicle])
        let now = Date(timeIntervalSince1970: 1_800_000_000.125)
        let shortcutContext = try VehicleQueueContext(environment: .development, identity: identity, device: UUID())
        try await queue.initializeFreshDevice(shortcutContext)
        try await authorize(queue, shortcutContext, [vehicle, otherVehicle])
        let fix = VehicleLocationEvidence(latitude: 32, longitude: 34, accuracy: 5, measuredAt: now)
        let a = try await queue.recordShortcut(shortcutContext, vehicle: vehicle, kind: .take, time: now, location: nil)
        let b = try await queue.recordShortcut(shortcutContext, vehicle: otherVehicle, kind: .take, time: now, location: nil)
        await fails { _ = try await queue.recordShortcut(shortcutContext, vehicle: vehicle, kind: .take, time: now, location: nil) }
        await fails { _ = try await queue.recordShortcut(shortcutContext, vehicle: vehicle, kind: .returning, time: now, location: nil) }
        await fails { _ = try await queue.recordShortcut(shortcutContext, vehicle: vehicle, kind: .returning, time: now.addingTimeInterval(31), location: fix) }
        let ra = try await queue.recordShortcut(shortcutContext, vehicle: vehicle, kind: .returning, time: now, location: fix)
        await fails { _ = try await queue.recordShortcut(shortcutContext, vehicle: vehicle, kind: .returning, time: now, location: fix) }
        let rb = try await queue.recordShortcut(shortcutContext, vehicle: otherVehicle, kind: .returning, time: now, location: fix)
        precondition([a.sequence, b.sequence, ra.sequence, rb.sequence] == [1,2,3,4])
        precondition(ra.takeID == a.id && rb.takeID == b.id && ra.location == fix && ra.occurredAt == now)
        let take = try await queue.enqueueTake(context, vehicle: vehicle, occurredAt: now)
        precondition(take.sequence == 1)
        let same = try await queue.enqueueTake(context, id: take.id, vehicle: vehicle, occurredAt: now)
        precondition(same == take)
        await fails { _ = try await queue.enqueueTake(context, id: take.id, vehicle: otherVehicle, occurredAt: now) }
        let evidence = VehicleLocationEvidence(latitude: 32, longitude: 34, accuracy: 10, measuredAt: now)
        let returning = try await queue.enqueueReturn(context, vehicle: vehicle, occurredAt: now,
                                                       takeID: take.id, location: evidence)
        precondition(returning.sequence == 2)
        await fails { _ = try await queue.enqueueReturn(context, vehicle: vehicle, occurredAt: now, takeID: take.id, location: evidence) }
        await fails { _ = try await queue.enqueueReturn(context, vehicle: otherVehicle, occurredAt: now, takeID: take.id, location: evidence) }
        await fails { _ = try await queue.enqueueReturn(context, vehicle: vehicle, occurredAt: now, takeID: UUID(), location: evidence) }
        let third = try await queue.enqueueTake(context, vehicle: otherVehicle, occurredAt: now)
        precondition(third.sequence == 3) // Failed duplicate RETURN rolled back allocated sequence.
        let preparing = try await queue.prepareNext(context)!
        precondition(preparing.event == take && preparing.state == .preparing)
        let held = try await queue.prepareNext(context); precondition(held == nil)
        await fails { try await queue.markRegistered(context, event: take.id, attempt: UUID(), sessionIdentifier: "fca.test", taskIdentifier: 1) }
        try crash(root, mode: "crash-register")
        let reopened = try VehicleEventQueue(directory: root)
        var rows = try await reopened.records(context)
        precondition(rows[0].state == .preparing && rows[0].sessionIdentifier == nil)
        try await reopened.markRegistered(context, event: take.id, attempt: preparing.attempt!, sessionIdentifier: "fca.test", taskIdentifier: 1)
        let secondConnection = try VehicleEventQueue(directory: root)
        rows = try await secondConnection.records(context)
        precondition(rows[0].state == .registered && rows[0].taskIdentifier == 1 && rows[0].attempt == preparing.attempt)
        try await reopened.recordFailure(context, event: take.id, attempt: preparing.attempt!, failure: .deliveryUnknown)
        let stopped = try await reopened.prepareNext(context); precondition(stopped == nil)
        try await reopened.retryAfterTaskReconciliation(context, event: take.id, attempt: preparing.attempt!)
        let retry = try await reopened.prepareNext(context)!
        precondition(retry.event == take && retry.attempt != preparing.attempt)
        await fails { try await reopened.applyAdmission(context, event: take.id, attempt: preparing.attempt!, receipt: .init(kind: "accepted", admission_outcome: "accepted")) }
        await fails { try await reopened.applyAdmission(context, event: take.id, attempt: retry.attempt!, receipt: .init(kind: "accepted", admission_outcome: nil)) }
        try await reopened.recordFailure(context, event: take.id, attempt: retry.attempt!, failure: .authentication)
        rows = try await reopened.records(context); precondition(rows[0].state == .awaitingAuthentication)
        try await reopened.retryAfterTaskReconciliation(context, event: take.id, attempt: retry.attempt!)
        let authenticated = try await reopened.prepareNext(context)!
        try await reopened.applyAdmission(context, event: take.id, attempt: authenticated.attempt!, receipt: .init(kind: "retry", admission_outcome: "accepted"))
        let next = try await reopened.prepareNext(context)!
        precondition(next.event == returning)
        try await reopened.recordFailure(context, event: returning.id, attempt: next.attempt!, failure: .preAdmissionRejection)
        await fails { try await reopened.retryAfterTaskReconciliation(context, event: returning.id, attempt: next.attempt!) }
        let blocked = try await reopened.prepareNext(context); precondition(blocked == nil)
        try await reopened.applyAdmission(context, event: returning.id, attempt: next.attempt!, receipt: .init(kind: "terminal", admission_outcome: "causal_conflict"))
        let finalHead = try await reopened.prepareNext(context)!
        precondition(finalHead.event == third)
        try await reopened.suspend(context)
        await fails { _ = try await reopened.enqueueTake(context, vehicle: vehicle, occurredAt: now) }
        await fails { try await reopened.applyAdmission(context, event: third.id, attempt: finalHead.attempt!, receipt: .init(kind: "accepted", admission_outcome: "accepted")) }
        try await reopened.initializeFreshDevice(context) // Must not undo logout.
        await fails { _ = try await reopened.prepareNext(context) }
        let foreignIdentity = ChatIdentity(owner: UUID(), user: 3, family: 4, generation: 1, version: 1)
        let foreign = try VehicleQueueContext(environment: .development, identity: foreignIdentity, device: context.device)
        await fails { try await reopened.initializeFreshDevice(foreign) }
        await fails { _ = try await reopened.records(foreign) }
        let familySwitch = try VehicleQueueContext(environment: .development,
            identity: ChatIdentity(owner: identity.owner, user: 1, family: 5, generation: 1, version: 1), device: context.device)
        await fails { try await reopened.initializeFreshDevice(familySwitch) }
        let newDevice = try VehicleQueueContext(environment: .development, identity: foreignIdentity, device: UUID())
        try await reopened.initializeFreshDevice(newDevice)
        try await authorize(reopened, newDevice, [vehicle])
        await fails { _ = try await reopened.enqueueReturn(newDevice, vehicle: vehicle, occurredAt: now, takeID: take.id, location: evidence) }
        let fresh = try await reopened.enqueueTake(newDevice, vehicle: vehicle, occurredAt: now)
        precondition(fresh.sequence == 1)
        try await reopened.reactivate(context)
        try await authorize(reopened, context, [vehicle, otherVehicle])
        try crash(root, mode: "crash-create")
        rows = try await reopened.records(context)
        precondition(rows.map(\.event) == [take, returning, third])
        let afterCrash = try await reopened.enqueueTake(context, vehicle: vehicle, occurredAt: now)
        precondition(afterCrash.sequence == 4)

        // Multiple actors/connections contend on the same device, not just one actor mailbox.
        try await withThrowingTaskGroup(of: Void.self) { group in
            for index in 0..<24 {
                group.addTask {
                    let writer = index % 2 == 0 ? queue : reopened
                    _ = try await writer.enqueueTake(context, vehicle: index % 2 == 0 ? vehicle : otherVehicle, occurredAt: now)
                }
            }
            try await group.waitForAll()
        }
        rows = try await reopened.records(context)
        precondition(rows.map(\.event.sequence) == Array(1...28).map(Int64.init))
        precondition(Set(rows.map(\.event.id)).count == 28)

        // Failed SQL insertion after counter update rolls back both changes.
        try sql(root, "CREATE TRIGGER fail_insert BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'test'); END")
        await fails { _ = try await reopened.enqueueTake(context, vehicle: vehicle, occurredAt: now) }
        try sql(root, "DROP TRIGGER fail_insert")
        let afterRollback = try await reopened.enqueueTake(context, vehicle: vehicle, occurredAt: now)
        precondition(afterRollback.sequence == 29)
        await fails { _ = try await reopened.enqueueTake(context, vehicle: vehicle, occurredAt: Date(timeIntervalSince1970: .infinity)) }
        let invalid = VehicleLocationEvidence(latitude: .nan, longitude: 34, accuracy: 10, measuredAt: now)
        await fails { _ = try await reopened.enqueueReturn(context, vehicle: vehicle, occurredAt: now, takeID: afterRollback.id, location: invalid) }
        for bad in [
            VehicleLocationEvidence(latitude: 91, longitude: 34, accuracy: 10, measuredAt: now),
            VehicleLocationEvidence(latitude: 32, longitude: 181, accuracy: 10, measuredAt: now),
            VehicleLocationEvidence(latitude: 32, longitude: 34, accuracy: 0, measuredAt: now),
            VehicleLocationEvidence(latitude: 32, longitude: 34, accuracy: 101, measuredAt: now),
            VehicleLocationEvidence(latitude: 32, longitude: 34, accuracy: 10, measuredAt: now.addingTimeInterval(-31)),
            VehicleLocationEvidence(latitude: 32, longitude: 34, accuracy: 10, measuredAt: now.addingTimeInterval(1))
        ] {
            await fails { _ = try await reopened.enqueueReturn(context, vehicle: vehicle, occurredAt: now, takeID: afterRollback.id, location: bad) }
        }
        let unchanged = try await reopened.records(context)
        precondition(unchanged.last?.event.sequence == 29)

        let isolated = try VehicleEventQueue(directory: root.appendingPathComponent("causality"))
        try await isolated.initializeFreshDevice(context)
        try await authorize(isolated, context, [vehicle])
        let rejectedTake = try await isolated.enqueueTake(context, vehicle: vehicle, occurredAt: now)
        _ = try await isolated.enqueueReturn(context, vehicle: vehicle, occurredAt: now, takeID: rejectedTake.id, location: evidence)
        let rejectedHead = try await isolated.prepareNext(context)!
        try await isolated.applyAdmission(context, event: rejectedTake.id, attempt: rejectedHead.attempt!, receipt: .init(kind: "retry", admission_outcome: "vehicle_retired"))
        let unavailableReturn = try await isolated.prepareNext(context); precondition(unavailableReturn == nil)
        let causalRows = try await isolated.records(context)
        precondition(causalRows[1].state == .blocked && causalRows[1].reason == "cause_not_accepted")

        let missing = try VehicleEventQueue(directory: root.appendingPathComponent("missing"))
        try await missing.initializeFreshDevice(context)
        try await authorize(missing, context, [vehicle])
        let missingTake = try await missing.enqueueTake(context, vehicle: vehicle, occurredAt: now)
        _ = try await missing.enqueueReturn(context, vehicle: vehicle, occurredAt: now, takeID: missingTake.id, location: nil)
        let missingRows = try await missing.records(context)
        precondition(missingRows[1].state == .blocked && missingRows[1].reason == "missing_location")
        let missingHead = try await missing.prepareNext(context)!
        await fails { try await missing.applyAdmission(context, event: missingTake.id, attempt: missingHead.attempt!, receipt: .init(kind: "terminal", admission_outcome: "unknown_outcome")) }
        try await missing.applyAdmission(context, event: missingTake.id, attempt: missingHead.attempt!, receipt: .init(kind: "gap", admission_outcome: nil))
        let gapHead = try await missing.prepareNext(context); precondition(gapHead == nil)
        await fails { try await missing.retryAfterTaskReconciliation(context, event: missingTake.id, attempt: missingHead.attempt!) }
        try sql(root.appendingPathComponent("missing"), "PRAGMA user_version=99")
        await fails { _ = try VehicleEventQueue(directory: root.appendingPathComponent("missing")) }
        // Authorization migration: retain events/cursor but never infer grants from legacy state.
        let fenceRoot = root.appendingPathComponent("fence")
        let fence = try VehicleEventQueue(directory: fenceRoot)
        try await fence.initializeFreshDevice(context)
        await fails { _ = try await fence.enqueueTake(context, vehicle: vehicle, occurredAt: now) }
        try await authorize(fence, context, [vehicle, otherVehicle])
        let before = try await fence.enqueueTake(context, vehicle: vehicle, occurredAt: now)
        try sql(fenceRoot, "DROP TABLE vehicle_authorizations; DROP TABLE authorization_scopes; PRAGMA user_version=1")
        let migrated = try VehicleEventQueue(directory: fenceRoot)
        let retainedBefore = try await migrated.records(context)
        precondition(retainedBefore.map(\.event) == [before])
        await fails { _ = try await migrated.enqueueTake(context, vehicle: vehicle, occurredAt: now) }
        try await authorize(migrated, context, [vehicle, otherVehicle])
        let after = try await migrated.enqueueTake(context, vehicle: otherVehicle, occurredAt: now)
        precondition(after.sequence == 2)

        // Out-of-order server evidence cannot undo a newer verification or logout.
        let oldGeneration = try await migrated.beginVerification(context)
        let currentGeneration = try await migrated.beginVerification(context)
        await fails { try await migrated.completeVerification(context, generation: oldGeneration, vehicles: [vehicle]) }
        await fails { _ = try await migrated.enqueueTake(context, vehicle: vehicle, occurredAt: now) }
        try await migrated.completeVerification(context, generation: currentGeneration, vehicles: [otherVehicle])
        await fails { _ = try await migrated.enqueueTake(context, vehicle: vehicle, occurredAt: now) }
        let pendingLogout = try await migrated.beginVerification(context)
        try VehicleEventQueue.revokeAuthorization(directory: fenceRoot, context: context)
        await fails { try await migrated.completeVerification(context, generation: pendingLogout, vehicles: [vehicle]) }

        // Failure before the preflight commit MUST prevent starting server verification.
        try await authorize(migrated, context, [vehicle, otherVehicle])
        try sql(fenceRoot, "CREATE TRIGGER fail_fence BEFORE UPDATE ON authorization_scopes BEGIN SELECT RAISE(ABORT,'test'); END")
        var requests = 0
        await fails {
            _ = try await migrated.beginVerification(context)
            requests += 1
        }
        precondition(requests == 0)
        try sql(fenceRoot, "DROP TRIGGER fail_fence")
        let failedSave = try await migrated.beginVerification(context)
        try sql(fenceRoot, "CREATE TRIGGER fail_grants BEFORE UPDATE ON vehicle_authorizations BEGIN SELECT RAISE(ABORT,'test'); END")
        await fails { try await migrated.completeVerification(context, generation: failedSave, vehicles: []) }
        let recovered = try VehicleEventQueue(directory: fenceRoot)
        let denied = try await recovered.authorizedVehicles(context)
        precondition(denied.isEmpty)
        await fails { _ = try await recovered.enqueueTake(context, vehicle: vehicle, occurredAt: now) }
        try sql(fenceRoot, "DROP TRIGGER fail_grants")
        try await authorize(recovered, context, [vehicle, otherVehicle])

        func child(_ mode: String) throws -> Process {
            let child = Process()
            child.executableURL = URL(fileURLWithPath: CommandLine.arguments[0])
            child.arguments = [mode, fenceRoot.path, context.owner.uuidString, context.device.uuidString, vehicle.uuidString]
            try child.run()
            return child
        }
        let crashed = try child("crash-pending"); crashed.waitUntilExit()
        precondition(crashed.terminationStatus == 73)
        let afterProcessCrash = try VehicleEventQueue(directory: fenceRoot)
        await fails { _ = try await afterProcessCrash.enqueueTake(context, vehicle: vehicle, occurredAt: now) }
        try await authorize(recovered, context, [vehicle, otherVehicle])
        // If the scope write fails, the independent devices.active quarantine remains effective.
        let preFailureTicket = try await recovered.beginVerification(context)
        try sql(fenceRoot, "CREATE TRIGGER fail_revoke BEFORE UPDATE ON authorization_scopes BEGIN SELECT RAISE(ABORT,'test'); END")
        await fails { try VehicleEventQueue.revokeAuthorization(directory: fenceRoot, context: context) }
        await fails { _ = try await afterProcessCrash.enqueueTake(context, vehicle: vehicle, occurredAt: now) }
        try sql(fenceRoot, "DROP TRIGGER fail_revoke")
        try await recovered.reactivate(context)
        await fails { try await recovered.completeVerification(context, generation: preFailureTicket, vehicles: [vehicle]) }
        try await authorize(recovered, context, [vehicle, otherVehicle])
        // Actual separate-process revocation, after a committed TAKE and before the paused next TAKE.
        let ready = AsyncStream<Void>.makeStream(), release = AsyncStream<Void>.makeStream()
        let paused = Task {
            ready.continuation.yield(())
            for await _ in release.stream { break }
            return try await recovered.enqueueTake(context, vehicle: vehicle, occurredAt: now)
        }
        for await _ in ready.stream { break }
        let revoker = try child("revoke"); revoker.waitUntilExit()
        precondition(revoker.terminationStatus == 0)
        release.continuation.yield(()); release.continuation.finish(); ready.continuation.finish()
        await fails { _ = try await paused.value }
        let retainedAfter = try await recovered.records(context)
        precondition(retainedAfter.map(\.event) == [before, after])
        try await authorize(recovered, context, [vehicle, otherVehicle])
        let children = try (0..<6).map { _ in try child("record") }
        for child in children { child.waitUntilExit(); precondition(child.terminationStatus == 0) }
        let concurrentRows = try await recovered.records(context)
        precondition(concurrentRows.map(\.event.sequence) == Array(1...8).map(Int64.init))
        // A previous login namespace cannot record after fresh server authorization for a new login.
        let oldNamespace = UUID(), newNamespace = UUID()
        let ticket = try await recovered.beginVerification(context)
        try await recovered.completeVerification(context, generation: ticket, vehicles: [vehicle], namespace: newNamespace)
        await fails {
            _ = try await recovered.recordAuthorizedShortcut(context, vehicle: vehicle, kind: .take, time: now,
                location: nil, namespace: oldNamespace, permit: VehicleRecordingPermit())
        }
        // A corrupt state or lost grant row never becomes an implicit permission.
        try sql(fenceRoot, "PRAGMA ignore_check_constraints=ON; UPDATE authorization_scopes SET state='corrupt'")
        await fails { _ = try await recovered.enqueueTake(context, vehicle: vehicle, occurredAt: now) }
        try await authorize(recovered, context, [vehicle])
        try sql(fenceRoot, "DELETE FROM vehicle_authorizations")
        await fails { _ = try await recovered.enqueueTake(context, vehicle: vehicle, occurredAt: now) }
        // Explicitly expose the impossible guarantee when BOTH durable fence writes fail.
        try await authorize(recovered, context, [vehicle])
        try sql(fenceRoot, "CREATE TRIGGER fail_all_scope BEFORE UPDATE ON authorization_scopes BEGIN SELECT RAISE(ABORT,'test'); END; CREATE TRIGGER fail_all_device BEFORE UPDATE ON devices BEGIN SELECT RAISE(ABORT,'test'); END")
        await fails { try VehicleEventQueue.revokeAuthorization(directory: fenceRoot, context: context) }
        let survivingDiskGrant = try await afterProcessCrash.authorizedVehicles(context)
        precondition(survivingDiskGrant.contains(vehicle))
        print("LIMITATION: total fence-write failure leaves old durable state; fresh process cannot infer failed logout")
        try sql(fenceRoot, "DROP TRIGGER fail_all_scope; DROP TRIGGER fail_all_device")
        print("PASS: authorization migration, pending/unknown/revoked fences, stale evidence, persistence failures and separate-process ordering")
        print("PASS: durable queue, sequencing, concurrency, identity, causality, admission, rollback and process-crash recovery")
    }
}
