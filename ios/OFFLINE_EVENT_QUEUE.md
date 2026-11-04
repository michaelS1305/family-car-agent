# Durable native vehicle queue — Phase 2

The queue itself is storage only. Phase 3 adds a separate, inactive-by-default
coordinator (see below). `VehicleEventQueue.applicationDirectory()` is
the Application Support location reserved for integration.

## Identity and creation

`VehicleQueueContext(environment:identity:device:)` consumes the existing
`AppEnvironment` and `ChatIdentity`, plus a server-registered device UUID. Its
durable key includes Backend/Supabase environment, auth owner, internal user,
family and device. Session generation/version are intentionally not persisted.
Production remains disabled by the existing AppEnvironment; adding a Production
environment later must supply its own authoritative environment URLs.

`initializeFreshDevice` is ONLY for a registration with a known zero server
cursor. It is idempotent for an existing exact partition, but cannot reset a
sequence or reactivate a suspended partition. One environment/device cannot be
reassigned to another user/family. Loss of the database, reinstall or an existing
server device with unknown cursor requires explicit future recovery, not calling
this API to assume zero. No server cursor reconciliation exists in Phase 2.

`suspend` freezes a partition on logout/account/family change; `reactivate`
requires the exact context and an independently authorized integration decision.
Neither changes authentication. No lifecycle call is wired yet. A future caller
must also fence stale session generations and cancel/reconcile system tasks;
freezing this database does not cancel a request already sent to a server.
New registration uses a separate device partition. Old records are retained.

## SQLite and transactions

Schema version 1 uses two tables:

- `devices`: context primary key, environment/device unique pair,
  `last_sequence`, `active`.
- `events`: globally unique event UUID, context foreign key, sequence, vehicle,
  causal TAKE foreign key, immutable Codable payload, state, attempt UUID,
  session/task identifiers and fixed diagnostic reason.

Unique `(context,sequence)` prevents repeated numbers. Unique `(context,cause)`
allows one RETURN per TAKE. A RETURN must explicitly reference a local TAKE in
the same context and vehicle, no later than the RETURN. There is no last-car
heuristic. Multiple vehicles share the device counter.

Every mutation uses `BEGIN IMMEDIATE` / `COMMIT`, rolling back on any error.
Sequence increment, event insert and causal link are one transaction. Separate
actors/connections serialize through SQLite, not only through a Swift actor.
Foreign keys, FULL synchronous durability and DELETE rollback journal are used.
An unknown schema version fails closed; no destructive reset is implemented.

Original Date instants (timezone-independent) and location evidence are immutable.
Missing RETURN evidence is retained as `blocked/missing_location`; it cannot be
sent or repaired with a later position. Invalid supplied evidence is rejected
before allocating a number. Recovery of such a blocked head is deliberately
unimplemented pending the admission recovery decision, rather than skipping it.

## State API

- `enqueueTake`, `enqueueReturn`: pending (or blocked for absent RETURN location).
  Reusing an event UUID with exactly identical contents returns the same event;
  changed contents or a second RETURN cause fail without consuming a sequence.
- `prepareNext`: atomically claims the oldest unresolved pending event and creates
  an attempt UUID. It refuses another in-flight head. RETURN requires an accepted
  causal TAKE; a terminally rejected TAKE blocks its RETURN.
- `markRegistered`: preparing → registered, retaining system session/task identity.
- `recordFailure`: preparing/registered → awaitingAuthentication or blocked.
  Pre-admission rejection never advances the queue.
- `retryAfterTaskReconciliation`: unresolved attempt → pending, only after the
  future coordinator establishes that no system task can still send. Keeps event
  UUID, sequence, timestamp and cause. It cannot unblock a business rejection.
- `applyAdmission`: consumes an explicit validated Backend AdmissionResult.
  `accepted/accepted` or `retry/accepted` resolves accepted; known terminal
  outcomes with `terminal` or `retry` resolve terminal. Gap/conflict/unavailable/
  malformed/future-clock results block. Unknown outcomes fail closed.
  HTTP status and transition text alone cannot resolve an event. Acceptance is
  admission of evidence, not proof that the vehicle currently has that state.
- `records`: recovery snapshot; does not automatically reset preparing/registered
  records. Session/task identifiers and attempts survive restart.

The future adapter must associate each receipt with the exact context/event/
attempt and authenticate it. This local method is not cryptographic attestation.
Old-attempt callbacks and mutations of frozen contexts are rejected.

## Recovery, security and limits

The directory and database use iOS complete-until-first-user-authentication file
protection. SQLite journals inherit the protected parent directory. The directory
is excluded from backup; no credentials are stored or logged. Access before first
unlock may fail and must not trigger a reset. Device file protection/backup
behavior still requires physical-iPhone verification.

After a crash, reconnect the future URLSession, reconcile `getAllTasks()` against
`records`, then explicitly retry unknown outcomes with the original event. No
network coordinator is included. SQLite cannot atomically commit with URLSession
task creation; preparing/registered and attempt fencing expose that gap safely.
No guaranteed delivery, retry timer, deletion/retention policy or sequence-skipping
API exists. Disk errors fail closed. Corruption is not silently discarded.

