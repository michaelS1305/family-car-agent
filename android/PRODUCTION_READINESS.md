# Android Production — local implementation, not activation

## Identity and build inputs

Production is a **new install**, `com.familycaragent.app`, launcher name `Family Car Agent`.
Development remains `il.fca.companion.dev` / `FCA Companion Dev`. Kotlin namespace remains
`il.fca.companion`. Neither old app data nor old FCM tokens are migrated.

The owner-supplied JSON is copied unchanged to ignored `app/src/prod/google-services.json`.
Gradle and runtime require project `family-car-agent`, sender `249909620080`, Android app
`1:249909620080:android:c0f07c3b74400bfaee33b5`, package `com.familycaragent.app`.
Development JSON is unchanged. No service-account material belongs in Android.

Production backend remains `https://family-car-agent.onrender.com`, Supabase remains
`https://xrgijytfigcuxmdktvmd.supabase.co`. Before device authentication, the owner must allow
`com.familycaragent.app://auth/callback` in **Production Supabase** redirects and verify the
existing Google OAuth provider configuration. Authentication remains Supabase OAuth/PKCE,
not Firebase Auth. The website legal/support routes remain intended public destinations.
Production Maps stays disabled; notification permission, logout, account deletion and vehicle
identification behavior are unchanged.

## Branding

The old launcher inset retained only 42% of the adaptive canvas, compounded by artwork padding.
The approved PNG is copied byte-for-byte, without changing the logo. The launcher uses an 8%
inset on each side (84% canvas); tests measure the opaque navy artwork within the 66dp safe
circle on the 108dp adaptive canvas. The cream tile may be masked; the family/car must not be.
Splash artwork is unchanged. Both flavors share the launcher. There was no monochrome layer;
none has been invented. Verify circle, squircle and themed launchers on a physical device.
Only the Settings back image is mirrored; its right alignment, target and action are unchanged.

## Trusted backend configuration

| Environment | Android | iOS |
| --- | --- | --- |
| Development | family-car-agent-dev | family-car-agent-dev |
| Production | family-car-agent | family-car-agent |

API and worker use the same loader. Each bounded worker pass processes both native platforms
in its environment's single project. Production Android FCM is restricted to
`com.familycaragent.app`; Production APNs topic remains `com.familycaragent.app`.
Client project/environment/package overrides are not accepted. Existing stored provider
identity must match the trusted environment. Missing Production inputs fail closed.

Development `NATIVE_PUSH_*` credentials and keys stay unchanged. Production reuses the
**existing iOS Production cohort** (historical environment variable names retained):

- `NATIVE_PUSH_ENVIRONMENT=prod`
- `NATIVE_PUSH_ANDROID_PACKAGE=com.familycaragent.app`
- `SUPABASE_URL=https://xrgijytfigcuxmdktvmd.supabase.co`
- `NATIVE_PUSH_IOS_PROD_ENABLED=true` — now gates this shared Production cohort
- `NATIVE_PUSH_IOS_PROD_PROJECT=family-car-agent`
- `NATIVE_PUSH_IOS_PROD_CREDENTIALS_FILE` — absolute secure server file path
- `NATIVE_PUSH_IOS_PROD_KEY_ID`, `NATIVE_PUSH_IOS_PROD_ENCRYPTION_KEY`,
  `NATIVE_PUSH_IOS_PROD_FINGERPRINT_KEY` — retain existing values; do not rotate or regenerate

The service account remains `fca-push-prod@family-car-agent.iam.gserviceaccount.com`.
Keep existing push/reminder enable flags and database configuration unchanged unless separately
approved. API and worker must receive identical configuration during an owner-controlled rollout.
No new database migration is required by this change; existing schema prerequisites still apply.

Old Production Android registrations in `family-car-agent-dev` cannot be adopted by the new app.
Before cutover, inventory those records using an owner-authorized maintenance operation, distinguish
them from Development and iOS records, and retire their installations/challenges/deliveries through
the existing cleanup semantics. Do not rewrite project IDs or re-encrypt tokens into a new cohort.
The new app registers a new installation after login. Historical records are rejected by routing;
pending old-project deliveries are not dispatched through Production credentials. Existing expiry
cleanup remains. No live cleanup or schema operation was performed here.

## Signing and CI (prepared only)

The existing `android.yml` keeps Dev/Prod debug validation. A **manual** `production_release=true`
input adds a dependent `production-release` job, environment `android-production`, with no publishing.
Configure owner approvals for that GitHub environment before use. No workflow was executed.

