# Native RETURN location acquisition

Local implementation only. No CI, signed app, device integration or release has been executed for this change.

## Contract and isolation

`FCA — Return Vehicle` takes only `Vehicle`. Bluetooth and CarPlay use this same
Intent. No Current Location variable/action, address conversion or geocoding is
required. Owners must recreate RETURN shortcuts after a separately approved build;
existing iCloud links are intentionally unchanged. TAKE and its links are unchanged.

The acquisition lifecycle is adapted from the physically tested Development POC
at 593dc08e99cf45b60054c9fe3fdef6b116493903. Its diagnostic Intent, permission button,
Development-only guards and temporary signing exceptions are not included.

## Acquisition and permission lifecycle

The foreground authenticated notification permission flow calls the shared location
permission service after notification authorization has completed, whether granted,
denied or terminated by an error. The notification error remains reported by Push;
a scoped completion runs once before subsequent push registration/revocation work. It waits for UIApplication.didBecomeActiveNotification if inactive.
Only notDetermined authorization causes one When In Use request. Re-entry cannot
start a duplicate request. Existing denied/granted installations are not prompted.
The permission manager never starts location updates or warms the acquisition.
Settings and vehicle connection UI refresh authorization/accuracy on activation.

Each RETURN owns a retained MainActor CLLocationManager and delegate. It uses
startUpdatingLocation, a ContinuousClock 15-second deadline, background updates and
the visible background indicator. Invalid fixes are ignored while the original
deadline remains. A valid fix, terminal error, cancellation or timeout stops updates,
clears the delegate and timer, and resumes the continuation exactly once. Late
callbacks are inert. locationUnknown remains transient inside the same deadline.
No geocoding, network lookup, Always permission or temporary accuracy prompt exists.
Reduced authorization does not bypass numeric accuracy validation.

The existing native policy remains: valid coordinates, accuracy >0 and <=100m,
measurement age 0...30s, no simulated source. Missing native sourceInformation is
allowed, as in the verified POC. Only the actual Core Location delegate populates
private acquisition evidence; no Shortcut coordinates are treated as native.

## Recording and concurrency

Before acquisition, local installation validation and SQLite preparation capture
account/device/vehicle context, Shortcut namespace, authorization generation,
intended immutable TAKE evidence, its known anchor/session identity, and relevant
blocked RETURN/recovery eligibility. Preparation writes no event or sequence.
No new persistent metadata or schema is introduced.

After acquisition, runtime context is locally revalidated. The semantic identity
is checked under SQLite BEGIN IMMEDIATE before sequence allocation. Ordinary
pending/registered/accepted transitions, unrelated metadata and transport fields
do not invalidate the intended RETURN. A known anchor and session must remain
identical and open. An unknown anchor may resolve to the captured TAKE itself;
resolving it to another anchor cannot prove identity and fails closed. If previously
known metadata becomes unavailable, identity cannot be established and fails closed.
A changed authorization generation, paired RETURN, replacement TAKE, closure or
material recovery eligibility change still prevents recording. Existing permits
also fence same-process logout. No arbitrary metadata revision alone is compared.

intentStartedAt is invocation time, not the disconnect time. measuredAt is the
unchanged CLLocation timestamp. Normal RETURN occurredAt is read after acquiring
the SQLite write lock. Freshness is revalidated against that final time. Existing
Recovery/Reconciliation preserve the original event and use the new time only for
the separate verification attempt, as before. No backend contract changes.

Successful local recording still does not imply server admission. Existing wake,
background uploads and retry protocols remain responsible for synchronization.
A post-commit scheduling failure reports the event as safely stored for retry.

## Configuration and privacy review

Both effective wrappers use the Hebrew When In Use purpose statement explaining a
brief RETURN measurement, including automatic background invocation. Both retain
remote-notification and add location background capability. No Always keys exist.
Tests generate real disposable wrapper plists with synthetic public Firebase data;
no application compilation or signing is needed for this check.