## Local checks

Run `bash ios/Checks/run-vehicle-queue-checks.sh`. Linux requires SQLite development
headers (`SQLITE_INCLUDE_DIR` override) and libsqlite3.so.0; Apple SDKs provide
SQLite3. Tests use temporary databases only, including separate-process abrupt
exit during an uncommitted create/registration, SQL abort rollback, reopening,
concurrent writers, causal and identity isolation, admission and retry fencing.
The existing CI workflows are unchanged; this standalone check is not wired into
GitHub Actions in this phase.

## Phase 3 — ordered background coordinator

`VehicleSyncCoordinator` uses the existing queue states and transactions. The only
queue API addition is `validateActiveContext`, used before scheduling or resuming.
No SQLite schema migration is needed. A MainActor FIFO serializes wakeups and
callbacks across suspension points; a background transport permits only one live
session owner per identifier in this process. This is an app-target design, not
a multi-process extension coordinator.

The coordinator's stable session identifier includes the application environment,
auth owner, internal user, family and registered device. Supply one retained
coordinator/transport pair per context. Its upload directory is partitioned by that
identifier, excluded from backup and protected until first unlock on iOS.
Only immutable JSON event bodies and retry-not-before dates are written there.
Tokens/headers are never written to SQLite or these files. URLSession itself must
retain the authenticated request to perform a scheduled background upload.

Scheduling order is: reconcile `allTasks` → obtain current authorization → claim
queue head → persist deterministic payload → create suspended file upload → persist
session/task/attempt mapping → recheck identity → resume. RETURN eligibility remains
the queue's responsibility. Existing payload bytes are compared on retry; a changed
encoding fails closed rather than replacing a previously submitted body.

Response disposition:

- accepted/accepted and retry/accepted acknowledge admission.
- terminal or retry with a known terminal outcome resolves terminal rejection.
- gap, conflict, unavailable, malformed and future_clock_skew block progression.
- 401 retains the event awaiting authentication and initiates bounded recovery (Phase 4 below).
- Network failure, absent/invalid/unknown response, 429 and 5xx preserve the event
  as delivery unknown. Retry-After (seconds or HTTP date) is persisted, with a
  minimum 60-second cooldown. `wake()` never retries before that deadline.
- Other non-2xx responses block as pre-admission rejection; no skip/renumber API.

Only after a validated disposition is durably stored does the completion handler
try scheduling the next head. Duplicate/old callbacks are ignored by exact
event/attempt/session/task mapping. Task identifiers alone are not unique history.
No HTTP status alone establishes vehicle admission or current occupancy.

### Restoration and lifecycle boundary

The iOS delegate transport uses background URLSession, file-backed uploads,
cellular/expensive/constrained access and system launch events. It buffers bounded
response bodies, then serially awaits coordinator processing before invoking the
UIKit background completion handler. Callbacks arriving before handler attachment
are buffered. A changed final response URL is not trusted as an admission response.

The app delegate restores only the identifier derived from the explicitly authorized
scope in the current Keychain session. An unavailable scope completes the OS
callback without attaching a transport or guessing credentials.

With a supplied context and provider, `wake()` reconstructs the persisted head
against getAllTasks. A matching suspended task is mapped before resume. A running
task is left alone. Conflicting/orphan tasks are cancelled; no replacement is
created in that pass. A missing task permits only an idempotent retry of the same
unresolved event, never an assumption of delivery. No task is resumed for a frozen
context. `suspend()` fences scheduling immediately, freezes the queue, and cancels
system tasks; it cannot revoke an already delivered request.

Fallback hooks are `wake()` on future foreground/BGProcessing/recovery entry points
and the background completion path. No retry timer or BGTaskScheduler policy is
registered in this phase. iOS may delay chaining, and a crash after durable receipt
but before creating the next task can leave work waiting for a future wake. Force
quit, first-unlock restrictions, auth refresh execution time and revoked identity
remain limitations; this implementation does not guarantee autonomous draining.

### Verification and next integration

`bash ios/Checks/run-vehicle-sync-checks.sh` uses fake authentication/transport and
temporary SQLite/files. It covers ordered multi-car events, causal RETURN, exact
retry, all admission dispositions, 401, uncertainty, retry cooldown, early rejection,
logout/mismatch, duplicate callbacks and create/mapping/resume restoration windows.
These tests do not send any HTTP request or establish physical-device success.
Queue/Auth/Vehicles regressions remain independently runnable. GitHub Actions and
the Probe are unchanged.

Before device testing: approve and connect the existing session provider and
lifecycle restoration factory; decide locked-Keychain policy separately; provide
authorized device/bindings and a controlled Dev test. No production App Intent,
vehicle screen, trigger or registration flow is connected in Phase 3.

### Phase 4 — session-bound background authentication

No screen or Intent enables synchronization. A future registration integration must
explicitly call enable(authorized:) for an initialized queue. It checks /api/me
and the current user's non-revoked iOS devices before recording the exact scope
in the activated Keychain session. Neither SQLite nor payload files contain tokens.
Foreground and background use one process-wide SessionManager and one refresh flight.
The OS-managed background task necessarily carries the access-token header.

