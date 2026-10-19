# Native Android Push A1 + A2 (Dev only)

No backend changes or live-delivery tests are part of this implementation.

## Environment and SDK

Dev uses the existing ignored `app/src/dev/google-services.json`, Google Services
plugin 4.4.4 and Firebase Messaging 24.1.2 (non-KTX). The SDK and messaging service
are Dev-source-set only. Runtime token access requires Firebase project
`family-car-agent-dev`; the Google Services task matches the Dev application ID.
Prod has a no-op platform implementation, no Messaging SDK, no service, no Google
Services processing and no invented Firebase configuration. Existing backend URLs
and credentials continue to come from the existing flavor configuration.

Auto-init, analytics collection and notification delegation are disabled in Dev's
manifest. Token retrieval is explicit after authenticated app entry. Do not enable
Firebase auto-init or server notification payloads as a workaround for background
restrictions. The backend protocol is data-only.

## Identity and private state

The app creates random UUID installation/request references, unrelated to hardware
or Companion installation IDs. A separate AES-GCM Android Keystore key protects
an AtomicFile in `noBackupFilesDir`. Existing app backup/transfer exclusions remain
unchanged. There is no new Bearer storage. FCM tokens remain in Firebase storage;
only a SHA-256 token fingerprint is kept by FCA. Pending nonces are encrypted,
never put in WorkManager Data or logs. Unreadable storage fails closed, rather than
silently claiming/replacing an existing installation.

State is scoped to owner, family and a random local epoch. Owner/family changes
invalidate the epoch, cancel only FCA Native Push notifications, discard pending
challenges/dedup state and allocate a new installation. Network work does not hold
the state lock. Responses and notification posting recheck active/auth owner and
epoch under that lock. Each local generation comes only from a successful matching
confirmation. Token rotation uses a new request on the same owned installation.

Registration durably stores request_id before POST. Early challenges can occupy
one encrypted slot before the POST response arrives. Installation, challenge,
nonce shape, expected generation and two-minute expiry are checked. A lost begin
response retries the SAME request ID; CHALLENGE_EXISTS is reconciled with the
matching challenge. Confirmation must return expected_generation + 1. A consumed
challenge cannot be reused locally. Failed/refused attempts have cooldowns and
workers have capped retries; there is no periodic registration loop.

## Logout / account switch / deletion

The existing authenticated logout and legacy Companion logout now invalidate local
push processing first, attempt up to two queued revocations on their existing IO
path while the old SessionStore is available, then fence again before the existing
store/session cleanup. Network failure does NOT mean revocation succeeded. Old
owner/reference/generation metadata remains encrypted; reconciliation is attempted
only when that same owner has an existing authenticated session again. No old
Bearer is retained to authenticate in the background after logout.

Firebase token deletion is queued and retried within worker limits, and must succeed
before registration for a subsequent owner. Offline logout cannot guarantee immediate
server revocation. Old in-flight opaque hints may arrive but cannot display old event
details. Server-side invalid/deleted identity or revoked generation causes authenticated
fetch denial, disables local registration and clears push notifications.

Settings account deletion is still a presentation-only placeholder in this repository;
this task does not implement that unrelated workflow. When wired later, it must use
the same invalidate-before-session-cleanup boundary. Backend deletion remains enforced
by the existing event API; this client has not tested live account deletion.

## Refresh and presentation

Only the exact data map `{"kind":"refresh","version":"1"}` starts a business
refresh. No event details are read from FCM. The separate registration challenge
map keeps its existing backend schema.

GET uses the existing authenticated FcaApi, owned installation and confirmed
generation. Independent refreshes start at page one, maximum four pages of 20
items. Cursor UUIDs and repeated cursors are checked. Later hints/resumes catch up
from page one, not a durable watermark. A hint received during a pass marks the
pass dirty for a bounded follow-up. More than 80 simultaneous eligible events may
need subsequent opportunities; this is not guaranteed exhaustive delivery.

Only vehicle_taken/vehicle_returned events with valid public IDs, timestamps and
an unexpired lifetime of at most five minutes are displayed. Expiry is checked
again at posting. Local clock skew can suppress valid events; it does not extend
the server's eligibility. No personal details are cached for fallback. Dedup stores
only event references and ten-minute local expiry, inside the installation scope;
records are pruned during work. Stable notification tags plus onlyAlertOnce also
reduce duplicate effects across a crash between posting and persistence. This is
not an exactly-once display guarantee.

The `fca_native_vehicle_events` channel respects permission, app and channel
settings. A single permission request is made after authenticated entry, never on
each message or resume. Denial does not bypass OS controls or stop secure registration.
The existing Settings link can open Android notification settings. Its pre-existing
Companion-channel status indicator is not redesigned by this task.

Notifications use Hebrew authorized names, the existing app name/car drawable,
secret lock-screen visibility, expiration timeout and an explicit immutable
PendingIntent to the existing EntryActivity. Taps contain no identity/event details
and do not add navigation routes. Existing in-memory navigation is preserved.

## Work and limitations

FirebaseMessagingService performs only validation/private-state handoff and enqueue.
Existing WorkManager runs one unique push chain with network constraints and
expedited work falling back to ordinary scheduling. There are at most three worker
attempts with exponential backoff, finite pages/revocations/registration calls, and
existing HTTP timeouts. No periodic poll, foreground service, Companion executor,
detector, Bluetooth, geofence or acquisition behavior is changed.

Android can delay or suppress data-only work, especially offline, locked, battery
restricted or force-stopped. No delivery/background/display guarantees are made.
Foreground authenticated entry/resume offers another bounded opportunity. Account
switch and permission/clock/FCM timing behavior require physical Dev QA.

## Local validation / separately approved device checklist

Run compileDevDebugKotlin, focused NativePushTest, full testDevDebugUnitTest,
assembleDevDebug and lintDevDebug. Compile Prod and inspect its merged manifest to
verify no Firebase service/config dependency. Tests must never send live messages.

Device QA: initial grant/denial, challenge receipt, token rotation, process restart,
offline logout then account switch, multiple installations, duplicate hints, revoked
generation, five-minute expiry, notification tap, locked/background/force-stop states,
and Companion operation alongside push. Real Firebase/Render behavior is unverified
until separately authorized testing. Do not install, enable Prod or deploy implicitly.
