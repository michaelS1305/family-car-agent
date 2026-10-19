# Native Push backend P3–P7

Disabled by default. Local tests are not evidence of real FCM delivery or
production readiness. P2 is verified in Dev only; do not enable this in Prod
before separate schema, privileges, credentials and client review.

## Configuration (names only)

- `NATIVE_PUSH_ENABLED`: opt in explicitly; otherwise no producer, worker or registration.
- `NATIVE_PUSH_PROJECT`: exact environment Firebase project.
- `NATIVE_PUSH_CREDENTIALS_FILE`: absolute service-account JSON path, mounted externally.
- `NATIVE_PUSH_KEY_ID`: non-secret identifier for the encryption/key cohort.
- `NATIVE_PUSH_ENCRYPTION_KEY`: base64 encoding of a cryptographically random 32-byte AES key.
- `NATIVE_PUSH_FINGERPRINT_KEY`: separate, independently generated 32-byte base64 HMAC key.

No credentials belong in this repository. All instances serving an environment
must use identical project/key configuration. Do not change keys in place or
reuse a key identifier for different material. This version supports one key
cohort: revoke existing installations before changing keys and re-register.
Registration detects active-cohort drift and fails closed. A future seamless
key rotation/key ring is not implemented. Preserve old keys until revocation is
complete; do not silently discard ciphertext or fingerprint uniqueness.

Credentials are loaded only by the enabled runtime provider, never by tests.
Project/type/token-endpoint checks precede signing; OAuth uses the Firebase
Messaging scope, a one-hour RS256 assertion and a cached short-lived token.
Requests have 3-second connection and 5-second read timeouts, no redirects,
implicit HTTP retries or environment proxy inheritance. No Firebase SDK added.

## Authenticated API

All paths below are under `/api/native-push`, Bearer-authenticated through the
existing `get_current_user`. Owner/family IDs cannot be supplied. Responses are
`Cache-Control: no-store`. Invalid bodies are sanitized by the application's
validation handler; tokens/nonces are never reflected. Configuration failure is
503 `NATIVE_PUSH_UNAVAILABLE`; invalid body is 422 `INVALID_NATIVE_PUSH_REQUEST`.

### POST /registrations

Body: `installation_ref` (UUID4), `request_id` (UUID4 idempotency key),
`platform` (`android` or `ios`), `token` (20–4096 restricted ASCII characters).
Project is server configured, not a request field.

202 body uses `code`:
- `CHALLENGE_PENDING`, with `challenge_ref`, `expected_generation`, `expires_at`.
- `CHALLENGE_EXISTS`, with existing `challenge_ref` and `status` for an idempotent request.
- `REGISTRATION_UNAVAILABLE`, `RATE_LIMITED`, or `INSTALLATION_LIMIT` for refusal.

Clients must inspect `code`, not interpret 202 as activation. No nonce is
returned over this API. The worker sends a random 256-bit nonce to the candidate
FCM token; lifetime is two minutes. Duplicate request IDs cannot retarget a
challenge. A new request cancels and erases the previous pending challenge.
Limits: 20 lifetime installation references per owner, five pending challenges,
ten new challenges per ten minutes, five confirmation guesses, three send
attempts. Terminal rows preserve rate/idempotency evidence. Reuse an owned
installation reference rather than creating unbounded references on reinstall.

### POST /installations/{installation_ref}/confirm

Body: `challenge_ref` (UUID4), `nonce` (43 base64url characters).
200 `ACTIVE` with `generation`, or `REGISTRATION_UNAVAILABLE`.
Constant-time nonce verification, live identity/family checks, owner locks,
installation locks and a fingerprint activation lock guard the transition.
An active token is never transferred to another installation/account implicitly.
Only successful proof activates the token. This proves token receipt/control,
**not physical-device identity**. Success increments generation and erases all
challenge material. An already consumed challenge only returns current activation
status if its activated generation is still current; it never reactivates.

### POST /installations/{installation_ref}/revoke

Body: `expected_generation` (positive integer).
200 `REVOKED` if the current owned generation was revoked; otherwise
`REGISTRATION_UNAVAILABLE` (also for absent/foreign/stale references).
Revocation increments generation, erases token material and cancels pending
challenges. A delayed logout cannot revoke a newer generation. Account switch
must revoke under the old authenticated owner, then register a new reference
under the new owner. The backend does not infer a transfer from a shared token.

## Vehicle producer and the approved loss tradeoff

Only newly admitted **fast** `opened` and `returned` effects enter the producer.
It rereads the persisted accepted source event, excludes future/expired sources,
sets expiry to source `occurred_at + 5 minutes`, excludes the actor and snapshots
active installations of current family members. A unique source/type key prevents
duplicate outbox records. Replay/reconciliation never calls this as eligible work.