Only the non-synchronizable session item changes accessibility, in place, to
AfterFirstUnlockThisDeviceOnly. Before the first unlock after reboot it cannot be
read. After first unlock it can be read while locked: this deliberately increases
credential availability to the app while locked. It does not enable backup,
migration to another device, or access by another app. Failed migration leaves
the legacy item intact until another successful unlocked read.

401 retains the immutable head. A fresh token is obtained before registering a
replacement. A protected per-event marker limits automatic authenticated replay
to one, including across restarts. A second 401 retains and blocks the head for
review; no sequence is skipped. Transient refresh failures retain credentials and
defer until a subsequent eligible wake (at least 60 seconds). iOS does not
guarantee a wake at the deadline. Explicit session revocation and logout cancel
OS tasks where possible; cancellation cannot undo an already delivered request.
Local events stay in their original partition. A new login has no scheduling
scope and cannot resume another identity's work.

### Phase 5 — Dev Shortcuts

The two actions live in the real iOS DEBUG app. The existing explicit
VehicleSessionRuntime.enable(authorized:) integration now reads the authenticated
device's vehicle-bindings list. It persists only usable refs/names alongside the
session scope. A shortcut stores a selection ID scoped to that login, not a name
or a last-opened vehicle. Refresh preserves the selection; logout invalidates it.
Offline authorization reflects the last confirmed snapshot. Admission still
rechecks current ownership and bindings on the server. No setup screen calls
enable yet. An empty picker on an unconfigured installation is expected.

The queue pairs a shortcut RETURN with exactly one unmatched, non-terminal TAKE
for the same vehicle in the same partition, inside the sequence-allocation
transaction. A duplicate TAKE, ambiguous/missing cause, or unusable position
does not allocate a sequence. Success in Shortcuts means persisted locally.
The optional Current Location parameter is a CLPlacemark. A provenance-bearing
CLLocation with its own accuracy and timestamp can supply evidence; otherwise
FCA checks its already-authorized Core Location cached fix. Neither path requests
permission in the background. A fix outside the existing 30-second/100-metre
contract is unusable. Shortcuts retaining measurement metadata while locked
requires physical verification.

For device discovery, build the real app with the Xcode wrapper (generate and
verify without --probe). The Linux xtool build compiles the actions but lacks
Xcode's metadata extraction. Keep existing automations disabled during review.

After separate approval, on a Mac with Xcode and the existing FCA **app** Dev
identity/profile installed, use the following from the repository root. Set
FCA_DEV_TEAM and FCA_DEV_PROFILE to that team's ID and that profile's exact name.
The profile must match the app bundle ID, Apple Sign-In entitlement and the phone.
The standalone Probe profile is for a different bundle ID.

```bash
set -eu
: "${FCA_DEV_TEAM:?existing FCA app team required}"
: "${FCA_DEV_PROFILE:?existing FCA app development profile required}"
work=$(mktemp -d)
python3 ios/Checks/app-intents-poc.py generate "$PWD/ios" "$work/wrapper"
xcodebuild -project "$work/wrapper/FCAIntentPoC.xcodeproj" -target FamilyCarAgent \
  -configuration Debug -sdk iphoneos SYMROOT="$work/products" OBJROOT="$work/objects" \
  SWIFT_COMPILATION_MODE=singlefile SWIFT_ENABLE_BATCH_MODE=NO OTHER_SWIFT_FLAGS=-disable-batch-mode \
  CODE_SIGN_STYLE=Manual CODE_SIGNING_ALLOWED=YES CODE_SIGNING_REQUIRED=YES \
  CODE_SIGN_IDENTITY="Apple Development" DEVELOPMENT_TEAM="$FCA_DEV_TEAM" \
  PROVISIONING_PROFILE_SPECIFIER="$FCA_DEV_PROFILE" build
app="$work/products/Debug-iphoneos/FamilyCarAgent.app"
python3 ios/Checks/app-intents-poc.py verify "$app" "$work/metadata-report.json"
codesign --verify --strict "$app"
mkdir "$work/Payload"
ditto "$app" "$work/Payload/FamilyCarAgent.app"
(cd "$work" && ditto -c -k --keepParent Payload FCA-Dev.ipa)
echo "$work/FCA-Dev.ipa"
```

Copy that IPA to Windows Downloads. Connect, unlock and trust the phone, then in
Ubuntu-24.04 run:

```bash
USBMUXD_SOCKET_ADDRESS=127.0.0.1:27015 /usr/bin/ideviceinstaller -i /mnt/c/Users/micha/Downloads/FCA-Dev.ipa
```

Launch FCA Dev once. In Shortcuts create a new ordinary shortcut, search for
each exact action title, and inspect the Vehicle picker. For RETURN, insert Get
Current Location before the FCA action and pass its output to Current Location.
Remove the test shortcut afterward if desired. Without a verified device/binding
setup the picker must be empty. Do not run bound actions against a live family
until explicitly approved. Discovery, locked execution and real location evidence
remain device checks.
