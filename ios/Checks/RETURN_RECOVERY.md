# RETURN recovery — local Phase 2 verification

Backend/migration files are unchanged in Phase 2. The client follows
`backend/RETURN_RECOVERY.md`: `recovery_id`, `original_return`, `verification`
(`invoked_at`, `location_at`, `latitude`, `longitude`, `accuracy_m`). Normal and
recovery uploads share the original event wire encoder, preserving timestamp
precision and GPS values. Recovery JSON is persisted once, before scheduling.

SQLite schema version 3 adds a separate immutable-payload recovery table and a
unique active-attempt index. Opening an existing queue preserves all events and
sequence numbers. Accepted recovery and original-event acknowledgement are one
SQLite transaction. No account/device/environment partition is merged or reset.

Only the two structured home-location 409 codes authorize an explicit new
Shortcut recovery. Historical `preAdmissionRejection` is not inferred eligible.
Uncertain requests retain identical bytes/ID across retries and restarts, including
after the 120-second window. Definitive home/expiry refusals permit another explicit
invocation; other refusals remain blocked. An existing transport task is reconciled
before any replacement upload. Upload files are published atomically without
replacing different existing bytes. Orphan staging files after a crash contain no
credentials and do not become upload requests.

## Checks allowed without a build

From repository root:

```powershell
.\.venv\Scripts\python.exe -B ios/Checks/test-return-recovery.py
```

Seven tests exercise the actual recovery-table DDL in disposable in-memory SQLite
and compare outgoing wire keys with the actual Backend model definitions. They do
not execute Swift behavior. Swift syntax and `-typecheck` checks are additional
validation, not physical-device or E2E evidence.

## Before the next TestFlight build

1. With separate approval for compiling test executables, run on a machine with
   Swift 6 and SQLite headers/libraries:

   ```sh
   bash ios/Checks/run-vehicle-queue-checks.sh
   bash ios/Checks/run-vehicle-sync-checks.sh
   ```

   The sync checks include structured home rejection, fresh recovery, unchanged
   original wire bytes, repeated invocation, reopening SQLite, restoring an
   existing upload, lost response and identical retry after expiry, queued TAKE,
   home/expiry/order/legacy/unknown refusals. Existing offline tests remain included.

2. With separate authorization for local database migrations, apply Phase 1 to a
   disposable PostgreSQL database and run real transaction/concurrency/cascade
   validation. Do not use Production data or provider credentials.
3. Use an isolated local API with a test authenticated owner/device/vehicle, valid
   binding and home. Admit TAKE; reject RETURN with outside-home evidence; confirm
   a durable candidate; submit the client's recovery bytes with a fresh home fix.
   Assert exactly one RETURN receipt, unchanged event time/sequence/cause, one
   recovery result and successful admission of the next queued TAKE.
4. Drop the recovery response after its server commit. Replay identical bytes/ID
   after 120 seconds and assert the same result and no duplicate receipt. Also test
   interrupted pre-commit requests, stale/future measurements, mismatched payload,
   revocation and finalized/72h chronology refusal. No queue skipping is permitted.
5. Only after these checks, separately authorize an app build and device validation
   of App Intent location provenance, protected storage, background URLSession
   restoration and clock differences. This phase did not build or sign the app.

The existing Production legacy event still requires individual trusted server
evidence/manual review; installing this client does not automatically unblock it.
The Backend migration and endpoint must be deployed separately before activation.
