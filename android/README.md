# FCA Android TAKE / RETURN companion

Independent Kotlin Android project; no PWA build/layout changes. This first
detector targets **Android 16 / API 36+** (Samsung S24 FE). Earlier versions are
not claimed supported: their older presence callbacks do not distinguish BLE
proximity from Classic connection as explicitly. No Android Auto/CarPlay work.

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

Copy `fca.properties.example` to ignored `fca.properties` and set HTTPS backend,
Supabase project URL, and **public publishable/anon key only**. These are compiled
public client configuration, not secrets. Never put service-role credentials in
this project. Missing configuration builds but sign-in fails closed.

With JDK/SDK configured, from this directory (the pinned wrapper is included):

```
.\gradlew.bat :app:testDebugUnitTest :app:lintDebug :app:assembleDebug
```

APK: `app/build/outputs/apk/debug/app-debug.apk`. Install using Android Studio or
`adb install -r app/build/outputs/apk/debug/app-debug.apk` on the Samsung. A physical
test is required; successful compilation cannot prove OEM background delivery.

## Google/Supabase setup

Use the existing Supabase project's Google provider. This client uses the system
browser and Supabase's **PKCE OAuth flow**, not a separate Android Google credential
or shortcut token. Add `il.fca.companion://auth/**` to the Supabase Auth redirect
allowlist to permit the callback and per-login nonce query. The client accepts
only `/callback` with its own pending nonce and PKCE verifier. Keep the Google provider's existing Supabase callback
configuration. Browser OAuth does not require an Android SHA fingerprint/client
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
   connected during setup). Only `EVENT_BT_CONNECTED` produces a TAKE; BLE nearby
   events are ignored. `EVENT_BT_DISCONNECTED` starts the RETURN grace described below.
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
constraints/exponential retry. Unique immediate work plus periodic recovery covers
death between DB commit and enqueue. Acknowledged local rows are bounded to 30;
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

Deferred: polish, all other native FCA screens, older Android compatibility, iPhone/CarPlay.

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
**60-second grace** (one constant), wall and monotonic deadline. Reconnect cancels
it; the pre-existing reconnect TAKE/no-op-alias behavior remains. The final local
queue transaction rechecks account, acquisition, disconnected state and deadlines,
then appends exactly one RETURN after its TAKE. Offline delivery reuses the same
payload/UUID/sequence. Location payload is removed from the local row after receipt.

A no-network-constraint worker requests one GPS fix, bounded to 20 seconds, only
after grace. Freshness uses monotonic and wall clocks; mock, inaccurate or absent
fixes fail closed. Permission/home/location failure or outside-home abandons this
candidate with diagnostics, requiring a new physical cycle. A worker more than
five minutes late also abandons it: later arrival home must not retroactively
qualify an old disconnect. Periodic recovery and app startup recover durable
candidates, but WorkManager/OEM scheduling is not exact. Reboot invalidates pending
physical candidates, never immutable outbox events. No continuous GPS or force-stop
guarantee. Missed OS connection callbacks remain a physical-validation limitation.

Permissions: first grant precise foreground location, then choose **Allow all the
time** in app location settings using the diagnostic setup button. Background
location is required because the screen need not be open. Approximate/foreground-only
permission fails closed. Background GPS can fail or be delayed by Android/Samsung
power policy; no foreground-service or battery-policy bypass is added.

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

- https://developer.android.com/reference/android/companion/CompanionDeviceManager
- https://developer.android.com/reference/android/companion/DevicePresenceEvent
- https://supabase.com/docs/guides/auth/sessions/pkce-flow
- https://developer.android.com/build/releases/agp-9-1-0-release-notes
- https://robolectric.org/compatibility_table/
