# Dev authentication implementation and review

## Status and setup gates

Local implementation, not a claim of successful live Google/Apple authentication.
No cloud configuration, provider linking configuration, Production identity,
provisioning profile, backend, schema, Android or Web was changed.

Before physical Dev testing, the operator must:

1. Set `FCASupabasePublishableKey` in `Config/Info.Dev.plist` to the **public**
   `sb_publishable_...` key for `jouhqvbxhsvkluwkqmdg`. It is intentionally empty.
   Never use `sb_secret_...`, service-role credentials, an Apple private key or
   an App Store Connect API key. Legacy anon JWTs are deliberately not accepted
   by this small iOS configuration validator. A publishable key is public client
   configuration, but its association with Dev must be verified by the operator.
2. Verify Supabase **Dev** redirect allowlisting for
   `com.familycaragent.app.dev://auth/callback`, including its per-attempt `nonce`
   query parameter. Match the existing Android redirect policy, not a broad
   unrestricted scheme wildcard. No Dashboard settings were changed here.
3. Keep Google's provider callback directed to Supabase Dev's
   `/auth/v1/callback`; the iOS URL above is the subsequent app redirect.
4. Verify the Apple provider accepts `com.familycaragent.app.dev` as a native
   ID-token audience, nonce validation is enabled, and the existing Dev App ID
   and provisioning profile authorize `com.apple.developer.applesignin=Default`.
   Provider/capability activation was reported by the operator, not independently
   verified in this run. Do not create Services IDs or API keys for this task.
5. Rebuild. Configuration is embedded at build time, not a runtime environment
   switch. The custom callback is handled by ASWebAuthenticationSession; arbitrary
   unsolicited deep links cannot initiate code exchange. Process termination
   discards pending login and requires a new attempt.

## Audited authoritative flow

Android sources: `auth/SessionStore.kt`, `ui/LoginRoute.kt`, `ui/EntryActivity.kt`,
`ui/OnboardingModel.kt`, `net/FcaApi.kt`, `net/OnboardingFailure.kt` under
`android/app/src/main/java/il/fca/companion/`.

Web sources: `web/src/auth/{authService,AuthContext,onboardingDraft}.ts[x]`,
`web/src/lib/supabase.ts`, onboarding submitters and `web/src/App.tsx`.
Web uses Supabase JS PKCE/persistence/auto-refresh; native Android uses a direct
REST store with Keystore and owner checks. iOS follows the latter architecture
with Foundation, AuthenticationServices, CryptoKit and Security; no added SDK.

Backend authority: `backend/auth_service.py`, `deletion_gate.py`, `main.py`,
`family_creation_service.py`, `join_family_service.py`, `database.py`.
JWT ES256 signature/issuer/audience/expiry/role/UUID checks and the live deletion
gate remain server-owned. No client-supplied family or email establishes identity.

The native state transitions are:

- Intro chooses existing/create/join BEFORE provider login.
- Google PKCE or native Apple -> Supabase session (not yet activated for FCA).
- Existing -> GET `/api/me` -> activate -> Ready.
- Create -> family name -> POST `/api/onboarding/create-family/address`
  (`home_address`) -> explicit address confirmation -> name + driving consent ->
  POST `/api/onboarding/create-family` (`family_name`, `user_name`,
  `address_resolution_token`) -> `/api/me` and `/api/family` -> Success -> Ready.
- Join -> POST `/api/onboarding/join-family/start`, then server-driven
  `family-name`, `address`, `address-confirmation`, `code`, `complete` with the
  existing request fields. Server step/counters/15-minute lock are authoritative.
  `INVALID_JOIN_STEP` reconciles through `start`; it does not reset counters.
- Successful creation/join followed by failed bootstrap retries bootstrap only,
  not the completed mutation. Uncertain network outcomes still rely on server
  uniqueness/mapping guards; the client does not claim an exactly-once mutation.
- `/api/me` exact missing-account errors clear local session and return to Intro
  with create/join guidance. `ACCOUNT_UNAVAILABLE` clears local state. Other
  bootstrap failures retain credentials for Retry; no fake ready/account data.
- Restart restores only an activated session, verifies Apple credential state
  when applicable, then bootstraps. Incomplete forms are memory-only and must be
  restarted; the server retains authoritative join state. Ordinary resume does
  not reconstruct navigation or trigger global loading. Apple credential-state
  checks occur on foreground/revocation notification without inventing readiness.
- Logout fences late results, cancels pending login and erases the Keychain item.
  As in Android SessionStore, this is local logout, not a promise to revoke every
  Supabase session on every device. No iOS Push/Companion installation exists in
  this foundation. A Keychain deletion failure is surfaced and is NOT a claim of
  successful persistent logout; unlock the device and retry before account reuse.

Known existing discrepancy: Android `AddressVerification.resolve` also reads
latitude/longitude, while current `main.py` create-address response contains only
normalized/display address and resolution token. iOS consumes the actual server
contract; neither Android nor backend was changed to address that discrepancy.

