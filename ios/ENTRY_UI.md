# Dev entry UI (2026-10-25)

Windows `ios/` is canonical. No Apple authorization, nonce/state validation,
token exchange, entitlements or provider diagnostics were changed in this pass.
Android entry files and the two supplied screenshots are visual references.
No iPhone rendering claim is made from compilation or source inspection.

## Screens and routes

`EntryScreens.swift` implements Intro, Login and a temporary onboarding destination.
Intro distributes measured content and spare safe-area height in the Android
proportions. Short viewports / accessibility sizes may scroll. Login adds a native
black ASAuthorizationAppleIDButton below the original Google image. Its target
invokes the existing NativeProviders implementation, not a second Apple flow.
The legal links open local sheets containing the exact Android LegalCopy texts.
The `fca-entry-legal` links are internal document identifiers, not external policy URLs.

All three LoginRoute values remain distinct. The new UI calls
`login(apple:previewOnboarding: true)`. Create and join stop at the placeholder:
no join-start, address, creation, completion or membership mutation requests.
Existing-account login still calls `/api/me` and activates only a valid account.
Back from the placeholder keeps the unactivated session and selected route;
another provider attempt uses the existing session-clear boundary. Logout still
clears it, and unactivated sessions are not restored after process termination.
The old onboarding domain methods remain, but this UI has no controls invoking them.

## Temporary resources

Only `Sources/FamilyCarAgent/Resources/EntryAssets/` is copied as raw resources:

- `intro_logo.png`: rendered at 1119 x 1099 from the existing
  `assets/branding/app-icon/fca_logo_intro.svg` using locally available librsvg/cairo.
  Original paths, colors and canvas were retained; no source asset was modified.
- `login_logo.png`: byte-identical Android `drawable-nodpi/fca_logo.png`.
- `google_sign_in.png`: byte-identical Android `drawable-nodpi/google_sign_in.png`;
  its 720:160 aspect ratio is preserved with scaledToFit.

`Package.swift` excludes the existing xcassets catalog and copies EntryAssets.
The catalog and all 36 imagesets remain untouched. This is a Dev entry-screen
resource choice, not the permanent asset pipeline. Replace EntryImage's loader
and this one resource declaration when that separate work is approved.

## Google redirect hypothesis and external prerequisite

The operator reports Supabase Dev has Site URL
`https://family-car-agent-web-dev.onrender.com/` and an exact redirect allowlist
entry `com.familycaragent.app.dev://auth/callback`.

The application DOES explicitly send `redirect_to`, to:
`com.familycaragent.app.dev://auth/callback?nonce=<per-attempt-random-value>`.
The registered scheme and ASWebAuthenticationSession callback scheme match.
PendingAuthorization checks scheme/host/path, unique nonce and code, expiry,
single consumption and PKCE. Session exchange remains `/auth/v1/token?grant_type=pkce`.

The reported exact allowlist entry does not match the query-bearing URL.
Upstream Supabase Auth `internal/utilities/request.go`, `IsRedirectURLValid`
matches the query as part of the URL; `GetReferrer` falls back to SiteURL when
the redirect (and referrer) are rejected. This explains the observed Web landing,
subject to the operator's configuration being complete and the hosted version
having this behavior. The live hosted configuration/version was not independently
queried. No real login was performed in this task.

Required operator-approved Dev change: add a narrowly scoped redirect pattern
covering the nonce query on this exact scheme, host and path. For example:
`com.familycaragent.app.dev://auth/callback?nonce=*`.
Supabase glob `?` matches one character (the query delimiter here); the client
still validates the exact path and nonce. Do not add a scheme-wide wildcard.
Keep the existing base entry and Site URL; the latter belongs to Web/PWA.
Do not replace this fix by dropping the nonce check or accepting a Web callback.
No Supabase or Google dashboard configuration was modified.

References inspected:
- https://supabase.com/docs/guides/auth/redirect-urls
- https://github.com/supabase/auth/blob/master/internal/utilities/request.go

