# Internal bounded Vehicle Identity admission (MC-SEC-001)

No native HTTP adapter is enabled. Legacy CarPlay and device enrollment are
unchanged. This document describes internal code, not production activation.

## Transaction and time policy

Identity fence -> family advisory -> family row -> owned device -> vehicle.
Exact receipts and conflicts precede time-sensitive revalidation. PostgreSQL
time supplies a 72-hour rolling target; a later deletion boundary always wins.
Expected-sequence events at/before this effective cutoff receive the existing
terminal `before_finalized_boundary` receipt, including when a rolling checkpoint
has not yet been installed. This never permits replay behind a stored boundary.
Future skew remains at most five minutes. Terminal receipts advance sequence;
transient database/timeout failures roll back and do not advance it.

Rolling advancement loads only bounded old-generation seeds and sessions starting
between the old and proposed boundaries (initialization has a bounded first
page). Crossing means start <= boundary and end absent or > boundary, NOT merely
currently active. Markers and family metadata advance atomically. On checkpoint
overflow no partial boundary is installed; admission returns the durable policy
receipt. There is no automatic/unbounded maintenance queue. The internal
`maintain_native_checkpoint` performs one explicitly requested bounded recovery
unit. It can install a complete earlier boundary before an overflowing timestamp
group; a later unit can continue. It never splits a group, widens admission's
72-hour cutoff, consumes sequence or changes occupancy. Excessive carry state or
a timestamp group too large to progress returns policy_exceeded without looping;
that exceptional case needs operator review, not an unbounded bypass.

The fast path requires a timestamp strictly after the family's latest accepted
event and the effective boundary. It runs the existing pure transition engine
on at most two affected sessions, updating endings and inserting only required
new sessions. An already-ended causal RETURN leaves occupancy alone. Equal/late
events replay the bounded suffix. Pre-boundary causes are fetched by requested
UUID only; old redundant aliases retain their projection anchor. Long trips are
never closed for age. No old evidence/history is deleted by rolling maintenance.

Late materialization retains unchanged rows. Changed rows use preflighted bounded
replacement to satisfy immediate active indexes and overlap constraints, keeping
existing public refs/creation metadata where their logical identity survives.
Seed pre-boundary fields remain unchanged. Receipt, sequence, checkpoint and
projection share a transaction; policy refusal rolls the planning savepoint back
before persisting only the terminal receipt.

## Conservative defaults (`vehicle_work.py`)

These are safety ceilings, not measured production capacity or a product promise.
Adjust only after adversarial/load testing. Counts accumulate for the operation;
seed/checkpoint processing can charge more than one dimension for the same row.

| Dimension | Default | Enforcement |
|---|---:|---|
| Accepted replay events including candidate | 512 | Indexed limit remaining+1 |
| Seeds processed | 128 | Checkpoint, seed loader, small fast-path seed |
| Mutable sessions | 512 | Indexed suffix page plus seeds |
| Distinct historical causes | 128 | Bounded suffix UUID set, point resolution |
| Planned session inserts | 512 | Complete materialization plan before writes |
| Session updates/marker updates | 512 | Checkpoint and materialization plan |
| Session deletes | 512 | Changed-row replacement set |
| Association operations | 512 | Complete bounded effects plan |
| Checkpoint candidates | 512 | Old seeds + indexed new starts, limit+1 |
| Planning/materialization SQL operations | 2048 | Budgeted queries and reserved writes |
| Aggregate charged units | 4096 | Every budget charge |

Authentication, fixed point lookups, receipt/sequence and transaction setup are
constant-size overhead outside the SQL planning budget. Limits prevent unbounded
collections; they do not make PostgreSQL cost strictly constant. Indexed access,
finite timeouts and query-plan validation remain necessary.

Transaction-local lock timeout: at most 1000ms; statement timeout: at most 2000ms
(a stricter caller setting is preserved). A five-second
monotonic admission deadline is checked between SQL operations and before success.
An in-flight statement is bounded by the statement timeout; these are not a
promise about OS/network failure or transaction commit/rollback latency. Settings
are restored on success and rolled back on failure, including caller-owned outer
transactions. No unrelated pool/global timeouts are changed.

## Operator-only partial-index migration

File: `supabase/manual_migrations/2026092301_vehicle_events_accepted_device_index.sql`.
Execute its exact complete contents as postgres BEFORE the matching backend.
It is prepared, not executed in production. Only a partial index is introduced.

Read-only preflight (run manually):

```sql
SELECT current_user = 'postgres' AS correct_role,
       to_regclass('public.vehicle_events') IS NOT NULL AS table_exists,
       to_regclass('public.vehicle_events_device_accepted_sequence_idx') IS NULL AS index_absent;
SELECT attname, format_type(atttypid, atttypmod) AS data_type
FROM pg_attribute
WHERE attrelid = to_regclass('public.vehicle_events')
  AND attname IN ('device_id','device_sequence','admission_outcome')
  AND NOT attisdropped
ORDER BY attname;
```

Expected: true/true/true; admission_outcome=text, device_id=integer,
device_sequence=bigint. The migration repeats strict checks transactionally.
Success ends with COMMIT and creates just one index; rerun/conflict fails closed.

Read-only verification (run manually):

```sql
SELECT i.indisvalid, i.indisready, i.indisunique,
       i.indrelid = 'public.vehicle_events'::regclass AS correct_table,
       pg_get_indexdef(i.indexrelid) AS definition,
       pg_get_expr(i.indpred, i.indrelid) AS predicate
FROM pg_index i
WHERE i.indexrelid = to_regclass('public.vehicle_events_device_accepted_sequence_idx');
```

Expected exactly one row: valid=true, ready=true, unique=false, correct_table=true;
btree keys `(device_id, device_sequence)` and predicate
`(admission_outcome = 'accepted'::text)`. No other schema/ACL changes.

Old backend is compatible. No mandatory application downtime, but this ordinary
transactional index build blocks writes to vehicle_events while building: use a
controlled quiet window, pause any internal event writer if necessary, and retry
after rollback if the migration's 5s lock / 60s statement limit is exceeded.

## Remaining public-activation gates

Production-like load/adversarial validation and native request/rate/concurrency
controls remain necessary. Bounded single operations do not bound aggregate load
or receipt storage. Device enrollment (MC-SEC-002) and legacy authority cutover
(MC-SEC-003) are separate, unchanged gates. Hot/Warm/Cold is future history-query
policy only; no History API/UI changes or physical archival occur in this slice.
