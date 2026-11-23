# Current-state RETURN reconciliation

Local implementation; no live migration, deployment or device verification performed.

## Protocol

`POST /api/devices/{device_ref}/events/return/{event_id}/reconciliation` is JWT authenticated.
The body contains `reconciliation_id` (UUID4), `original_return` (existing Return model),
and `verification` (existing ReturnVerification model). Unknown fields are rejected.
New operations are disabled unless `RETURN_RECONCILIATION_ENABLED=true` in the Backend process.
While disabled, authenticated retries with the same candidate, ID and fingerprint can
retrieve their committed result unchanged; no new attempt or operation is persisted.
This is a rollout gate, not eligibility or permission supplied by the client.

Only a server-recorded immutable home-rejection candidate qualifies. All ownership,
active binding, sequence, chronology, accepted TAKE and open linked session checks
are independent of time rejection. Under family serialization, the effective boundary
is max(stored boundary, database clock minus 72 hours). Equality is rejected historically.
The new verification retains the existing 30-second measurement freshness, 120-second
request age, accuracy <=100m, and distance + accuracy <=500m home rule.

The complete checkpoint advances only to that effective boundary, freezing the causal
session anchor. Work-limit or transactional failure rolls everything back. The original
RETURN receives a terminal `before_finalized_boundary` receipt (never accepted), its
sequence is consumed, and a separate current-time resolution closes ONLY that anchor.
The candidate and recovery attempts remain unchanged. A successful response is
`kind=resolved_current_state`, with the original event/sequence, terminal historical
receipt, canonical reconciliation/operation IDs, effective_at and last_processed_sequence.

Identical retries return the stored result before rechecking freshness. A different
payload for the same key fails. A different key after success returns the canonical
committed result without creating another operation; clients must retain that actual
operation identity. Rejected fresh-location attempts need a new explicit invocation.
No GPS coordinates are copied to the new database tables; a canonical fingerprint
binds the immutable request. Existing candidate evidence remains governed by existing
account deletion cascades.

## Projection/order

Ordinary event order remains timestamp + device/cause DAG + UUID ties. Resolution
operations follow ordinary events at the same instant, then sort by operation UUID.
They are not accepted vehicle events and do not take another device sequence.
A late ordinary event may have already closed the anchored session; resolution then
has no additional projection effect. It never closes the replacement session/driver.
A TAKE before resolution can be redundant; its RETURN refers to the same old session.
A new logical TAKE after a prior ordinary RETURN is not closed by this resolution.
Events behind the later cutoff receive ordinary explicit terminal receipts.

Full replay loads operations above the checkpoint; already-frozen closed targets need
no replay action. Strictly later evidence can use incremental materialization, preserving
normal notification behavior. Checkpoint carries current open sessions and absorbs old
operations without reopening them. No notification is fabricated for the terminal RETURN.

## iOS

SQLite v4 adds `return_reconciliations`, separate from original events/recovery tasks.
An explicit RETURN after a definitive historical Recovery ORDER_CONFLICT creates a
separate reconciliation request. This is permission to ask the server, not proof of
eligibility. Unknown/legacy rejection records remain blocked. Existing historical
Recovery otherwise retains its behavior. Cross-table triggers prevent concurrent work.

Payload bytes and UUID survive background-task restoration, uncertainty and restart.
No automatic fresh measurement after expiry. The original event remains blocked until
a validated server acknowledgment is stored atomically with its terminal state. Queued
subsequent events then run normally in order. No timestamps or event payloads are changed.

## Migration / deployment (owner approval required; not executed on real environments)

1. Apply `supabase/manual_migrations/2026112301_return_current_state_reconciliation.sql`
   as the existing migration owner, after the RETURN Recovery migration. It is an
   additive transaction, not a startup migration; do not reapply it.
2. Deploy the compatible Backend with the new endpoint disabled. The schema must exist
   because normal admission now understands resolutions too.
3. Drain ALL older Backend processes/writers before setting
   `RETURN_RECONCILIATION_ENABLED=true`. Do not enable during a mixed-version rollout.
4. Release the compatible iOS client, then perform controlled physical-device E2E.
5. Rollback after any successful resolution must retain a compatible projection reader.
   Disable new reconciliation requests if necessary; do not roll back to an old reader,
   drop the tables, or mutate historical receipts.

Recommended review units: migration + Backend/projection + PostgreSQL tests together;
then iOS queue/coordinator + Swift/SQLite checks. No workflow/signing changes required.

## Local tests

Use only a disposable loopback database named `test_gemini`; fixtures reject other hosts
or database names. Set `GEMINI_TEST_DATABASE_URL` and `DATABASE_URL` to that local DSN.
The fixture needs the existing test roles anon/authenticated/service_role and a local
superuser gemini_test. It applies actual migration DDL in random schemas and cleans them.

From backend: `python -B -m unittest tests.test_return_reconciliation.ResolutionPostgresTests tests.test_return_reconciliation_api.ResolutionApiTests`
Regression: `python -B -m unittest tests.test_vehicle_reconciliation tests.test_vehicle_admission tests.test_return_recovery tests.test_device_bindings tests.test_vehicle_lifecycle tests.test_account_deletion`
From ios: `bash Checks/run-vehicle-sync-checks.sh` and `bash Checks/run-vehicle-queue-checks.sh`.
Wire/SQLite checks: `python -B ios/Checks/test-return-recovery.py` from repository root.

Physical-device checks remain required: offline explicit invocation, expiry requiring
new invocation, process termination during upload, lost response retry, subsequent
queued pairs, actual App Intent/background execution and user-visible terminal state.
No claim of TestFlight/Production E2E is made by local tests.
