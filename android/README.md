# FCA Android TAKE / RETURN companion

Independent Kotlin Android project; no PWA build/layout changes. This first
detector supports **Android 15 / API 35+**. API 35 uses manifest Bluetooth ACL
connected/disconnected broadcasts, filtered to the selected local bonded address
and Classic (BR/EDR) transport. Missing/LE transport is ignored, not guessed.
API 36+ retains Companion `DevicePresenceEvent` callbacks. Version-qualified
component enablement and runtime guards prevent overlapping detectors and API 36
class loading on 35. Both use the same durable TAKE/RETURN pipeline. Companion
association/selection remains on both versions; legacy BLE-presence callbacks are
not used. No permanent foreground service or Android Auto/CarPlay work.

## Backend prerequisite (operator-controlled, NOT applied by this task)

Review/apply `2026092701_registered_device_vehicle_bindings.sql` before deploying
the matching backend. No backfill: historical activity does not grant authority.
The table uses the existing backend-only Vehicle Identity ACL model. No browser
access, Bluetooth identifiers, or new vehicle/session authority. Device/user and
vehicle/family are derived and revalidated, not duplicated into binding rows.

JWT endpoints:

- `POST /api/devices`: `{ "request_id": "UUID4" }`; server chooses Android platform.
- `GET /api/devices`: caller's Android refs/platform/revocation only.
- Existing `GET /api/me` and `GET /api/vehicles`.
- `GET /api/devices/{device_ref}/vehicle-bindings`: own-device family bindings,
  vehicle refs/names and `usable` lifecycle state.
- `PUT` / `DELETE /api/devices/{device_ref}/vehicle-bindings/{vehicle_ref}`:
  desired-state idempotency, no body or client identity. Opposite operations must
  be serialized; delayed PUT after DELETE is a new binding, not historical replay.
- `POST /api/devices/{device_ref}/events/take`: UUID4 `event_id`, UUID `vehicle_ref`,
  positive int64 `device_sequence`, aware ISO `occurred_at`. Extra fields rejected.
  Returns existing admission `{kind, admission_outcome, transition}`. Only
  accepted/retry/terminal receipts advance the local queue. Other results retain
  the head event and require retry/attention; no sequence skipping or new UUID.

The binding-gated adapter holds identity -> family advisory -> family row ->
device -> vehicle locks through existing admission. No network inside this DB
transaction. Revoked devices cannot submit; retired/unbound vehicles cannot
receive new TAKE. An exact already-committed receipt can replay after unbinding
without re-executing anything. Binding removal never ends a session. No alternate
public route exposes the ungated internal native engine. Realtime remains the
existing accepted-event trigger; PWA/Gemini read the existing sessions.

## Build and public configuration

Use Android Studio supporting AGP 9.1.1, Gradle **9.3.1**, Android SDK platform 36
and Build Tools 36.0.0. JDK 17 builds the app; **JDK 21 is needed for Robolectric
API 36 tests**. Install SDK/licenses explicitly through Android Studio/SDK Manager.
Open this `android/` directory, not the Python/PWA root.

Use the `dev` / `prod` product flavors independently of debug / release:
`devDebug`, `devRelease`, `prodDebug`, `prodRelease`. Namespace, SDK levels,
signing configuration and all sensor/storage behavior remain unchanged.

Copy `fca.dev.properties.example` to ignored `fca.dev.properties`, and the
corresponding Prod template to ignored `fca.prod.properties`. Supply each project's
**public publishable/anon key only**. Never use a service-role key. Generic
`fca.properties` is no longer read; there is no fallback between environments.
Only the selected variant needs its configuration. Missing or mixed endpoint,
project or callback values fail its build. Endpoints and callback are flavor-owned;
the local values must match exactly. Legacy anon JWT metadata must name the right
project and anon role (this is not signature verification). Opaque publishable keys
have no locally verifiable project identity: the operator must select the right
project's key and verify login. Keys are compiled public client configuration;
never share generated BuildConfig output or put private credentials in the APK.

| Flavor | Application ID | Label | Callback |
|---|---|---|---|
| dev | `il.fca.companion.dev` | FCA Companion Dev | `il.fca.companion.dev://auth/callback` |
| prod | `il.fca.companion` | FCA Companion | `il.fca.companion://auth/callback` |