The existing vehicle transaction owns commit. A nested PostgreSQL SAVEPOINT
contains event and delivery inserts together. Recoverable statement-local
data/integrity, missing optional push objects/privileges and lock/statement-timeout
errors roll back only that savepoint. Recovery is accepted only with an open
connection still INTRANS. Serialization/deadlock/connection errors, failed
savepoint recovery, business errors, deadline exceptions and outer COMMIT errors
propagate normally. No change to vehicle receipts, sequence or projection logic.

**An isolated outbox failure may permanently lose the notification.** The event
is not backfilled by retry or reconciliation. This intentionally prioritizes
vehicle availability; it is not guaranteed delivery. A structured error records
only the operation, SQLSTATE and notification-loss flag, not SQL exception text,
tokens, nonces or notification content.

Companion's `device_api.run` and CarPlay's `apply_carplay_transition` enclose the
pool commit with `commit_boundary`. A wakeup is issued only for successful outbox
work after the connection context commits. Outer failures discard the signal.
Other internal callers can omit the hint: committed work is recovered by polling.
Do not enclose these ingress helpers in a new hidden outer transaction.

## Dispatcher

Composes with (does not replace) the account-deletion lifespan. One serial worker
per process; at most one challenge and one delivery per pass, one connection at a
time, five-second idle interval or earlier post-commit hint. Recovery updates are
bounded to 100 rows each; statements/locks are bounded. No startup backlog drain.
Each pass runs in a fresh supervised Python interpreter (no forked/shared DB
connections), using `sys.executable -B -m native_push_process --run-pass` with
closed inherited file descriptors and no shell. The child alone opens direct
psycopg connections (3s connect, 3s statement, 1s lock timeouts), OAuth and FCM.
A monotonic 20s parent deadline covers startup, database work, BOTH provider
operations, finalization and cleanup. Including the 2s termination/reaping budget,
this remains below the 30s lease (8s margin for a lease acquired at pass start).
There is no unbounded
pool acquisition or executor-thread shutdown. OAuth cache is per pass, not shared.
Shutdown signals the supervisor immediately; it terminates the child, waits at
most 1s, escalates to kill and waits at most 1s. Failure to confirm exit quarantines
the supervisor: no replacement process/send is permitted. A child-local 20s
watchdog also exits the child if its parent dies. OS process creation/kill and
scheduling must work normally; a failed kill is an operational incident, not a
claim that the process stopped. Never retry a possibly submitted send: expired
delivery leases become terminal uncertain; expired challenge leases remain
confirmable until expiry but are not resent. Challenge wire/proof protocol is
unchanged. Child output/exception text is suppressed; parent reports only fixed
complete/failure/uncertain/quarantine outcomes.

Render/Python subprocess permission, available memory/process limits and the
platform termination grace period require deployment verification. Repository
README documents FastAPI on Render and uvicorn, but no pinned Render runtime
manifest was found. Local subprocess tests are not Render verification. No new
service/dependency is required. Render sleep/restart can
exhaust the source TTL; wakeups do not wake a sleeping Render service.

PostgreSQL `FOR UPDATE SKIP LOCKED` claims and UUID leases coordinate processes.
Leases last 30 seconds. Membership, live auth/deletion state, actor exclusion,
installation status/generation, project and expiry are checked immediately before
send and generation/membership again before recording completion. Provider calls
are outside all DB transactions. No locked database transaction waits for FCM.

Explicit 429/500/503 responses permit bounded exponential backoff, respecting
Retry-After and the original expiry. At most four notification send attempts.
FCM gets only remaining TTL (and original APNs expiry). Transport ambiguity or a
crashed delivery lease is terminal `transport_uncertain`, never blindly replayed.
Challenge retries are bounded and contain the same challenge, not a visible
business notification. Invalid-token responses invalidate only the matching
current installation generation. FCM `accepted` is not phone delivery.

### NP-01: opaque business refresh protocol

Business-event FCM application data is exactly:

```json
{"kind":"refresh","version":"1"}
```

No event/type/reference, vehicle, family, user, installation, generation or
timestamp is included in that data. It contains no credential or authorization
capability. The FCM routing token and provider TTL/APNs expiration remain in the
transport envelope, not application data; original-event expiry is still enforced.
The separate registration challenge protocol above is unchanged: its short-lived
one-time nonce proves token control and is not a reusable detail-access credential.

Intended future client flow (not implemented or device-verified here):

1. Treat a supported refresh hint only as a request to refresh, never as a
   notification body or evidence that a particular event occurred.
2. If signed out or locally revoked, discard it. Use only the current account's
   Bearer session, never a saved previous owner's credentials. Capture local
   account/family/installation generation and discard any fetch result if that
   identity changes before display. Account switching still requires old-owner
   revoke and a new installation reference.
3. Fetch the installation-bound events endpoint below. Display details only from
   its freshly authorized result, never infer a take/return from the hint alone.
4. On denied, unavailable or failed fetch, do not display event details from old
   caches or fabricate a notification. Normal foreground refresh remains possible.
5. Coalesce hints and deduplicate fetched event_ref by account/installation;
   discard fetched items past expires_at. No event ID/expiry is in the push itself.
   Each independent refresh starts at page one, including after restart or
   connectivity restoration. Persisting display deduplication and stable local
   notification IDs is future client work, not exactly-once display assurance.

