# Development and Production PR builds

Local redesign only. No GitHub settings, secrets, workflows or deployments were
changed remotely. Do not enable Production signing until the security setup below
is complete. `FCA_PROD_SIGN_ENABLED` must be a **repository variable** because job
conditions run before environment variables are available.

## Observed review protections (read-only API inspection, 2026-11-25)

- Classic branch-protection endpoints report `Branch not protected` for both
  develop and main. Rulesets must be checked separately; that response alone
  does not establish the absence of protection.
- Active repository ruleset **Protect develop** (27643044) applies to develop:
  deletion and non-fast-forward updates are prohibited. Its required-status-check
  list is empty; there is no pull-request or approval requirement, and no bypass
  actors are listed.
- **Protect main** (27642861) is disabled. The effective branch rules endpoint
  returns no rules for main. Its inactive PR rule would require zero approvals
  and no code-owner review; it does not provide current enforcement.
- Complete main/develop trees contain no CODEOWNERS in .github/, root or docs/.
- Consequently, workflow/classifier changes do **not** currently require protected
  review, and the named CI gates are not enforced as required checks by these
  observed settings. No settings were changed. Signing secret values, environment
  protections and collaborator permissions were not inspected in this review.

The classifier and its tests are executed from the candidate revision. They cannot
independently defend against malicious edits to themselves or their workflows.
Conservative self-change classification catches ordinary mistakes, not an author
who also changes the tests. Branch-name conditions are not a substitute for trust.

Minimal future owner safeguard (not applied): require PRs and trusted code-owner
approval on both develop and main for `.github/**` (including CODEOWNERS itself),
with valid owners, stale-approval dismissal/latest-push approval and restricted
bypasses/direct pushes. Populate required checks with the existing four gate names.
Protect both branches from deletion/force push. A single-owner repository needs
an eligible independent reviewer to make mandatory approval practical; document
that decision rather than claiming self-approval is an independent security control.

Evidence: repository rulesets 27643044/27642861, effective rules/branches/develop
and rules/branches/main, classic protection endpoints and complete Git trees.

## Component-aware validation and release

All four existing workflows report on PRs targeting develop/main and pushes to
both branches. Required check names remain `Android required`, `iOS required`,
`backend`, and `web`. Workflow compatibility does not require renaming checks;
actual enforcement is a separate owner configuration described above.

`.github/component_scope.py` emits independent validation/release decisions.
Checkout fetches full history. PRs compare merge-base(base SHA, head SHA) to head;
pushes compare before/after. Git's NUL-delimited diff includes both rename names,
deletions and every file (no API truncation limit). Missing history, malformed
input, manual dispatch and unknown paths conservatively require all components.
Manual dispatch still respects the existing mobile input/branch/opt-in gates.