Dev targets `family-car-agent-dev.onrender.com` and Supabase project
`jouhqvbxhsvkluwkqmdg`; Prod targets `family-car-agent.onrender.com` and project
`xrgijytfigcuxmdktvmd`. No runtime environment switching is supported.

With JDK/SDK configured, from this directory (the pinned wrapper is included):

```
.\gradlew.bat :app:testEnvironmentConfiguration
.\gradlew.bat :app:testDevDebugUnitTest :app:lintDevDebug :app:assembleDevDebug
.\gradlew.bat :app:testProdDebugUnitTest :app:lintProdDebug :app:assembleProdDebug
```

APKs: `app/build/outputs/apk/dev/debug/app-dev-debug.apk` and
`app/build/outputs/apk/prod/debug/app-prod-debug.apk`. A physical
test is required; successful compilation cannot prove OEM background delivery.

Dev installs beside Prod with separate private data, Keystore credentials,
WorkManager state and Companion associations. Do not copy databases, credentials,
registration IDs or outbox events between them. Preserve Prod's existing signing
certificate and package ID for in-place updates; verify version-code compatibility
before installation. Do not uninstall/clear the existing installation. No release
signing credentials are introduced by flavors.

Initially test with only one environment's detector intentionally active. Separate
packages do not exclude simultaneous detection of the same physical car. Switch
only with vehicle free and queues/candidates settled; existing sign-out disables
detection but invalidates active acquisition state. Do not sign out mid-trip.
Complete FCA onboarding through Web Dev before native login, then register and
bind a fresh Dev installation. Test callback routing, TAKE/RETURN, offline outbox
and deferred recovery while checking only the intended environment changes.

## Google/Supabase setup

Use the existing Supabase project's Google provider. This client uses the system
browser and Supabase's **PKCE OAuth flow**, not a separate Android Google credential
or shortcut token. Keep `il.fca.companion://auth/**` in Production and add
`il.fca.companion.dev://auth/**` only to the Dev Supabase Auth redirect
allowlist to permit the callback and per-login nonce query. The client accepts
only `/callback` with its own pending nonce and PKCE verifier. Keep the Google provider's existing Supabase callback
configuration; Dev Google OAuth must allow the Dev Supabase project's
`https://jouhqvbxhsvkluwkqmdg.supabase.co/auth/v1/callback`. No external settings
are changed by building these variants. Browser OAuth does not require an Android SHA fingerprint/client
ID. The custom scheme is not a claimed HTTPS app link: interception can cause
denial of login, but cannot redeem the code without the private verifier.

The verifier/nonce and only the Supabase access/refresh credentials are encrypted
with Android Keystore AES-GCM in private preferences. Refresh is serialized and
persisted, including rotation. No Google provider tokens retained. Tokens never
appear in diagnostics. Refresh failure leaves events pending. Backend CurrentUser
remains the only trusted person/family authority. Backup and device transfer are
disabled so installation sequence/credentials cannot be cloned by normal backup.

## Physical test

1. Operator prepares compatible backend/migration separately; this task does not deploy.
2. Configure/build/install as above. Do not clear app data while testing retries.
3. Sign into the mother's existing Google/FCA account. Confirm her name in the app.
4. Tap registration (stable per-account installation request UUID survives retries).
5. Refresh vehicles, select Hyundai, grant Nearby devices/Bluetooth permission.
6. Select Hyundai from **already bonded** devices. Names are display only; local
   address and OS association ID distinguish devices. FCA never calls createBond.
7. Approve the Android companion association. Server PUT must succeed before the
   local association/presence observation is enabled. If approval is interrupted,
   repeat setup; an existing matching system association is reused.
8. Start a fresh physical Bluetooth connection (disconnect/reconnect if already
   connected during setup). API 36 uses `EVENT_BT_CONNECTED` / `EVENT_BT_DISCONNECTED`;
   API 35 uses Classic `ACTION_ACL_CONNECTED` / `ACTION_ACL_DISCONNECTED` for the
   bound paired address. BLE nearby events are ignored. Both start the same TAKE
   and RETURN grace described below.
9. Observe pending count/delivery diagnostics; refresh PWA and confirm Hyundai's
   driver is the mother. Screen can be closed; do not force-stop the app.
