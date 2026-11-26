# Development-only native offline location POC

Status: local diagnostic implementation only. No signed IPA, CI or physical-device verification.

## Isolation and behavior

`NativeLocationPOC.swift`, `NativeLocationPOCCore.swift` and the permission view insertion
use `DEBUG && !FCA_PRODUCTION` guards. The production wrapper removes the experimental
When In Use purpose string and `location` background mode while preserving
`remote-notification`. No signing settings are changed. Test the generated production
plist, not only the template. No Production RETURN validator or event flow is changed.

The diagnostic Intent is `FCA Dev — Native Location POC`, has no parameters and uses
`openAppWhenRun = false`, with the same default authentication policy as RETURN.
It does not call the session runtime, queue, account/device setup or Backend.
Normal app lifecycle code remains unchanged; a cold app launch may still execute its
existing startup work. The diagnostic itself introduces no network calls.

A foreground button on vehicle connection setup requests When In Use permission only.
It never starts updates or reads a cached location. No Always or temporary-full-accuracy
request is made. The automatic diagnostic Intent never requests permission.

Each invocation retains its own MainActor manager/delegate and ContinuousClock deadline.
Updates stop after the first valid measurement, terminal error, cancellation or 15 seconds.
`locationUnknown` and invalid measurements may improve within that same deadline.
The shared original validator evaluates real callback samples at Date() evaluation time:
valid coordinates, accuracy > 0 and <= 100m, age 0...30s, no simulated source.
Missing sourceInformation remains allowed only under the existing native policy.
Reduced accuracy is logged; it does not relax the sample accuracy limit.
Cleanup precedes exactly-once completion; late callbacks cannot change the outcome.
An OS process kill cannot guarantee a final cleanup log or returned result; it is not success.

## Time semantics (future integration requires separate approval)

This POC creates no event and has no occurredAt. It evaluates CLLocation.timestamp
against actual evaluation time, not Intent entry time. A future RETURN integration must
separate intentStartedAt, measuredAt and occurredAt. Intent entry is not proof of exact
Bluetooth disconnection time. Existing queue/server rules reject location_at after
occurred_at. No timestamp, queue, Recovery or Reconciliation semantics are changed here.

## Local checks

- `python ios/Checks/test-native-location-poc.py`
- `bash ios/Checks/run-native-location-poc-checks.sh`
- existing return-location, vehicle-queue and vehicle-sync checks
- existing production-push and return-recovery Python contracts

The pure Swift checks exercise the actual acquisition state machine and existing validator.
Python checks verify the actual generated Production plist and source contracts.
Neither replaces Xcode typechecking of CoreLocation/AppIntents nor physical iPhone tests.
The existing iOS workflow runs both POC check scripts during validation. A temporary
trusted-repository workflow_dispatch exception allows Development signing only on
codex/native-offline-location-poc. It must never be merged into develop or main.

## Device preparation AFTER separate build/signing approval

1. Build/sign the existing Development target through the existing signing infrastructure.
   Keep bundle `com.familycaragent.app.dev`; do not replace Production or reset data.
2. Open FCA Dev, navigate to vehicle connection setup and press the Development permission
   button. Grant When In Use. Check Precise Location. This button does not acquire a fix.
3. Do not alter existing TAKE/RETURN shortcuts. After owner approval, create a separate
   diagnostic Shortcut with only `FCA Dev — Native Location POC`, no Current Location
   variable, no vehicle selection and no extra location action.
4. Observe `intentEntered` separately from `result=acquired`; only acquired proves a valid fix.
5. Disable internet connectivity while retaining the Bluetooth/CarPlay transport and Location
   Services required for the case. Record manual context and iOS version, not coordinates.
6. Test in sequence: foreground; immediate background; background after at least 2 minutes
   (repeat after 5 minutes); locked after first unlock; suspended/cold OS-terminated process;
   user force-quit separately. Do not claim waiting proves OS termination.
7. Only after approval, make separate Bluetooth/CarPlay disconnect diagnostic automations.
   Leave all real vehicle automations unchanged. Avoid concurrent real RETURN during diagnostics.
8. Repeat each critical success at least 3 times, including meaningful background waiting.
   Record acquired/timeout/error, elapsed time, authorization and cleanup. Test denied permission,
   reduced precision and no usable fix. Before-first-unlock is a separate unsupported-storage case.
9. Do not grant Always as part of this experiment. If When In Use fails in a required context,
   stop and report logs before deciding any capability/authorization change.

No operation above has been executed on the physical device by this task.

## Windows/WSL live logs

Run in PowerShell with the paired iPhone connected over USB:

```powershell
wsl -d Ubuntu-24.04 -- env USBMUXD_SOCKET_ADDRESS=127.0.0.1:27015 idevicesyslog --no-colors 2>&1 | Select-String -SimpleMatch 'FCA_NATIVE_LOCATION_POC'
```

Optional local capture of only matching lines:

```powershell
wsl -d Ubuntu-24.04 -- env USBMUXD_SOCKET_ADDRESS=127.0.0.1:27015 idevicesyslog --no-colors 2>&1 | Select-String -SimpleMatch 'FCA_NATIVE_LOCATION_POC' | Tee-Object -FilePath "$env:TEMP\fca-native-location-poc.log"
```

Prefix: `FCA_NATIVE_LOCATION_POC`; subsystem `com.familycaragent.app.dev`;
category `native_location_poc`; level notice. Values are fixed categories or elapsed time/
Core Location error code, never locations, addresses, identities, tokens or raw errors.
OSLog visibility and cold/locked execution remain physical-device acceptance gates.
A successful foreground fix does not prove background eligibility. Fifteen seconds is an
experimental ceiling, not a guaranteed Apple App Intent execution budget.

## Local verification results

- Native acquisition core: 23 executable Swift scenarios passed; Production core AST exclusion passed.
- POC Python policy/configuration checks: 7 passed, including actual generated Production plist.
- Existing validator: 1,568 equivalence cases plus rejection/boundary checks passed.
- Existing vehicle queue checks: passed (suite does not report an individual test count).
- Existing vehicle sync checks: 24 PASS groups, including Recovery, Reconciliation and SQLite migration/rollback.
- Existing production-push policy: 8 passed; return-recovery contract: 7 passed;
  App Intent wrapper: 4 passed.
- iOS-target Swift syntax parsing passed. Full adapter typecheck is BLOCKED locally:
  installed cross-SDK/toolchain reports missing SwiftShims. No Xcode compilation claimed.
- git diff --check passed. No commit, CI, IPA build, signing or device test performed.

WSL regression scripts were executed with normalized in-memory line endings, existing Swift
at /home/micha/.local/share/swiftly/bin/swiftc and existing SQLite headers from the installed
Apple SDK. No dependencies were installed and no existing scripts were edited.
The queue suite reports its existing limitation: if all durable logout fence writes fail,
a fresh process cannot infer that failed logout. This POC does not change that behavior.

Publication review: workflow policy 21/21, classifier 17/17, POC Python 8/8, Native Push policy 9/9 and Production signing policy 8/8 passed locally. Physical-device and signed-IPA results remain pending.
