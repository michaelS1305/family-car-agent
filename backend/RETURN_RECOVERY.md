# RETURN recovery — Phase 1

Local implementation; migration `2026112201_return_recovery.sql` is NOT applied.
Deploy only after separately authorized migration application. No iOS behavior
changes in this phase. Existing RETURN response/error shapes remain unchanged.

## API

Authenticated `POST /api/devices/{device_ref}/events/return/{event_id}/recovery`:

```json
{
  "recovery_id": "00000000-0000-4000-8000-000000000004",
  "original_return": {
    "event_id": "00000000-0000-4000-8000-000000000002",
    "vehicle_ref": "00000000-0000-4000-8000-000000000003",
    "device_sequence": 2,
    "take_event_id": "00000000-0000-4000-8000-000000000001",
    "occurred_at": "2026-11-22T14:30:00Z",
    "location_at": "2026-11-22T14:30:00Z",
    "latitude": 32.0,
    "longitude": 34.0,
    "accuracy_m": 10.0
  },
  "verification": {
    "invoked_at": "2026-11-22T14:40:00Z",
    "location_at": "2026-11-22T14:40:00Z",
    "latitude": 32.1,
    "longitude": 34.1,
    "accuracy_m": 10.0
  }
}
```

Coordinates above are illustrative, not evidence of a valid home location.
All times must include a timezone. Unknown fields are rejected. Location accuracy
must be positive and <=100m, matching the original API. The server requires:

- `0 <= invoked_at - location_at <= 30 seconds`;
- `0 <= server_now - invoked_at <= 120 seconds` (no future-clock tolerance);
- invocation no earlier than the historical RETURN;
- current home distance + accuracy <=500m.

First successful response (HTTP 200), also returned unchanged on identical retries:

```json
{
  "kind": "accepted",
  "admission_outcome": "accepted",
  "recovery_outcome": "recovered",
  "event_id": "00000000-0000-4000-8000-000000000002",
  "recovery_id": "00000000-0000-4000-8000-000000000004",
  "verified_at": "2026-11-22T14:40:00.000000+00:00"
}
```

Refusals use the existing `detail: {code, message}` HTTP error shape:

| Code | Meaning |
| --- | --- |
| RETURN_RECOVERY_LEGACY_UNVERIFIED | No matching server-owned candidate; do not infer a historical reason |
| RETURN_RECOVERY_EVIDENCE_MISMATCH | Original event/evidence differs from the recorded candidate |
| RETURN_RECOVERY_NOT_ELIGIBLE | Missing accepted TAKE, unavailable binding/vehicle, noneligible candidate or already admitted event under a different recovery attempt |
| RETURN_RECOVERY_IDEMPOTENCY_CONFLICT | Changed payload under the same event/recovery ID pair |
| RETURN_RECOVERY_VERIFICATION_EXPIRED | Invalid measurement/invocation/delivery timing |
| RETURN_RECOVERY_ORDER_CONFLICT | Existing admission refused; no sequence, receipt, checkpoint or projection changes retained |
| RETURN_HOME_UNAVAILABLE / RETURN_OUTSIDE_HOME | Fresh verification failed the unchanged home rule |

These are HTTP 409. Existing authentication/authorization and Pydantic HTTP 422
validation continue to apply. Dependency timeouts remain the existing 503 behavior.

## Transactions, evidence and retention

Normal HTTP RETURN records a candidate only on the two home rejection codes and
with an accepted same-owner/family/vehicle TAKE at or before the RETURN time.
The transaction returns a refusal VALUE; `device_api.run` raises the HTTP error
only after the pool commits. Commit failure never masquerades as a saved rejection.

The first candidate wins (event UUID and device/sequence uniqueness). Its original
envelope/GPS and SHA-256 canonical fingerprint are immutable. New verification
GPS is used transiently; attempts retain only its payload fingerprint, times and
result. Fingerprints are protocol integrity checks, not location anonymization.

Recovery uses the existing identity fence, family advisory/row lock, device and
vehicle locks. Same-candidate attempts serialize across API processes using these
PostgreSQL locks. `(event_id, recovery_id)` is the idempotency scope. Ownership is
checked before returning stored outcomes; revoked devices cannot retrieve them.

Event admission and result insertion share the outer transaction. A failed result
write rolls back admission. A nonaccepted admission rolls back its savepoint,
including terminal receipts/sequence advancement; only the refused attempt remains.
No retry, skip or chronology repair is introduced. A different recovery ID after a
successful admission is refused; the original stable ID retrieves the committed
outcome even after expiry. A changed payload requires a NEW ID on a new explicit
user invocation, never on an uncertain-delivery retry.

TAKE 14:22 -> RETURN 14:30 -> queued TAKE 14:35 -> verification 14:40 therefore
admits the RETURN at 14:30, subject to normal reconciliation/checkpoint/72h rules.
The subsequent TAKE remains untouched and can sync in sequence. If admission
cannot reconcile chronology, the RETURN stays blocked with ORDER_CONFLICT; automatic
queue skipping is not permitted. The product path for that separate conflict still
requires owner review.

Both new tables are backend-only, with RLS and no browser policies. Immutable update
guards are separate from `vehicle_events`' existing trigger. Existing account
cleanup deletes the causal TAKE and cascades candidate -> attempts; user, vehicle,
device and family deletion also cascade. No separate TTL deletes idempotency proof:
records follow the causal vehicle event's retention lifetime. Raw ORIGINAL rejected
GPS is new retained personal data and follows that same account cleanup.

## Legacy stop / Phase 2 iOS

Historical `preAdmissionRejection` alone is insufficient. No automatic backfill or
privileged candidate-creation API exists. Individual migration would require trusted
server evidence of the exact original immutable request, authenticated ownership,
the specific home failure and lack of admission, followed by separately approved
administrative verification. Existing vehicle receipts alone do not retain rejected
GPS/rejection reasons. Missing proof returns LEGACY_UNVERIFIED.

Phase 2 must preserve structured rejection codes; persist the original RETURN;
capture a fresh measurement only on explicit eligible RETURN invocation; persist
a separate recovery ID and immutable verification request BEFORE upload; drain or
resolve any original in-flight upload; retry an uncertain recovery with EXACTLY
the same payload/ID across restart; never replay old GPS as fresh evidence. Resume
the queue only on committed `recovered`; keep rejected/uncertain work diagnosable.
Do not increase device sequence for this operation or rewrite queued events.

## Validation limits

Unit/API tests use mocks only. Transaction interruption and concurrent calls are
tested against a transactional mock, not PostgreSQL. Migration execution, real
cross-connection locks/FKs/RLS, physical iPhone and Production E2E are NOT verified.
Before activation, separately authorize a disposable PostgreSQL migration + real
concurrency/rollback/cascade test run. No external service is needed for that test.
