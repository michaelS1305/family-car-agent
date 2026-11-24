# TAKE session metadata — Current Snapshot policy

POST /api/devices/{device_ref}/take-session-metadata is an authenticated read-only
snapshot. Request: request_id UUID4 and 1..64 unique takes (event_id UUID4,
device_sequence positive Int64, vehicle_ref UUID). Admission replies are unchanged.
The response echoes request/device identities, projection_revision, server
last_processed_sequence, observed_at and one item per reference. A scoped accepted
TAKE includes anchor_event_id, session_ref, session_state, closed_at, closure_kind,
reconciliation_operation_id and finality. Missing, foreign, unbound, retired or
mismatched events yield unavailable, never closure. Revoked/foreign devices fail.
No coordinates, names, authentication material or other users' sessions are returned.

The family lock and identity gate match admission/account deletion. The endpoint
never admits events, advances checkpoints or creates receipts. PostgreSQL triggers
atomically increment the new family revision for session/event/alias mutations,
resolution insert/delete, and checkpoint changes, including existing older writers.
Binding insertion/removal and vehicle retirement also advance the revision.
Revision increments may exceed one per transaction; only monotonic ordering matters.
A rolled-back mutation rolls back its increments. Family UUID/context identity must
never be replaced by the revision alone. Migration functions are not public RPCs.
Finalized means both TAKE occurrence and session closure are within the stored
checkpoint. Other closed snapshots are explicitly provisional.

SQLite v5 adds two separate cache tables. Original evidence, links, statuses and
upload payloads remain unchanged. Accepted TAKEs alone may use a matching cached
closure. Pending/blocked/uncertain events remain protected. Accepted open aliases
are grouped by anchor; RETURN keeps a valid original local TAKE cause. A local
non-terminal RETURN pairs earlier accepted aliases of that same verified anchor,
never a later or pending TAKE, without changing any stored causal link. Missing or
known-stale provisional metadata does not suppress a TAKE. A higher received family
revision invalidates older provisional items even when they are outside that batch.
Within an equal revision, server observed_at orders snapshots (never the phone
clock). SQLite persists that timestamp and compares/writes under BEGIN IMMEDIATE
across independent processes. Older observations are rejected; exact timestamp ties
are accepted only as identical item retries, otherwise fail closed. A server clock
regression cannot revive an invalidated item; availability mutations independently
advance revision. Early unreleased v5 caches lacking ordering are discarded during
cache schema upgrade, without changing events, tasks or acknowledgments.
Authorization-generation fencing prevents delayed replies from a previous scope
being applied. New local events created during refresh are never touched.

Existing wake paths (app restoration, connectivity, admission and reconciliation)
launch a separate asynchronous metadata task. Shortcut eligibility is SQLite-only;
it never awaits metadata. Requests prioritize accepted unpaired TAKEs without a current closed snapshot,
then rotate by least-recent refresh. Each pass sends at most four batches of 64
distinct references; a visited set prevents repeated requests in the same pass. Failures retain cache/evidence; the next wake retries. Background
URLSession event uploads are unchanged. Metadata refresh itself is foreground
URLSession and may be interrupted by iOS suspension; the next activation backfills.

APPROVED LIMITATION: offline devices cannot discover unknown server revisions.
A provisional closed cache can be older than a new server replay. Until refresh,
local eligibility uses the last verified snapshot; the server remains authoritative
when queued events are admitted. This is not a guarantee of real-time availability.
A known newer revision is never ignored. No synthetic RETURN or queue reset is used.

Deployment (separate owner approval): apply additive
2026112401_take_session_metadata.sql after the reconciliation migration, then deploy
the compatible Backend endpoint, then iOS. No live changes were made. Older clients
ignore the endpoint and keep existing behavior. Unavailable endpoint/cache safely
retains the old conservative TAKE behavior. Do not remove the revision column while
new Backend readers are deployed. Physical-device suspension/connectivity verification
and Xcode CI remain required before release; local Linux Swift is not an iOS build.

Focused review corrections verified locally (2026-11-24): 216 Backend checks passed,
including real PostgreSQL 17 metadata, availability revision, concurrency and existing
admission/Recovery/Reconciliation/account-deletion regressions. Seven Python iOS
contract checks passed. Swift synchronization checks cover 24 groups, including
>64-history blocker priority, four-batch distinct continuation, same-revision ordering,
independent SQLite connections racing, restart after unavailable, and independent
shipping-v4 DDL with all original records compared before/after two reopenings.
This is not a physical app/Shortcut multi-process or Xcode verification claim.
