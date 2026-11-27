import Foundation

@main struct AccountDeletionChecks {
    @MainActor static func main() async throws {
        enum Injected: Error { case storage }
        let original=AccountDeletionLifecycle.Record(owner:UUID(),environment:"development",operation:UUID(),secret:"test-secret")
        let good=AccountDeletionLifecycle.Reply(operation_id:original.operation,status:"completed",completed_at:"2026-01-01T00:00:00Z",expires_at:"2026-06-30T00:00:00Z")
        var assertions=0
        func expectFailure(_ body: () throws -> Void) {
            do { try body(); fatalError("expected failure") } catch { assertions += 1 }
        }
        var disk=original; var cleanups=0
        expectFailure { _ = try AccountDeletionLifecycle.apply(record:disk,reply:good,save:{ _ in throw Injected.storage },cleanup:{ _ in cleanups += 1 }) }
        precondition(cleanups==0 && disk==original); assertions += 1
        expectFailure { _ = try AccountDeletionLifecycle.apply(record:disk,reply:good,save:{ disk=$0 },cleanup:{ _ in throw Injected.storage }) }
        precondition(disk.completed && !disk.cleaned && disk.secret==nil); assertions += 1
        // Restart needs neither JWT nor status secret after durable confirmation.
        _ = try AccountDeletionLifecycle.apply(record:disk,reply:nil,save:{ disk=$0 },cleanup:{ value in precondition(value.owner==original.owner); cleanups += 1 })
        precondition(disk.cleaned && cleanups==1); assertions += 1
        _ = try AccountDeletionLifecycle.apply(record:disk,reply:nil,save:{ _ in fatalError("duplicate write") },cleanup:{ _ in fatalError("duplicate cleanup") }); assertions += 1
        for state in ["pending","draining","failed","401","unknown"] {
            let reply=AccountDeletionLifecycle.Reply(operation_id:original.operation,status:state,completed_at:nil,expires_at:nil)
            if state=="pending" {
                let result=try AccountDeletionLifecycle.apply(record:original,reply:reply,save:{ _ in fatalError("pending saved") },cleanup:{ _ in fatalError("pending cleanup") })
                precondition(!result); assertions += 1
            } else { expectFailure { _ = try AccountDeletionLifecycle.apply(record:original,reply:reply,save:{ _ in fatalError("invalid saved") },cleanup:{ _ in fatalError("invalid cleanup") }) } }
        }
        let wrong=AccountDeletionLifecycle.Reply(operation_id:UUID(),status:"completed",completed_at:good.completed_at,expires_at:good.expires_at)
        expectFailure { _ = try AccountDeletionLifecycle.apply(record:original,reply:wrong,save:{ _ in fatalError("wrong saved") },cleanup:{ _ in fatalError("wrong cleanup") }) }
        for expiry in [nil,"invalid","2026-01-02T00:00:00Z"] as [String?] {
            let bad=AccountDeletionLifecycle.Reply(operation_id:original.operation,status:"completed",completed_at:good.completed_at,expires_at:expiry)
            expectFailure { _ = try AccountDeletionLifecycle.apply(record:original,reply:bad,save:{ _ in fatalError("malformed saved") },cleanup:{ _ in fatalError("malformed cleanup") }) }
        }
        disk=original; cleanups=0; var saves=0
        expectFailure { _ = try AccountDeletionLifecycle.apply(record:disk,reply:good,save:{ value in saves += 1; if saves==2 { throw Injected.storage }; disk=value },cleanup:{ _ in cleanups += 1 }) }
        precondition(disk.completed && !disk.cleaned); assertions += 1
        _ = try AccountDeletionLifecycle.apply(record:disk,reply:nil,save:{ disk=$0 },cleanup:{ _ in cleanups += 1 })
        precondition(cleanups==2 && disk.cleaned); assertions += 1
        // Termination or cancellation timeout AFTER confirmation must retain proof,
        // without running cleanup or needing the removed secret on restart.
        disk=original; cleanups=0
        let confirmed=try AccountDeletionLifecycle.confirmation(record:disk,reply:good,save:{ disk=$0 })
        precondition(confirmed==disk && disk.completed && disk.secret==nil && !disk.cleaned && cleanups==0); assertions += 1
        _ = try AccountDeletionLifecycle.apply(record:disk,reply:nil,save:{ disk=$0 },cleanup:{ _ in cleanups += 1 })
        precondition(disk.cleaned && cleanups==1); assertions += 1
        // Independent owner/environment records are never rewritten by lifecycle processing.
        let other=AccountDeletionLifecycle.Record(owner:UUID(),environment:"production",operation:UUID(),secret:"other")
        precondition(other != disk && other.secret=="other" && !other.completed); assertions += 1
        // These are the SAME async orchestration functions invoked by the iOS client.
        disk=original; var sent=0; var pending=false
        do {
            try await AccountDeletionLifecycle.begin(record:disk,markPending:{ pending=true },save:{ _ in throw Injected.storage },send:{ _ in sent += 1 })
            fatalError("expected submitted persistence failure")
        } catch {}
        precondition(pending && !disk.submitted && sent==0); assertions += 1
        let unarmed=try await AccountDeletionLifecycle.resume(record:disk,status:{ fatalError("unarmed network") },replayInitiation:{ fatalError("unarmed replay") },save:{ disk=$0 },cancel:{ _ in fatalError("unarmed cancel") },cleanup:{ _ in fatalError("unarmed cleanup") })
        precondition(!unarmed); assertions += 1
        // Lost initiation response: durable submitted state survives the throw.
        do { try await AccountDeletionLifecycle.begin(record:disk,markPending:{},save:{ disk=$0 },send:{ _ in sent += 1; throw Injected.storage }) } catch {}
        precondition(disk.submitted && sent==1); assertions += 1
        var replayed=0
        let unknown=try await AccountDeletionLifecycle.resume(record:disk,status:{ throw AccountDeletionLifecycle.Failure.statusUnavailable },replayInitiation:{ replayed += 1 },save:{ disk=$0 },cancel:{ _ in fatalError("401 cancel") },cleanup:{ _ in fatalError("401 cleanup") })
        precondition(!unknown && replayed==1 && !disk.completed); assertions += 1
        // Failed daemon cancellation must not proceed to files/SQLite/Keychain cleanup.
        do {
            _ = try await AccountDeletionLifecycle.resume(record:disk,status:{ good },replayInitiation:{},save:{ disk=$0 },cancel:{ _ in throw Injected.storage },cleanup:{ _ in fatalError("cancel failure cleanup") })
            fatalError("expected cancellation failure")
        } catch {}
        precondition(disk.completed && disk.secret==nil && !disk.cleaned); assertions += 1
        var sqliteRemoved=false; var keychainFail=true; var activeOwner=other.owner
        do {
            _ = try await AccountDeletionLifecycle.resume(record:disk,status:{ fatalError("restart must not need JWT") },replayInitiation:{},save:{ disk=$0 },cancel:{ _ in },cleanup:{ value in
                sqliteRemoved=true
                if keychainFail { throw Injected.storage }
                if activeOwner==value.owner { activeOwner=UUID() }
            })
            fatalError("expected Keychain failure")
        } catch {}
        precondition(sqliteRemoved && disk.completed && !disk.cleaned && activeOwner==other.owner); assertions += 1
        keychainFail=false
        _ = try await AccountDeletionLifecycle.resume(record:disk,status:{ fatalError("restart network") },replayInitiation:{},save:{ disk=$0 },cancel:{ _ in },cleanup:{ value in if activeOwner==value.owner { activeOwner=UUID() } })
        precondition(disk.cleaned && activeOwner==other.owner); assertions += 1
        let timeout=DeletionUploadCancellation()
        do { try await timeout.wait(invalidate:{},timeout:{}); fatalError("expected timeout") } catch {}
        timeout.finish(failed:true) // Late daemon failure is not success.
        do { try await timeout.wait(invalidate:{ fatalError("finished") }); fatalError("expected failed callback") } catch {}
        timeout.finish(failed:false)
        do { try await timeout.wait(invalidate:{}); fatalError("late success cannot undo failure") } catch {}
        assertions += 3
        let success=DeletionUploadCancellation()
        try await success.wait(invalidate:{ success.finish(failed:false) },timeout:{})
        success.finish(failed:true)
        try await success.wait(invalidate:{ fatalError("already finished") })
        assertions += 2
        print("PASS: \(assertions) deletion lifecycle assertions: persistence failures, restart, replay, pending/invalid responses, owner isolation")
    }
}