## Identity policy and isolation

No `linkIdentity`, email matching, custom merging, family transfer or linking
configuration change. Supabase's built-in verified-email linking is accepted per
the approved decision. Same returned Supabase UUID means the same FCA identity;
a different UUID (including Apple's private relay) requires independent FCA
onboarding. Matching email alone never changes that decision.

The UUID in Supabase's TLS-authenticated token response is the client owner;
the backend independently verifies the JWT. `/api/me` supplies the authoritative
FCA user/family. Tokens, provider email/full name and raw server error text are
not used to manufacture a family or profile.

Generation fences protect login, refresh and backend responses. Refresh requests
are coalesced; refreshed UUID must match the stored owner. A network failure is
retryable, not proof of revocation. Confirmed invalid refresh/session credentials
clear local state. Tokens refresh on demand within 60 seconds of expiry, matching
Android; there is no polling timer or artificial splash delay. Backend 401 retries
once after refresh. Ready-state resume does not indiscriminately call `/api/me`.

Keychain stores access/refresh tokens, owner, expiry, activation marker and (for
Apple) the credential identifier needed for credential-state checks. Provider
tokens, authorization codes, nonce/verifier, email and forms are not persisted.
`WhenUnlockedThisDeviceOnly`, synchronization disabled, no shared access group:
foreground-only auth is sufficient here; no migration to another device or iCloud
sync is intended. Service name includes the Dev bundle ID and Supabase host.

Google uses 32-byte SecRandom verifier/nonce, SHA-256 S256, strict scheme/host/path,
no userinfo/port/fragment, unique nonce/code parameters, ten-minute expiry and
single consumption before exchange. Apple receives SHA-256(raw nonce) and an
attempt state; Supabase receives the identity token and raw nonce. Native callbacks
are tied to their controller/attempt, including timeout/cancellation. No raw
authentication errors or credentials are logged. HTTP is ephemeral, HTTPS-only
via fixed Dev URLs, with redirects disabled and bounded timeouts.

## Environment/release boundaries

One shared codebase; only Dev is selectable. `xtool.yml`, Info.Dev.plist and
Dev.entitlements are the Dev build configuration. `AppEnvironment.current()`
rejects other bundle IDs; `FCA_PRODUCTION` explicitly produces a compile error.
Debug versus Release does not choose services. There is no Production build
configuration or runtime switch and no Production deployment is authorized.

A future Production release requires separately reviewed bundle/App ID,
backend/Supabase project + public key, callback allowlist/URL scheme, Apple token
audience, entitlement file, provisioning identity/profile, Keychain namespace,
and device/security QA. Do not reuse Dev signing profiles or shared Keychain
access groups. No Production identifier/provider was registered or enabled.

## Local validation and limits

From PowerShell: `wsl -d Ubuntu-24.04`, then:

```bash
cd /mnt/c/Projects/family-bot-agent/ios
bash Checks/run-auth-checks.sh
xtool dev build
python3 Checks/check-built-config.py
git diff --check
```

The script compiles the actual session/API/EntryModel logic with Swift 6 and
warnings-as-errors and runs deterministic mock transports/vaults. Linux uses
minimal ObservableObject/Published test shims, not a substitute for UI testing.
It checks callbacks/replay/expiry, owner isolation, concurrent refresh, late
responses after logout, vault failures, safe errors, response contracts, same-ID
and private-relay/different-ID cases, and existing/create/join bootstrap rules.
It makes no FCA/Supabase/Apple requests. The unsigned xtool build compiles the real
Apple frameworks and applies the entitlement; it does not validate provisioning.

CryptoKit/Security runtime tests (`Checks/CryptoCheck.swift`, RFC 7636 known vector,
nonce hash and random encoding) require macOS/iPhone and are explicitly NOT RUN
on Linux. On macOS run `SWIFT_BIN=$(command -v swiftc) bash Checks/run-auth-checks.sh`.
Actual Keychain read/write/lock/relaunch, native sheets, URL routing and OS
cancellation need device verification; fake-vault tests do not prove those APIs.

Physical Dev matrix, not yet executed:

- Google success/cancel/timeout/interrupted app, forged/replayed callback rejection.
- Apple success/cancel, missing-token failure, credential revocation and relaunch.
- Google + Apple returning the same UUID -> same FCA account, no second membership.
- Apple Hide My Email returning another UUID -> separate account, no copied data.
- Same email with different UUID -> still separate; never infer linking from email.
- Existing family, missing account, create/join completion, server lock and retry.
- Token expiry/offline recovery, logout during request, account A -> B -> relaunch.
- Keychain inaccessible/deletion failure, app force quit, screen lock and foreground.

Do not log tokens or identity-token payloads to perform this matrix. No live
provider behavior, auto-linking outcome, real account creation or physical-device
authentication has been claimed as tested.
