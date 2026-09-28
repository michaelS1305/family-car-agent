# FCA Android TAKE companion

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
   events are ignored. `EVENT_BT_DISCONNECTED` records diagnostics only.
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
No guessed disconnect grace/RETURN policy is encoded.

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
unlink. No address, GPS, token, full provider response or MAC is sent to the backend.

Deferred: RETURN, home/geofence, disconnect grace, full offline RETURN handling,
polish, all other native FCA screens, older Android compatibility, iPhone/CarPlay.

## API references used

- https://developer.android.com/reference/android/companion/CompanionDeviceManager
- https://developer.android.com/reference/android/companion/DevicePresenceEvent
- https://supabase.com/docs/guides/auth/sessions/pkce-flow
- https://developer.android.com/build/releases/agp-9-1-0-release-notes
- https://robolectric.org/compatibility_table/
