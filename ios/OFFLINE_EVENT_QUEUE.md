# Durable native vehicle queue — Phase 2

Storage only. No UI/lifecycle wiring, networking, registration, App Intent, or
background upload is introduced. `VehicleEventQueue.applicationDirectory()` is
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