The repository privacy policy sections 3.5, 5.2, 6.1, 6.2 and 12.4 already describe
point-in-time RETURN evidence, server home verification, temporary local queue
storage and absence of continuous route tracking. No legal text was changed.
The OS capability permits background location; the implementation limits updates
to each bounded acquisition. App Store Connect privacy labels were not accessed
and cannot be verified from the repository. Before release, the owner must verify
that precise-location collection/use disclosures and review notes cover this
existing evidence transfer and automatic background RETURN. This is a technical
consistency review, not a legal-compliance certification.

## Local diagnostics

Only closed stages/reasons, authorization/accuracy categories, Core Location error
codes and bounded elapsed milliseconds are logged under FCA_RETURN_LOCATION.
No coordinates, addresses, identity, event payloads or credentials are logged.

PowerShell (existing USB pairing and usbmuxd bridge required):

```powershell
wsl -d Ubuntu-24.04 -- env USBMUXD_SOCKET_ADDRESS=127.0.0.1:27015 idevicesyslog --no-colors | Select-String 'FCA_RETURN_LOCATION'
```

Acquisition success and local-recording success are separate stages. A callback only
after SQLite COMMIT marks persistence; subsequent classified Recovery/Reconciliation
outcomes use persistedProcessingOutcome, never recordingFailed. A normal completed
processing pass uses recordedAwaitingSynchronization; neither claims server acceptance. OSLog delivery
and process lifetime in the final integrated signed build remain device checks.

## Later signed Development acceptance plan

No signed build is authorized by this implementation task. After local review and
separate approval, validate actual Xcode compilation and install a signed Dev build.
Use a test account/vehicle and retain the existing queue; do not reset data.

1. Verify sequential notification then location permission, both grant/deny paths,
   interruption by inactivity, existing installation first request, repeated launch
   and status refresh after returning from Settings.
2. Create RETURN shortcuts with only FCA — Return Vehicle and the selected Vehicle.
   Preserve TAKE shortcuts. Do not publish/update iCloud links yet.
3. TAKE/RETURN online; then TAKE/RETURN offline. Confirm local success before network
   restoration and ordered server acceptance afterward.
4. Repeat background, locked, Bluetooth disconnect offline/locked, after closing
   FCA and Shortcuts, and a reproducible automatic cold invocation with confirmed
   new PID. Test actual vehicle Bluetooth and CarPlay separately from JBL/Time tests.
5. Test outside-home admission rejection and existing explicit Recovery/Reconciliation;
   verify original evidence remains unchanged.
6. Test denied/restricted/disabled location, reduced accuracy, timeout, cancellation,
   duplicate invocations and account/vehicle/TAKE changes during acquisition. Failures
   must create no event or sequence. Repeat successful TAKE/RETURN cycles.

Prior POC successes do not establish these integrated queue/server tests. iOS may
suspend or decline background execution; When In Use + background capability does
not guarantee launch after force-quit or in every cold/locked scenario.

## Exact local change inventory

- `.github/workflows/ios.yml`
- `ios/Checks/VehicleSyncChecks.swift`
- `ios/Config/Info.Dev.plist`
- `ios/NATIVE_DEVICE_SETUP.md`
- `ios/OFFLINE_EVENT_QUEUE.md`
- `ios/Sources/FamilyCarAgent/OfflineEvents/VehicleAppIntents.swift`
- `ios/Sources/FamilyCarAgent/OfflineEvents/VehicleEventQueue.swift`
- `ios/Sources/FamilyCarAgent/OfflineEvents/VehicleSessionRuntime.swift`
- `ios/Sources/FamilyCarAgent/Push/NativePushService.swift`
- `ios/Sources/FamilyCarAgent/Settings/SettingsScreen.swift`
- `ios/Sources/FamilyCarAgent/Vehicles/VehicleConnectionSetupView.swift`
- `ios/Checks/NativeReturnLocationChecks.swift`
- `ios/Checks/run-native-return-location-checks.sh`
- `ios/Checks/test-native-return-location.py`
- `ios/NATIVE_RETURN_LOCATION.md`
- `ios/Sources/FamilyCarAgent/OfflineEvents/LocationPermissionGate.swift`
- `ios/Sources/FamilyCarAgent/OfflineEvents/LocationPermissionService.swift`
- `ios/Sources/FamilyCarAgent/OfflineEvents/ReturnLocationAcquisition.swift`
- `ios/Sources/FamilyCarAgent/OfflineEvents/ReturnLocationAcquisitionCore.swift`

