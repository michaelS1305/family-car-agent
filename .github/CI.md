# Development and Production PR builds

Local redesign only. No GitHub settings, secrets, workflows or deployments were
changed remotely. Do not enable Production signing until the security setup below
is complete. `FCA_PROD_SIGN_ENABLED` must be a **repository variable** because job
conditions run before environment variables are available.

## Observed setup (read-only API inspection, 2026-11-19)

- Public repository; neither `main` nor `develop` has branch protection.
- No repository rulesets and no GitHub Environments are configured.
- Signing secrets currently reside at repository scope.
- `FCA_PROD_SIGN_ENABLED` is absent. The old iOS Production job required it to
  equal `true`, a manual event, `develop`, the Production input, and successful
  `ios` validation. Any failed condition skipped signing. The signing script also
  enforced manual/develop independently. This establishes skip conditions, not
  the history of a particular failed attempt.
- Android's Production Supabase publishable key is a **variable**, although the
  previous workflow read it as a secret. The redesigned workflow reads `vars`.

## Events

| Event | Validation/build | Signed artifacts |
|---|---|---|
| Push to develop, matching component paths | Development checks/builds | Android debug APK; iOS Dev IPA when `FCA_DEV_SIGN_ENABLED=true` |
| Non-draft internal develop → main PR opened/updated | All four workflows; Production mobile configuration | AAB + IPA after validation, only when Production opt-in is enabled |
| Fork or other source branch → main | Automatic secret-free Production validation | No Production signing; required mobile gates fail explicitly |
| Draft PR | Expensive validation/signing skipped | None; ready-for-review event starts validation |
| Merge/push to main | No workflow push trigger | No duplicate build |
| Manual dispatch | Explicit retry/diagnostic escape hatch | Mobile dispatch requires develop; Production requires the corresponding input and opt-in; iOS Dev uses its existing input |

PR validation uses synthetic public Firebase/Supabase configuration; no signing
secrets are supplied to validation. Signed builds use their real environment's
configuration. Production iOS compiles Release with `FCA_PRODUCTION`; Android
runs Prod unit tests/lint/debug compilation, then builds the signed Release AAB.
The existing iOS test suites are shared and include Production environment checks.
They do not establish physical-device E2E delivery or signing validity on Apple.

Each signing job depends on validation and does not rerun its tests. Website
`pnpm test` already runs TypeScript and a Production build, so separate duplicate
typecheck/build steps were removed. Dev and Prod
are intentionally different validations: a develop push and its main PR can both
run, but do not build the same configuration twice. Simulator validation and
device IPA compilation serve different targets. Superseded runs are canceled by
PR number/branch concurrency. Reopening, updating the base/branch, manual retries
or reruns may repeat work; this is not a global exactly-once scheduler.

All PRs run all four workflows without path filters, so required checks cannot
remain pending on documentation-only or cross-component PRs. Pushes retain their
component filters. This deliberately favors reliable merge protection over adding
a change-detection subsystem. All jobs check out `github.sha`: the PR **merge
candidate**, not just the head. Artifacts include that SHA; summaries record merge,
head and base SHAs. Require an up-to-date main base before merging.

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
predicate can replace these external trust controls. Repository settings cannot
currently enforce merge blocking because protection is absent; the owner must
configure it before relying on these checks.

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
to Google Play/TestFlight, published as a release, or deployed to Render/Supabase.

## Artifacts and local validation

GitHub → Actions → relevant run → **Artifacts**. Download the artifact named
`android-production-aab-<SHA>`, `ios-production-ipa-<SHA>`,
`android-development-…-<SHA>` or `ios-development-ipa-<SHA>`.
Retention is seven days, including metadata reports. The App Store IPA is not an
ad-hoc installation package. Dev IPA device eligibility remains profile-dependent.

Local static checks (Python with PyYAML, Bash; existing local WSL tooling):

```text
python3 .github/check_workflows.py
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