10. Test airplane/no-network, then restoration: exact event ID/sequence must retry.
    Reopen app after process death and check queue recovery. Test a second vehicle
    association; one phone supports many vehicles, one vehicle many family phones.

## Durability / diagnostics / limits

SQLiteOpenHelper is used rather than Room/code generation for this small store.
A single SQLite transaction updates observed connection state, assigns sequence,
inserts the immutable event, and increments next sequence. Repeated connected
callbacks produce no second event. Disconnect only rearms TAKE detection; rapid
real reconnects may produce another TAKE and existing server no-op rules apply.
An OS boot-count change also rearms connection detection without resetting the
sequence or queue; an ordinary process restart preserves the connection latch.
RETURN extends this latch with the durable causal link and grace described below.

WorkManager delivers strictly ordered pending events per installation with network
constraints. Each fresh kick is an independent expedited request (ordinary-work
fallback if quota is exhausted), not a child of the old `fca-delivery` chain.
Failed kicks finish after scheduling `fca-delivery-recovery`, which owns exponential
backoff; future kicks do not wait for it. A process-wide drain lock serializes all
kick/retry/periodic HTTP drains without holding a SQLite transaction over network.
Every enqueue creates a new opportunity, including at another drain's exit.
The unchanged 15-minute periodic recovery covers death between DB commit and
enqueue. Existing WorkManager jobs remain compatible and use the same guard.
Diagnostics distinguish kick requests/starts and recovery starts with attempt
counts. Previously installed periodic/one-time requests without source metadata
report `legacy_recovery`; new periodic requests report `periodic`. No jobs or
outbox rows are reset. Acknowledged local rows are bounded to 30;
unacknowledged events are never pruned. Server terminal receipts are acknowledged,
but auth/transport/permission/sequence conflicts keep the original payload. An
unbound/revoked head event can therefore block later sequence delivery: do not
silently skip it or reset registration to hide the failure.

Queues and associations are account-scoped. Signing out disables detection and
retains pending events; another account cannot send them. Clearing data/uninstall
does lose local state and requires a new registered installation. Force-stop,
permission removal, battery/OEM restrictions, and missed callbacks require physical
validation. WorkManager is eventual, not real-time. No guarantee is made for an
event the OS never delivers.

UI is basic: authenticated name, installation ref, vehicles, local associations,
connection state, pending count, safe HTTP/category diagnostics, manual retry and
unlink. No address text, full provider response or MAC is sent to the backend.
RETURN sends only a one-shot location fix and its accuracy/time over authenticated HTTPS.

API 35 setup uses the same Nearby devices (`BLUETOOTH_CONNECT`) runtime grant and
Android Companion approval. RETURN still requires precise location plus Allow all
the time. The manifest ACL broadcasts are Android implicit-broadcast exceptions,
so detection is intended to work with UI closed/screen locked (not force-stopped).
Physical Samsung validation remains required for background callbacks, permissions,
transport metadata, location and scheduling. No missing callback is synthesized.

Deferred: polish, all other native FCA screens, API 34 and older, iPhone/CarPlay.

## RETURN physical slice

No new PostgreSQL schema is required. Deploy the matching backend before installing
this APK. TAKE remains the same physical callback and admission path.

- `GET /api/devices/{device_ref}/return-home`: own active Android device only;
  authenticated family's latitude/longitude, no-store response. Android keeps one
  account-scoped home pair for at most 24 hours, cleared on sign-out. Refresh before
  testing. This small cache is necessary to qualify an event **offline**, not a
  client authorization claim. The server rechecks the current family home.
- `POST /api/devices/{device_ref}/events/return`: TAKE envelope plus UUID4
  `take_event_id`, finite numeric `latitude` [-90,90], `longitude` [-180,180],
  `accuracy_m` (0,100], aware `location_at`. The fix must be 0–30 seconds older
  than `occurred_at` (not receipt time). Unknown fields rejected.
- Both sides require distance + reported accuracy <=500 metres. Location is
  client evidence, not tamper-proof attestation. Backend checks family home,
  ownership, active binding/device/vehicle and delegates causal/sequence handling
  to existing admission. No location is inserted into PostgreSQL event/history.