## Initial local verification before focused corrections (2026-11-26)

- Native acquisition: 23 lifecycle/validation scenarios passed.
- Permission sequencing: 6 scenarios passed.
- Original validator: 1,568 equivalence cases plus fixed boundary/reason checks passed.
- Vehicle queue: all existing persistence, sequence, authorization and process-crash checks passed.
- Vehicle sync: 25 reported groups passed, including the new two-writer native RETURN
  preparation/commit test and all existing Recovery, Reconciliation, SQLite migration,
  rollback, metadata and session-anchor checks.
- Native device setup: 9 reported groups passed; existing four Shortcut URLs verified.
- Python: 33 tests passed (5 native RETURN, 7 Recovery, 8 Production policy,
  9 native push policy, 4 wrapper tests).
- Effective Development/Production wrapper configuration verified using synthetic inputs.
- iOS-target Production syntax parsing passed. This is NOT iOS SDK type checking.
- Workflow YAML and git diff --check passed. CI change is one additional check invocation.
- TAKE Intent definition compared with HEAD and unchanged. No Shortcut URL replacements.

Full Xcode compilation, native UIKit/Core Location integration, real permission dialogs,
physical-device queue recording and server E2E synchronization remain unverified for
this implementation. No CI, signing, app build or external deployment was performed.
The existing queue suite also reports its pre-existing limitation: if every durable
logout-fence write fails, a fresh process cannot infer that failed logout. This work
does not change storage protection or claim to resolve total storage-write failure.

## Focused review corrections

The synchronization regression fixtures now include ordinary TAKE transport-state
changes, self-anchor resolution, ambiguous remapping/closure and unrelated metadata.
A separate OS-thread SQLite connection holds BEGIN IMMEDIATE while the production
clock path waits; expired evidence must roll back without consuming a sequence.
Two independent queue connections compete with independent recording permits, so
the test is not serialized by an in-memory lock. Exactly one RETURN may commit.
Permission tests include a thrown notification error followed by inactive/active
transitions. Recording tests distinguish pre-commit failure and post-commit outcomes.
These remain local tests, not proof of native iOS permission dialogs or Xcode compilation.

## Verification after focused corrections (2026-11-26)

- 23 acquisition cases and 1,568 validator equivalence cases passed unchanged.
- 7 permission scenarios (including thrown notification error) and 6 recording
  diagnostic cases passed.
- 27 synchronization groups passed, including semantic identity tests and actual
  SQLite write-lock contention using the production clock and competing writers.
- Queue persistence/authorization/crash regressions and 9 device-setup groups passed.
- 29 Python tests passed in this correction run: native RETURN 5, Recovery 7,
  Production push policy 8, native push policy 9.
- iOS Production syntax parsing and git diff --check passed. No Xcode compilation,
  CI, app build, signing, publication or device integration was performed.

Files changed by this correction pass (within the existing 19-file implementation):
- ios/Sources/FamilyCarAgent/OfflineEvents/VehicleEventQueue.swift
- ios/Sources/FamilyCarAgent/OfflineEvents/VehicleSessionRuntime.swift
- ios/Sources/FamilyCarAgent/OfflineEvents/VehicleAppIntents.swift
- ios/Sources/FamilyCarAgent/OfflineEvents/ReturnLocationAcquisition.swift
- ios/Sources/FamilyCarAgent/OfflineEvents/ReturnLocationAcquisitionCore.swift
- ios/Sources/FamilyCarAgent/Push/NativePushService.swift
- ios/Checks/VehicleSyncChecks.swift
- ios/Checks/NativeReturnLocationChecks.swift
- ios/Checks/test-native-return-location.py
- ios/NATIVE_RETURN_LOCATION.md

Remaining limitations: native permission dialogs and CLLocationManager integration
need the separately approved Xcode/device stage. Unknown-to-other-anchor resolution
and loss of previously known metadata remain fail-closed; this is not a network
requirement for ordinary offline RETURN. The native acquisition lifecycle and
all location thresholds are unchanged from the reviewed implementation.
