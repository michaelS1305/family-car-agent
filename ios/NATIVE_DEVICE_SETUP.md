# Native iOS device setup (Dev, Phase 6)

Only an explicit activation in Vehicle Details ׳’ג€ ג€™ Connection registers/binds a device.
The app uses POST /api/devices (`platform: ios`, durable `request_id`), GET
/api/devices?platform=ios and PUT/GET device vehicle bindings. It never adopts an
arbitrary device from the list or binds all family vehicles. Authentication and
Keychain service/account identity are unchanged.

## Persistence and crash recovery

Application Support/NativeDeviceRegistration/<auth-owner>.json is a protected,
backup-excluded, atomic non-credential journal. It contains environment, owner,
user/family, registration request UUID, returned device UUID, queuePrepared and
per-vehicle CarPlay/Bluetooth choices. It contains no tokens or location data.
Corruption/unreadability is an error, not a new-installation signal.

1. Commit request UUID before POST. Lost responses/restarts retry that UUID.
2. Commit the server's device UUID before preparing SQLite.
3. Initialize the exact queue partition only while queuePrepared is false. This
   journal has never enabled a runtime; a repeated initialization preserves an
   existing partition and cursor.
4. Commit queuePrepared before binding/authorizing/enabling. From then on the
   partition must exist: recovery only, never sequence-zero initialization.
5. Explicitly bind the selected vehicle; GET validated bindings populates the
   existing session scope and stable entity namespace. Wake existing coordinator.

An interruption between 2 and 4 can safely resume because no upload or shortcut
scope has been enabled. An interruption after 4 cannot justify a cursor reset.
Missing journal with an existing session scope, missing prepared queue, conflicting
family or malformed journal requires recovery; there is deliberately no reset UI.
Existing queue history also prevents new registration if the journal was lost
after logout (when the authentication scope is no longer present).
Logout retains journal/queue but the existing session invalidation cancels uploads
and fences callbacks. Same-account/family re-entry revalidates before resuming.
Different accounts have different journals and queue contexts. Family changes do
not relabel a device's existing sequence/history.

Foreground restoration only restores local state; it never POSTs/PUTs or initiates
permission verification. Explicit refresh commits verificationPending before GET;
transient network failure then keeps that fence until a successful explicit retry.
Refreshed grants gate each queued head. An unbound head is retained and blocks later
sequences rather than being skipped. Cancellation cannot retract a request already
received by the server. Backend admission remains authoritative.

Changing connection methods changes only the journal. FCA does not discover or
claim that personal automations have been installed. Public intent parameter IDs,
names, location validation and queue payloads are unchanged. Setup UI is Dev DEBUG
because the existing vehicle App Intents are DEBUG-gated.

## Physical iPhone verification (not performed by local checks)

The original stale-Keychain regression now passes:
`bash Checks/run-vehicle-sync-checks.sh --verify-durable-revocation`.
The user accepts the total-persistence-failure limitation described below for
controlled Dev testing only, not production. The authorization fence is durable in SQLite, not merely the process-local
permit. Refresh remains GET-only; activation is the only binding PUT path.

1. Install a separately approved Dev build using the existing signing procedure;
   confirm the login survives. Do not delete app data to simulate recovery.
2. Open one active vehicle's connection sheet, choose a method and activate. Verify
   it appears by name in both FCA vehicle actions. Repeat activation, then activate
   a second vehicle: confirm one registered device and two explicit bindings.
3. Relaunch offline; verify both entities and previously saved selections resolve.
   Change the connection method and verify pending events remain intact.
4. CarPlay: create user-owned Connects/Disconnects automations, Run Immediately.
   Connects uses Take Vehicle. Disconnects uses Get Current Location then Return
   Vehicle with that output, both selecting this exact vehicle.
5. Bluetooth: select the actual paired car for the connection automation. Use a
   regular manually run shortcut for RETURN; no disconnect trigger is assumed.
6. With an explicitly approved Dev test vehicle, queue TAKE offline, then RETURN
   using a real <=100 m, <=30 s measurement. Restore connectivity, do not force-quit,
   and verify server acceptance/order (local "saved" is not server acceptance).
7. Test logout/account switch with pending work: no transmission under a different
   account; stale saved entity IDs must fail. Test server revocation/binding removal
   separately in approved Dev testing, followed by refresh; no new upload may be
   scheduled for a known unbound head. No sequence skip/reset is implemented.
