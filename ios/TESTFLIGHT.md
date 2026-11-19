# Automatic Production upload

Local implementation only: no settings changed, signing executed or upload made.
The historical GitHub configuration observations in `.github/CI.md` are not a
current verification of environment settings.

Every push to main runs Production validation, then the existing Production IPA
builder/signer. `iOS required` fails if validation or expected signing is skipped
or fails. Upload depends on all three jobs succeeding. PR and develop behavior is
preserved; they never upload. Main runs are not cancelled by newer pushes.

The upload downloads the signing job's immutable artifact ID from the same run.
It checks the existing signing report's verification flags, IPA SHA-256, embedded
Bundle ID/environment, version and expected build number. It uploads those exact
bytes with Apple's altool, without rebuilding or re-signing. The existing signer
continues to verify signatures, profile and entitlements before creating its report.

## Build numbers and recovery

Marketing version stays 1.0.0. Main builds use GITHUB_RUN_NUMBER mapped to
`1000 + floor(n/10000).floor(n/100)%100.n%100`: run 123 is `1000.1.23`.
This is a monotonic, unique namespace within this workflow and fits Apple's
four/two/two-digit CFBundleVersion limits. Dev, PR and manual candidates retain
their existing default build number. Exhaustion fails rather than wrapping.

Before activation, verify in App Store Connect that this reserved namespace is
unused and higher than existing builds. Do not reset/replace the workflow counter
or let other upload pipelines use this namespace without revisiting allocation.
Concurrent main runs have distinct numbers but can finish out of order; Apple
may reject an older candidate. There is no automatic retry or renumbering.

All rerun attempts are blocked from uploading, even when the first attempt failed
before upload. A new main push produces a new number. For timeout/cancellation or
any uncertain result, inspect App Store Connect before separately authorizing
recovery. Apple also rejects duplicate version/build combinations. This is not a
global duplicate registry for uploads made outside this workflow.

## Owner activation (not performed here)

1. Protect main and trust/review workflow, signing, build and dependency changes.
2. Allow main in `ios-production-signing`, preserving existing approved PR/manual
   refs and protections. Keep repository variable `FCA_PROD_SIGN_ENABLED=true`.
3. Restrict `ios-testflight-upload` to main. Set its existing secret
   `FCA_ASC_API_KEY_BASE64` (Base64 original .p8) and variables `FCA_ASC_KEY_ID`,
   `FCA_ASC_ISSUER_ID`. Use an API key authorized only as needed for app uploads.
   Confirm the app record, agreements and API access are ready.
4. After reviewing this change and the build-number reservation, set repository
   variable `FCA_TESTFLIGHT_UPLOAD_ENABLED=true`. It must be repository-scoped
   because the job condition runs before environment variables are available.
   No per-run review is added; existing environment reviewers still apply.
5. Separately authorize the first real run and verify Apple processing afterward.

Credentials are scoped to the final upload step. The decoded key uses a temporary
0600 file and is removed on normal completion/failure; hosted runners are ephemeral.
The Base64 secret is removed from the child process environment. Raw Apple output
is captured, never printed; failures expose fixed messages and numeric Apple codes
only. No automatic distribution to external testers or App Store submission occurs.
Successful upload means accepted for processing, not completed TestFlight processing.

## Local checks

With Python/PyYAML and Bash:

```
python3 .github/check_workflows.py
python3 ios/Checks/test-production-push.py
python3 ios/Checks/test-testflight-upload.py
```

Tests use synthetic artifacts and mocked Apple commands. Xcode signing, installed
altool compatibility, real credentials, environment protections and Apple processing
cannot be validated by these local tests.