Required GitHub secrets:
- Existing `FCA_FIREBASE_DEV_GOOGLE_SERVICES_JSON` unchanged.
- `FIREBASE_PROD_GOOGLE_SERVICES_JSON_B64`: the new approved **raw JSON**, despite the legacy suffix.
- `FCA_ANDROID_PROD_SUPABASE_PUBLISHABLE_KEY`: actual Production public key (never a service key).
- `FCA_ANDROID_UPLOAD_KEYSTORE_B64`: owner-provided upload keystore, Base64.
- `FCA_ANDROID_KEYSTORE_PASSWORD`, `FCA_ANDROID_KEY_ALIAS`, `FCA_ANDROID_KEY_PASSWORD`.

The keystore is written only to the runner temporary directory, removed on completion, never
uploaded. Only the AAB is retained for seven days. Owner must supply signing material and verify
Play App Signing, upload certificate, version code/name, store declarations and signing fingerprints.
No keystore/certificate/password was generated, and no signed AAB or Play publication is claimed.

Local signed build, after supplying those signing values as process environment variables and
`FCA_ANDROID_KEYSTORE_FILE` as an absolute file path outside Git:

```powershell
cd C:\Projects\family-bot-agent\android
.\gradlew.bat --no-daemon -PfcaProductionRelease=true :app:bundleProdRelease
```

Without explicit selection and signing inputs, Production Release fails. Test-fixture public keys
are also rejected for Release. Do not use Gradle debug logging/build scans with signing inputs.

## Local checks

```powershell
cd C:\Projects\family-bot-agent\android
.\gradlew.bat --offline :app:testEnvironmentConfiguration :app:testDevDebugUnitTest :app:testProdDebugUnitTest :app:lintDevDebug :app:lintProdDebug :app:assembleDevDebug :app:assembleProdDebug
```

Backend offline tests: `.venv/Scripts/python.exe -B backend/tests/run_native_push_offline.py`
from repository root. This runner blocks network/database access; PostgreSQL integration tests skip.
iOS regression: `bash Checks/run-native-push-checks.sh` from `ios/` in the existing Swift environment.

Before real Production E2E: separately approve infrastructure configuration/activation, deploy API
and worker together, complete controlled old-registration cleanup, configure OAuth redirects and
owner signing, then verify a real Android install/login/permission/token refresh/logout/deletion,
vehicle and booking notifications plus iPhone Production regression. Mocks are not delivery proof.

## Files in this Android implementation

- `.github/workflows/android.yml`
- `android/.gitignore`, `android/app/build.gradle.kts`
- `android/app/src/main/java/il/fca/companion/ui/SettingsScreen.kt`
- `android/app/src/main/res/drawable/fca_launcher_foreground.xml`
- `android/app/src/main/res/drawable-nodpi/fca_launcher_logo.png`
- `android/app/src/prod/java/il/fca/companion/push/PushPlatform.kt`
- `android/app/src/test/java/il/fca/companion/EnvironmentAuthTest.kt`
- `android/app/src/test/java/il/fca/companion/LaunchBrandingTest.kt`
- `android/app/src/testProd/java/il/fca/companion/push/ProductionPushIdentityTest.kt`
- `backend/native_push_security.py`, `backend/native_push_process.py`
- `backend/tests/test_native_push_isolation.py`, `backend/tests/test_native_push_dual_project.py`
- This runbook.

Ignored local inputs updated: `android/fca.prod.properties` (callback only) and
`android/app/src/prod/google-services.json`. Prior uncommitted iOS/backend work was preserved.

## Validation recorded 2026-11-17

- Android Development: 410 unit tests, zero failures/errors/skips.
- Android Production: 411 unit tests, zero failures/errors/skips.
- Environment guard tests and both Debug APK assemblies passed.
- Release negative tests: missing explicit opt-in and missing owner keystore both rejected.
- Backend: 146 discovered, 66 passed, 80 database-dependent tests skipped; offline runner blocks
  network and database connections.
- iOS: mock state/registration checks, 17 Python checks and Dev/Prod Swift configuration checks
  passed. The certificate test's synthetic OPENSSL3_UNAVAILABLE diagnostic is expected; it does
  not validate real Apple signing on Windows/WSL.
- Approved launcher PNG is byte-identical to the supplied original; safe-zone resource test passed.
- Workflow YAML parsed locally. No GitHub Actions execution or real signed AAB validation.
- No emulator/device installation, physical launcher inspection or real Push E2E performed.
- Lint completed: Development 0 errors, 285 warnings, 2 hints; Production 0 errors, 285 warnings, 2 hints. Warnings were not suppressed.
- `git diff --check` passed.