8. Verify locked-device/first-unlock behavior, location provenance from Shortcuts,
   layout/RTL and physical CarPlay/Bluetooth triggers. iOS scheduling is not immediate
   or guaranteed by a successful local build.

Apple references checked for the guide:
- https://support.apple.com/en-lamr/guide/shortcuts/apd8ebfc4e8e/ios (CarPlay)
- https://support.apple.com/en-ie/guide/shortcuts/apde31e9638b/ios (Bluetooth)
- https://support.apple.com/guide/shortcuts/run-a-shortcut-from-the-app-apd5ba077760/ios (manual execution)

Local checks: `Checks/run-native-device-setup-checks.sh`,
`Checks/run-vehicle-sync-checks.sh`, existing queue/auth/vehicles/details checks,
and existing App Intents project-generator checks. They use synthetic local data;
no live device registration, vehicle mutation, signing or deployment is performed.


## Durable authorization fence (Phase 6 follow-up)

Schema v2 adds `authorization_scopes(context, generation, state, namespace)` and
`vehicle_authorizations(context, vehicle, allowed)`. Context is the existing full
environment/owner/user/family/device partition. Migration is transactional, retains
all events/cursors, and creates NO grants for old installations. Missing rows are
unknown/denied; the first explicit online activation or refresh must verify them.
An offline upgrade cannot create events until that verification succeeds.

Explicit activation/refresh commits a new UUID generation and `verificationPending`
before profile/device/binding verification. The whole device is fenced because the
response verifies device ownership/family and the complete binding set. No other
identity/device partition is blocked. A network failure or process death leaves the
pending fence; it is not a confirmed server revocation. Retry is explicit and uses
a new generation. Completion requires matching generation, pending state and active
partition. Older responses cannot commit. Only explicit activation performs PUT.
Normal session/Shortcut restoration is local and does not start this verification.
After successful verification, offline selection uses the intersection of Keychain
bindings and SQLite grants, tied to the existing login's shortcut namespace.

BEGIN IMMEDIATE covers durable permission checks, namespace checks, causality,
sequence increment and event insertion. Revocation uses the same database locking;
a committed event before the fence is retained, and an insertion after it fails
without consuming a sequence. Separate-process tests cover these boundaries.
Missing/corrupt grants fail closed. Pending/removed heads remain queued, never skipped.
Keychain write failure after preflight leaves SQLite pending, so old credentials
cannot restore permission. Upload checks and cancellation are best effort: a request
already delivered to the OS/server cannot be retracted atomically by a SQLite commit.

Logout/identity invalidation synchronously attempts a durable revocation using a
separate SQLite connection. If that fails, it attempts `devices.active=0` in the same
existing database and still reports failure. Reactivation invalidates outstanding
verification generations before lifting quarantine. The runtime latches storage
failure and fences/cancels its work; local recovery requires restart and explicit
online verification. No session/queue deletion or sequence reset is used.

**Remaining limitation (accepted for controlled Dev only):** if BOTH revocation and partition-quarantine writes
fail, and stale Keychain authorization survives, a fresh process cannot infer the
failed invalidation. This is demonstrated by deterministic SQL failure injection.
No durable success is claimed for that case; a guarantee would require another
reliable persistent authority or a stricter offline policy. Neither was added.
Physical iPhone storage-protection, locked-device, daemon cancellation and signed
Xcode behavior remain unverified by local tests. No signing/install is performed.

## Structured server rejection and connection UI

Only the structured `detail.code` paired with its expected status is treated as
authorization rejection: `404 DEVICE_OR_VEHICLE_UNAVAILABLE` or
`403 IDENTITY_UNAVAILABLE`. The ambiguous first code fences the entire affected
device/identity context, without claiming that the device itself was revoked.
The queue atomically revokes grants and blocks the matched event, preserving its
payload, sequence and all pending events. Current-process scheduling is stopped
even if persistence fails. Successful later verification cannot skip the blocked head.

Connection UI reads the persisted authorization state. Failed verification remains
pending (displayed as temporarily unavailable in the current screen); reopening
restores pending state. Retry is verification-only, never an implicit binding PUT.
A confirmed removed binding requires explicit activation. Local checks cover these
transitions, stale Keychain restoration, generic errors and persistence failures;
rendered UI and background behavior still require physical-iPhone verification.