- Existing committed receipt replay bypasses changing home/binding eligibility,
  but retains exact event-envelope matching and revoked-device rejection.
  Invalid home/fix returns 409/422 without consuming sequence or mutating state.
  Such a rejected queue head remains pending/action-required, never skipped or
  regenerated. An address change while offline can therefore require operator
  investigation; the app does not re-home or rewrite captured evidence.

SQLite v2 upgrades v1 additively, preserving installation, sequence, associations
and pending TAKEs. A fresh TAKE saves its UUID on the acquisition; acknowledgement
pruning cannot remove that causal link. Disconnect persists a candidate with a
**30-second grace** (one constant), wall and monotonic deadline. Reconnect cancels
it; the pre-existing reconnect TAKE/no-op-alias behavior remains. The final local
queue transaction rechecks account, acquisition, disconnected state and deadlines,
then appends exactly one RETURN after its TAKE. Offline delivery reuses the same
payload/UUID/sequence. Location payload is removed from the local row after receipt.

The bounded foreground-service acquisition first inspects enabled GPS/network providers' last-known
fixes after grace. Each must satisfy the unchanged 30s wall/monotonic freshness,
non-mock and <=100m accuracy checks. Newest monotonic timestamp wins; accuracy is
only a tie-breaker, never home distance. Original timestamps are preserved.
If no cache is usable, one asynchronous current-location request per enabled
GPS/network provider races within a single 20s monotonic budget including cache
inspection/setup. Invalid/null responses do not stop the other provider. First
usable response wins and cancels outstanding requests; all failures finish early,
otherwise the shared deadline cancels them. Controller stop also cancels; late callbacks
are ignored. There is no polling, repeated acquisition, Play Services dependency,
or continuous tracking. Freshness is rechecked before queueing. A selected usable
fix outside `distance + accuracy <=500m` fails without searching for a more favourable
fix. Permission/home/location failure or outside-home abandons this
candidate with diagnostics, requiring a new physical cycle. The original-disconnect
60-second watchdog also abandons expired candidates: later arrival home must not retroactively
qualify an old disconnect. Periodic recovery and app startup recover durable
candidates, but WorkManager/OEM scheduling is not exact. Reboot invalidates pending
physical candidates, never immutable outbox events. No continuous GPS or force-stop
guarantee. Missed OS connection callbacks remain a physical-validation limitation.

Permissions: first grant precise foreground location, then choose **Allow all the
time** in app location settings using the diagnostic setup button. Background
location is required because the screen need not be open. Approximate/foreground-only
permission fails closed. The bounded location foreground-service experiment below
changes execution context only; the operator has reported successful Samsung
online / above-ground physical cycles, as summarized below.

### Bounded RETURN foreground-service experiment (online / above-ground only)

After persisting a disconnect candidate, FCA verifies its current system CDM
association by both ID and Bluetooth address, then requests an internal location
foreground service. Existing companion permissions are retained. Explicit app-owned
FOREGROUND_SERVICE, FOREGROUND_SERVICE_LOCATION and WAKE_LOCK permissions are
declared; no Play Services dependency or location-policy change is introduced.

The service promotes immediately with a generic notification: `Family Car Agent` /
`מעדכן את מצב הרכב…`. POST_NOTIFICATIONS is not a RETURN prerequisite: when notification
permission is unavailable Android may show the service only in its active-apps/Task
Manager surface rather than the notification drawer.

A single serial controller waits the remaining persisted 30-second grace, then
runs the unchanged cache-first GPS/network acquisition on a separate executor.
Framework callbacks remain on mainExecutor. There is no acquisition during grace.
The unchanged 20-second shared acquisition budget, home cache, accuracy, freshness,
mock rejection and distance checks still apply. Only qualified evidence reaches
the existing atomic queueReturn and delivery path; the service does not wait for HTTP.

The watchdog is anchored to the original disconnect: grace deadline + 30 seconds
(60 seconds total), bounded by both wall and elapsed clocks. Duplicate starts and
recovery cannot reset it. A timed partial wake lock covers only the remaining window,
because a service alone does not keep the CPU awake through locked-screen grace.
Every terminal path releases it; the OS timeout is a final safety net.