| Changes | Validation | New release inputs |
|---|---|---|
| android/** | Android | Android |
| ios/** | iOS | iOS |
| website/** | Web | Web |
| Backend tests/docs only | Backend | Backend (no deploy job) |
| Contact implementation/tests | Backend + Web | Backend |
| device_api.py or take_session_metadata.py | Backend + Android + iOS | Backend |
| Other Backend implementation | Backend + all clients (conservative) | Backend |
| supabase/** | Backend + Android + iOS | Backend/database (no deployment) |
| assets/** | Android + iOS + Web | All asset consumers |
| A component's workflow | That component | That component |
| Android retry helper/tests | Android | None |
| Dedicated manual TestFlight workflow only | Scope/policy/YAML checks | None |
| Unknown/shared scope tooling/incomplete diff | All | All (conservative) |

All scope jobs run classifier and workflow-policy checks, including upload-only
YAML/shell syntax. File rules are deliberately conservative, not an inferred
semantic API compatibility guarantee. Extend exemptions only with reviewed
consumer evidence. Website does not consume vehicle/session database tables.

For a proven unaffected component, the always-running required job reports an
explicit successful no-op and scope reasons. Affected validation must succeed;
unexpected failure, cancellation or skipped validation fails. Production release
requires successful signing; disabled opt-in or an untrusted source cannot count
as successful signing. Validation-only shared Backend/database changes do not
require unchanged mobile binaries to be rebuilt/signed.

Development pushes and PRs use Development validation; main PRs/pushes use
Production validation. Production signing remains limited to trusted internal
**develop -> main** PRs, explicit develop manual inputs, and trusted main pushes.
Android now also validates main pushes and signs there only when Android release
inputs changed, using the same repository restriction as iOS and the existing
`android-production` environment. Fork/feature PRs never gain signing secrets;
if a main PR requires signing and is not trusted, the required gate fails.
iOS Dev signing remains develop-only and only for changed release inputs.

Automatic TestFlight upload retains its existing main-only opt-in, environment,
artifact verification and successful-signing dependencies. Unaffected iOS has no
signed artifact, so it cannot trigger automatic upload. The dedicated manual
upload workflow, pinned artifact and all upload validations remain unchanged.
No artifact is reused across different commits by this change. An affected app
may still be built for both the PR merge candidate and the actual main commit.

PR #91 (head 83d95d3) is the shared database compatibility example: Backend,
Android and iOS validation; iOS signing; no Android signing and no Web work.
Its Android validation failure is not waived. Changes to this policy itself are
unknown/shared tooling and intentionally require all components during rollout.

## Android dependency reliability

Gradle dependency/wrapper caching and bounded Gradle HTTP 429 retries remain
unchanged, including signing-job caching. Only the dedicated integrity-verified Robolectric runtime cache is restored.
Before unit tests, prepare_robolectric_runtime.py downloads the SDK 35/36 jars
pinned in robolectric_runtime.json into a runner-temporary directory. SHA-512
sidecars were read from official Maven Central on 2026-11-25 and independently
checked against complete downloaded jars. These exact official sources are:

- https://repo.maven.apache.org/maven2/org/robolectric/android-all-instrumented/15-robolectric-13954326-i7/android-all-instrumented-15-robolectric-13954326-i7.jar.sha512
- https://repo.maven.apache.org/maven2/org/robolectric/android-all-instrumented/16-robolectric-13921718-i7/android-all-instrumented-16-robolectric-13921718-i7.jar.sha512

Only the official HTTPS endpoint is used; redirects are rejected. Downloads use
unique partial files, fsync, SHA-512 validation and atomic replacement. Existing
jars are rehashed before reuse; mismatches fail closed. The CI-only Gradle init
script rechecks the pinned hashes immediately before each Test task and supplies
robolectric.dependency.dir and robolectric.offline=true to the forked test JVM.
Missing jars fail explicitly. --info records the actual test-worker JVM arguments;
it does not enable credentials or change the application's behavior.

Preparation retries only HTTP 429/502/503/504, at most three attempts with 60/120s
delays. Checksum, TLS, permanent HTTP, partial and unclassified failures do not
retry. Logs contain artifact coordinates, attempt, HTTP status and fixed reason;
no raw exception messages or response bodies. A failed preparation does not start
the suite. Application test failures are never retried by this preparation step.
Gradle dependency resolution retains its separate existing strict 429 retry logic.

All available JUnit XML and HTML test reports are uploaded with always(), seven-day
retention, without continue-on-error on validation. No test filters or version
changes. Runtime and Gradle checks still depend on Maven Central availability;
persistent HTTP failures fail the required check rather than bypass tests.

Runtime versions/hashes must be reviewed together with Robolectric/SDK updates.
The compatibility regression compares the pinned version, test SDK annotations
and targetSdk. A different SDK cannot silently fall back to a network download.

## Security prerequisites — owner configuration, not performed here

An internal-PR condition is **not** a security boundary against someone who can
write a malicious workflow to the repository. GitHub runs the PR's workflow.
The automatic option is appropriate only if **every repository writer is trusted
with signing credentials** and code reaching develop has been reviewed/trusted.

For automatic signing without approving every run:

1. Audit collaborators, teams, bots and write tokens: only trusted writers.
   Protect develop against force push/deletion; restrict direct pushes/bypasses.
   Require reviewed PRs into develop where more than one writer contributes.
   Require trusted review of workflow/signing/build/dependency changes (CODEOWNERS
   and required code-owner review are recommended; configure owners appropriately).
2. Create `android-production` and `ios-production-signing`. Move existing
   Production signing secrets to the corresponding environment, using the same
   names, and remove their repository-scoped copies. Restrict deployment refs to
   `refs/pull/*/merge` plus `develop` for the manual fallback. The PR ref pattern
   alone does not restrict the source branch: the workflow also checks same
   repository, head `develop`, base `main`, non-draft. Only trusted writers can be
   allowed to modify/bypass these checks. No `pull_request_target` or privileged
   `workflow_run` is used. Fork PRs never receive secrets in these workflows.
3. Configure main protection/ruleset: require PR, require current checks
   `Android required`, `iOS required`, `backend`, `web`, require branch up to date,
   block force pushes/deletions and disallow bypass where applicable. GitHub may
   show workflow-qualified names; select the emitted checks from the first run.
   Protect workflow changes as well. Only the owner merges; these workflows do not.
4. After reviewing the above, set repository variable `FCA_PROD_SIGN_ENABLED=true`.
   Until then, Production signing is skipped and the required mobile gates FAIL,
   not silently succeed. Missing credentials cause a failure, not fallback to Dev.

If any writer or same-repository PR code is not trusted, do **not** use reviewer-free
signing. Keep opt-in disabled until environment required reviewers are enabled;
approve only the exact reviewed revision. That alternative starts automatically
but waits for approval before secrets are released. Another safe alternative is
automatic unsigned validation plus manual signing from trusted develop. No YAML
predicate can replace these external trust controls. The observed develop ruleset protects history but does not require these checks
or review; main has no active rules. The owner must configure enforcement before
relying on CI as a merge barrier.

## Existing signing configuration

Android environment `android-production` secrets:

- `FCA_ANDROID_UPLOAD_KEYSTORE_B64` (Base64 keystore)
- `FCA_ANDROID_KEYSTORE_PASSWORD`
- `FCA_ANDROID_KEY_ALIAS` (supports the owner's `fca-upload` alias)
- `FCA_ANDROID_KEY_PASSWORD`
- `FIREBASE_PROD_GOOGLE_SERVICES_JSON_B64` (**raw JSON**, despite its name)

Android repository public variable: `FCA_ANDROID_PROD_SUPABASE_PUBLISHABLE_KEY`.
For a usable Dev APK also set public variable
`FCA_ANDROID_DEV_SUPABASE_PUBLISHABLE_KEY`; without it the APK is explicitly named
`test-only-apk` and uses a fixture, not a working authentication configuration.
Dev Firebase remains `FCA_FIREBASE_DEV_GOOGLE_SERVICES_JSON`.

iOS environment `ios-production-signing` secrets:

- `FCA_IOS_PROD_CERT_P12_BASE64`
- `FCA_IOS_PROD_CERT_P12_PASSWORD`
- `FCA_IOS_PROD_PROFILE_BASE64`
- `FCA_IOS_PROD_GOOGLE_SERVICE_INFO_BASE64`

iOS public variable: `FCA_IOS_PROD_SUPABASE_PUBLISHABLE_KEY`. Existing Dev secrets
are unchanged: `FCA_IOS_DEV_CERT_P12_BASE64`, `FCA_IOS_DEV_CERT_P12_PASSWORD`,
`FCA_DEV_PROFILE_BASE64`, `FCA_IOS_DEV_GOOGLE_SERVICE_INFO_BASE64`.
Dev signing is automatic on develop push when `FCA_DEV_SIGN_ENABLED=true`.

No keys/certificates are regenerated. Signing remains on ephemeral hosted runners;
checkout credentials are not persisted, tokens have contents-read permission,
and temporary signing material uses the existing cleanup. No build is uploaded
to Google Play, published as a release, or deployed to Render/Supabase.
iOS main pushes can upload to TestFlight after the separate owner activation
described in `ios/TESTFLIGHT.md`; PR and Development builds cannot upload.

## Artifacts and local validation

GitHub → Actions → relevant run → **Artifacts**. Download the artifact named
`android-production-aab-<SHA>`, `ios-production-ipa-<SHA>`,
`android-development-…-<SHA>` or `ios-development-ipa-<SHA>`.
Retention is seven days, including metadata reports. The App Store IPA is not an
ad-hoc installation package. Dev IPA device eligibility remains profile-dependent.

Local static checks (Python with PyYAML, Bash; existing local WSL tooling):

```text
python3 .github/test_component_scope.py
python3 .github/check_workflows.py
python3 .github/test_android_gradle_retry.py
python3 ios/Checks/test-production-push.py
```

These validate YAML, event/branch matrices, dependencies, revision binding, shell
and embedded Python syntax, and the iOS signing event fence using synthetic data.
They do not execute GitHub Actions, Xcode, Gradle, signing, or validate live secret
values. The first authorized Actions runs must verify runner/toolchain availability,
real credential/profile compatibility, artifact generation and protection behavior.

References: [GitHub secure use](https://docs.github.com/en/actions/reference/security/secure-use),
[environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments),
[variable availability](https://docs.github.com/en/actions/reference/workflows-and-actions/variables).


### Integrity-verified runtime cache

Android validation invokes `.github/actions/prepare-robolectric` before tests.
The cache key includes OS, architecture, the pinned manifest, preparation script,
offline Gradle init configuration and composite action. No broad restore keys.
Restore is followed unconditionally by SHA-512 verification against the checked-out
manifest, never a checksum supplied by the cache. Valid existing files need no network;
missing files use the same bounded downloader. Corrupt files fail closed, without
replacement, tests or cache saving. Only manifest-listed JAR paths are saved after
BOTH artifacts verify, before tests. No temporary files or checksum sidecars are saved.
The existing Test JVM integrity check remains as defense in depth.
Cache service misses/eviction fall back to verified preparation; cache availability
is an optimization, not a trust boundary. Exact-key caches are immutable: a corrupt
or partial exact entry cannot be overwritten. A partial entry can be completed for
this run; repairing the persistent entry requires separately authorized cache deletion
or a reviewed cache-key generation bump. Never disable verification to repair it.

GitHub cache visibility (default branch confirmed as `main`):
- main runs can restore main caches, not develop or PR merge-ref caches.
- develop runs can restore develop and default-main caches.
- PR runs can restore their merge-ref and allowed base/default-branch caches.
- PR-created caches stay scoped to that PR merge ref; they do not populate main.
Therefore the same key is intentionally branch-independent, but visibility is still
controlled by GitHub. Cross-branch availability cannot be proven by a local mock.
Reference: https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching

After review/merge, a separately authorized maintainer may seed the main cache with:
`gh workflow run robolectric-cache.yml --repo michaelS1305/family-car-agent --ref main`
This manual-only, main-only workflow checks out its exact trusted SHA and runs only
the shared restore/verify/save action. No Gradle, Android SDK, tests, signing, secrets,
release or deployment. It does not replace or satisfy Android required checks.
The workflow must first exist on main. If Maven returns 429, the existing three
attempts remain bounded; warming does not bypass network failure. No workflow was
triggered during local implementation. Once seeded, later compatible develop/PR/main
runs can use that main entry without requesting SDK jars from Maven Central.

Activation verification (not performed locally): warm main, inspect saved cache ref/key,
then inspect cache restoration and `verified_existing` for both SDKs in authorized
main/develop/PR runs. Confirm no `verified_download`/network calls on a warm hit.
Pinned digest checks remain mandatory even for PR-supplied cached content. Repository
review protections, not the classifier itself, protect trusted manifest/script changes.