### Installation-bound event fetch (implemented)

`GET /api/native-push/installations/{installation_ref}/events`

Bearer authentication and `expected_generation` (positive integer) are required.
Optional `limit` defaults to 20 (1..50); `cursor` is a previously returned public
event_ref. Returns `items`, `has_more`, `next_cursor` with `Cache-Control: no-store`.
Each item has only `event_ref`, `type`, `occurred_at`, `expires_at`, `actor_name`,
`vehicle_ref`, `vehicle_name`. Names are current authorized names, not snapshots.
No internal IDs, tokens or provider diagnostics are returned.

One transaction revalidates live identity/deletion, current family and owned
active installation/project/generation. Identity -> family -> user/installation
locking coordinates deletion/revocation. The recipient delivery must match that
installation/owner/generation; actor must be live, non-deleting and in the same
family; vehicle must belong to that family. Actor cannot be recipient. Only
pending/complete events with expires_at strictly greater than database time are
returned. FCM delivery status is deliberately not an authorization condition.
Foreign/missing/revoked/stale installations share NATIVE_PUSH_ACCESS_DENIED (403).
Existing missing/deleting identity errors remain unchanged.

Order is `(occurred_at DESC,event_ref DESC)`. Cursor lookup uses the same scope
and expiry predicates; foreign/missing/expired cursors return the same sanitized
INVALID_NATIVE_PUSH_CURSOR (422). Restart at page one after this error. Cursors
are page continuations, not durable watermarks or snapshots. Repeated first-page
fetching recovers late commits/out-of-order events while eligible. No read ACKs.
Multiple devices have independent recipient records; new installations and new
generations do not inherit old-generation events. Five-minute eligibility is
unchanged; seven-day operational retention does not extend notification access.

Normal vehicle/history APIs remain unchanged:

- `/api/car/history` exposes authenticated family-scoped active/recent sessions
  with session_ref, names and start/end times, but is not an exact notification
  event inbox. Its service passes the authentication-time family snapshot to a
  separate database read; unlike `/api/vehicles`, it does not repeat live identity
  validation inside that read. It is not designated as the strict refresh path.
- Revoking a push installation does not revoke its owner's Bearer session.
  Normal vehicle APIs still authorize accounts. The new events endpoint additionally
  requires the owned active installation/generation and denies revoked references.

An authorization change can still race a submitted FCM request. The remaining
in-flight message contains only the fixed hint, not event details. Delivery timing
can still reveal that a refresh was requested; it is not an anonymity guarantee.
Every subsequent detail read must independently authorize the current account.
Data-only FCM does NOT guarantee delivery, background execution or notification
display on Android or iOS. Background restrictions/APNs setup and meaningful
notification display after a secure fetch require separately approved device QA.

### Seven-day retention and security exceptions (implemented)

Cleanup runs incrementally after each successful pass. NATIVE_PUSH_CLEANUP_BATCH
defaults to 50 and clamps to 1..100 per statement. SKIP LOCKED, 250ms lock and 2s
statement limits avoid waiting unnecessarily on admission/dispatch. Expired
pending challenges without a live lease have secrets erased. Expired delivery
leases become uncertain; expired queued work becomes terminal. Terminal deliveries
are deleted only seven days after the later of updated_at and event expiry.
Events are deleted only seven days after expiry AND once no deliveries remain;
deleting children first avoids an unbounded FK cascade. Event schema has no
terminal timestamp, so expiry is the approved retention anchor for empty events.
No active lease is deleted. Cleanup is automatic only while enabled and running;
sleep, backlog, provider stalls or shutdown can delay it. It is not a wall-clock
erasure SLA and does not extend fetch eligibility.

Security exceptions: terminal challenge metadata stays indefinitely while its
account exists because `(user_id,request_id)` prevents replay indefinitely today;
deleting it at seven days would silently weaken that guarantee. Its secret fields
are erased. Active installations/tokens and revoked/invalid/pending installation
ownership/generation tombstones are never deleted by cleanup, preserving lifetime
quotas and preventing ownership reuse. Existing account/source-event FK cascades
still apply. Key-ring rotation and throughput tuning remain separate work.

## Operator review before Dev activation

1. Keep the feature disabled until local tests and this protocol are reviewed.
2. Verify P2 applied only to the intended environment; no application migration.
3. Provision separate random encryption/fingerprint keys externally and configure
   the exact Dev project and service-account file; least-privilege FCM IAM.
4. Review data-only client handling and account-switch/revoke requirements before
   enabling end-to-end UI delivery. iOS APNs setup remains a separate task.
5. In a separately approved live test, verify challenge receipt, activation,
   rotation/revocation, TTL, error telemetry and Render restart recovery.
6. Prod requires separate schema/role/Firebase verification and explicit approval.

No live FCM/Render/Supabase calls, credential inspection or application deployment
are performed by this implementation's validation.