After configuration approval and a separately approved signed installation, test
Google success/cancel on all routes, native return, session/route restoration,
Apple regression, small-screen layout, RTL, Dynamic Type and both legal links.
Unit tests/builds do not establish live OAuth success.

## Local checks

- `bash Checks/run-auth-checks.sh`: actual session/EntryModel mock checks plus
  native redirect, route, no-onboarding-requests and late callback regression tests.
- `python3 Checks/check-entry-resources.py`: source assets/legal copy checks.
- `python3 Checks/check-entry-resources.py xtool/FamilyCarAgent.app`: verify copied
  image bytes in a built app; does not prove physical rendering.
- `python3 Checks/check-built-config.py`: public Dev configuration only.

Never use the broad `fca-ios-run.sh` sync/install wrapper for this task.

## Status at handoff

Integration resumed with explicit authorization on 2026-10-25. Final Dev source:
`/home/micha/FamilyCarAgent`. Existing files were backed up under
`/home/micha/fca-entry-ui-backups/20261025T144445Z`; manifest.json records old/new
hashes and protected files. Only the listed entry sources/checks/docs/images were
copied. The WSL manifest retained `.copy("Resources/Assets.car")` and added
`.copy("Resources/EntryAssets")`; the catalog remains excluded. Windows intentionally
does not reference an Assets.car that has not been integrated there. Do not overwrite
the WSL manifest using a broad sync or the old readiness restoration script.

118 auth/route checks passed both with and without DEBUG. AppEnvironment checks,
Apple diagnostic privacy checks and entry-resource checks passed. The real iOS
DEBUG build completed successfully with the existing isolated xtool, WITHOUT
`--sign`. SwiftUI compiled and all three images were found byte-for-byte in the
app's resource bundle; the existing Assets.car was also copied unchanged.
Dev plist/URL scheme/entitlement-source checks passed. The binary contains the
DEBUG diagnostic marker and no provisioning profile is embedded. xtool applies
its normal local build entitlements; no Apple-account provisioning or certificate
signing command was executed. CryptoKit/Security runtime tests remain unrun on Linux.

Unsigned artifact: `/home/micha/FamilyCarAgent/xtool/FamilyCarAgent.app`.
Build log: `/home/micha/fca-entry-ui-backups/20261025T144445Z/unsigned-debug-build.log`.
Protected NativeProviders, AuthAPI, AuthCore, Apple diagnostic check, Dev plist,
entitlements, xtool.yml and Assets.car were hash-verified unchanged.

Remaining gates: separately approved certificate signing/install, device rendering
and live provider tests, and confirmation/approval of any Supabase Dev allowlist fix.
The Google explanation remains a hypothesis based on reported settings and upstream
behavior, not a live hosted-service or network-capture verification.

## Next commands (operator only; not executed in this task)

```bash
cd /home/micha/FamilyCarAgent
# Rebuild and certificate-sign using the previously validated isolated tool:
/home/micha/fca-xtool-apple-isolated-20261022/.build/out/Products/Debug-linux-x86_64/xtool dev build --configuration debug --sign
# Only after success, check actual signed app/profile entitlement compatibility:
python3 /home/micha/fca-dev-readiness-20261025/verify-signed.py /home/micha/FamilyCarAgent/xtool/FamilyCarAgent.app
# Only after verification passes, connect/unlock/trust the iPhone and install:
USBMUXD_SOCKET_ADDRESS=127.0.0.1:27015 /usr/bin/ideviceinstaller -i /home/micha/FamilyCarAgent/xtool/FamilyCarAgent.app
```

The signing command performs provisioning and may recreate profiles or synchronize
capabilities. It can require certificate changes if cached material is no longer
valid. Stop on unexpected certificate/capability changes; do not auto-retry.
The fail-closed Apple grouping guard and tool binary are unchanged. Current Apple
account state/certificate validity and USB connectivity were not queried.
The verifier checks structure/identity/expiry, not full cryptographic validity.
ideviceinstaller installs the already-signed app; do not substitute `xtool dev run`.