Reconnect/account/association changes notify the controller after SQLite commit.
Cancellation and stale completion cannot act on a successor candidate. All service
instances share a single location executor. WorkManager now only requests the same
orchestrator, including an immediate process-start recovery request. SQLite remains
authoritative after process death; expired candidates fail closed rather than gaining
a new grace/watchdog window. No sticky intent or replacement event is generated.

Fixed diagnostics include `return_fgs_start_requested`, `return_fgs_started`,
`return_fgs_promoted`, `return_fgs_duplicate_suppressed`, `return_fgs_candidate_invalid`,
`return_fgs_acquisition_started`, `return_fgs_watchdog_expired`, bounded
`return_fgs_start_denied_*` and `return_fgs_stopped_*`. Existing provider diagnostics
remain. No identity/location values or exception messages are logged.

Operator-reported physical validation passed automatic TAKE, two consecutive home
TAKE/RETURN cycles, reconnect within grace without RETURN, outside-home rejection,
and subsequent automatic RETURN at home, without Companion interaction. Retained
diagnostics confirm the latest cycle's foreground promotion, 30-second grace,
fresh GPS callback, durable queueing, service shutdown and accepted delivery.
This is not a guarantee across every device/OS/power-policy combination. Force-stop, revoked
permissions, missing CDM association or unavailable location can still prevent RETURN.
This does not implement underground/offline home evidence, geofencing or trip tracking.

Source diagnostics are `return_location_source_cache_gps`, `_cache_network`,
`_current_gps`, `_current_network` (each with the full `return_location_source`
prefix). Provider availability uses `return_location_<gps|network>_<disabled|unavailable>`;
cache/current rejection diagnostics append the existing bounded failure reason.
Network positioning is device/OS-service dependent and may be unavailable or too
coarse. The race improves opportunities, not guarantees; physical locked-screen
testing on Android 15/16 remains necessary.

Home-check failures use `return_home_check_failed_<reason>` with fixed categories
for missing/expired/clock-invalid home cache, fine/background permissions, timeout,
unavailable fix, stopped/interrupted worker, security/request error, old/invalid
timestamps, mock fix, missing/invalid/insufficient accuracy, invalid coordinates,
or outside-home radius. No measured location/accuracy/distance or exception text
is logged. Diagnostic write failures do not block RETURN processing. Existing
persisted candidates keep their original deadline; newly observed disconnects use 30s.

### First RETURN using the existing mother's Hyundai session

1. Update with `adb install -r` (do not uninstall/clear data). Keep the same account,
   installation and Hyundai association. Configure location permissions above.
2. Refresh device/vehicles/home while online; verify the account is ז'אנה.
3. **Perform a real Hyundai Bluetooth disconnect/reconnect after upgrading.** v1
   did not record a proven acquisition link; this upgrade deliberately guesses none.
   The new TAKE is an alias/no-op for the mother's existing active Hyundai session,
   not a manual reset. Verify TAKE delivery and that Hyundai remains occupied.
4. At the configured home, disconnect Hyundai Bluetooth, keep the phone there,
   and do not reconnect during grace. The UI may be closed (not force-stopped).
5. Expect `bluetooth_disconnected`, `return_grace_started`,
   `return_home_check_started`, `return_queued`, `return_delivery_accepted`;
   pending returns to zero, PWA available, original session gains its causal end.
6. Separately test quick reconnect cancellation; outside-home rejection; offline
   TAKE then RETURN with home cached in the preceding 24h; network restoration;
   normal process restart. Fail-closed diagnostics are not evidence of a RETURN.

Android location constraints:
https://developer.android.com/develop/sensors-and-location/location/permissions/runtime
https://developer.android.com/develop/sensors-and-location/location/permissions/background
https://developer.android.com/reference/android/location/LocationManager

## API references used

- https://developer.android.com/develop/background-work/background-tasks/broadcasts/broadcast-exceptions
- https://developer.android.com/reference/android/bluetooth/BluetoothDevice
- https://developer.android.com/reference/android/companion/CompanionDeviceManager
- https://developer.android.com/reference/android/companion/DevicePresenceEvent
- https://supabase.com/docs/guides/auth/sessions/pkce-flow
- https://developer.android.com/build/releases/agp-9-1-0-release-notes
- https://robolectric.org/compatibility_table/
