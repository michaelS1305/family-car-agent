# iOS Production runtime and Apple readiness

Local preparation only. No live configuration, signing, migration, deletion, revocation or deployment was performed.

## Runtime and Release

`SessionComposition` is used by `VehicleSessionRuntime`: trusted compilation selection,
Bundle ID and `FCAEnvironment` must agree before constructing the vault/API/session.
Production is `FCA_PRODUCTION`, `com.familycaragent.app`, `production`; there is no Dev fallback.
Vehicle take/return App Intents and setup UI are available in Release. Diagnostic connection
and offline probe intents remain DEBUG-only. Production metadata verification requires both
product actions and rejects diagnostic actions. Synthetic metadata checks are not evidence
of an actual signed Xcode build; run the existing production wrapper verification on macOS.

## Backend configuration (API and deletion worker must agree)

| Variable | Production requirement |
| --- | --- |
| APPLE_CREDENTIAL_ENVIRONMENT | `prod` |
| APPLE_NATIVE_CLIENT_ID | `com.familycaragent.app` |
| APPLE_TEAM_ID | `GT43M39TLK` |
| APPLE_KEY_ID | Owner-verified 10-character Apple Sign in with Apple key ID |
| APPLE_PRIVATE_KEY_BASE64 | Base64 of the matching P-256 PEM private key, secret only |
| APPLE_CREDENTIAL_ACTIVE_KEY_ID | Existing identifier in the configured keyring |
| APPLE_CREDENTIAL_KEYS_JSON | JSON mapping 1–4 key identifiers to distinct base64 32-byte keys |
| SUPABASE_URL | `https://xrgijytfigcuxmdktvmd.supabase.co` |
| SUPABASE_SERVICE_ROLE_KEY | Matching Production secret for existing Auth deletion |
| DATABASE_URL | Matching Production database, existing backend connection convention |

No Key ID or private key availability has been verified by this task. No secrets were generated.
Keep keys stable and backed up securely. Apple keys must differ from all four original and
iOS Production Native Push encryption/fingerprint keys. Separate deployments must use their
own Apple keyrings; code cannot prove cross-server secret uniqueness. Existing Dev ciphertext
format/AAD and key identifiers are unchanged. Do not remove keys while records still use them.

Apple Developer: owner must verify Sign in with Apple capability for the exact native App ID,
Team and provisioning entitlement, and a matching authorized signing key. Supabase Production
Auth must enable Apple with the native client ID as an accepted audience, matching provider
credentials and existing identity matching. Native authentication must not substitute an
unrelated web Services ID. Existing Supabase JWT verification requires ES256; confirm project
signing configuration separately. Google authentication/callback configuration is unchanged.
Canonical website/legal availability and privacy declarations still require release verification.

## Migration and exact preconditions

Use `supabase/manual_migrations/2026111801_apple_production_credentials_revocation.sql`
only after separate approval. It is transactional and deliberately not repeatable. It expects
the four-column deletion foundation, all NOT NULL, with exactly the five named constraints
and definitions from `2026091603_account_deletion_jobs.sql`, phase default `draining`,
timestamp defaults `clock_timestamp()`. Owner confirmed names/types/phases, but live default,
nullability and full expression metadata still need confirmation. Any mismatch aborts.
It requires postgres execution, Supabase anon/authenticated roles, auth.users/auth.identities,
and absent Apple tables, identity sequence and manual-resolution function. Existing Dev Apple
schemas are intentionally rejected; do not apply this fresh-schema migration to Development.
The new identity constraint accepts only the exact Dev/client and Prod/client pairs.

The broader existing deletion dependencies (application tables, Auth identity columns, backend
DB role privileges) must already match the deployed deletion implementation; this migration
does not install or certify them. Do not use the old Dev migrations blindly in Production.
Use the adjacent `_verify.sql` file for read-only metadata, RLS, ACL and state verification.
No verification query prints credential ciphertext, tokens, owner identity or personal data.

Deployment order, after approval:
1. Back up schema/data and preserve encryption keys; inspect live prerequisite metadata.
2. Stop ALL old deletion workers, including embedded API workers and automatic restarts;
   stop deletion/credential writers. A rolling mixed-version deployment is unsafe.
3. Apply the single additive transaction, run verification, confirm pre-existing jobs survive.
4. Configure matching secrets on API/worker, deploy matching backend while workers remain stopped.
5. Validate configuration/schema, then start only updated API/workers; monitor safe categories.
6. Separately build/sign iOS Release and verify real device Apple capture, logout/relogin,
   Push, Shortcuts and explicit test-account deletion/revocation end to end with approval.

Rollback: transaction failures roll back atomically. After commit, do not drop new columns/tables,
erase credentials or restart old workers: that can skip revocation and lose durable state.
Stop processing and use a reviewed forward fix, or an approved backup recovery plan coordinated
with irreversible external Auth/Apple operations. There is no automatic down migration.

## Deletion semantics and limits

Existing preview/confirmation, ownership, generations, fencing, retries and non-Apple behavior
remain. Revocation and resumed finalization now require server-pinned Supabase/client/environment
identity. No credential is silently selected from another environment.

Authorization-code capture is still best effort. A missing credential cannot guarantee Apple
revocation; existing manual-required handling remains. Application data cleanup precedes Apple
revocation, and the existing manual-required terminal path can permit Auth deletion. A completed
account-deletion status is not proof that Apple revocation succeeded. Manual resolution requires
the existing explicit administrative procedure and arranged user instructions; no automatic
manual approval or new recovery guarantee was introduced.

## Local validation

`backend/tests/run_apple_offline.py` blocks provider/database I/O. DB workflow tests are skipped
without a disposable database; their presence is not a claim that concurrency tests ran.
`backend/tests/check_apple_production_migration.py` uses an already present postgres:17 image,
network disabled, no ports, synthetic data and a disposable tmpfs; tests exact SQL, preservation,
identity constraints, RLS/ACL and rollback on schema drift, then removes its own container.
`ios/Checks/run-native-push-checks.sh` compiles Dev/Prod composition checks on Linux Swift and
tests wrapper metadata rules. macOS signing/real generated metadata and physical iPhone E2E
remain outstanding. Native Push architecture and Android source are unchanged by this task.

Validation in this local run: Apple/deletion 167 discovered, 69 passed, 98 database-dependent
skipped; Native Push 146 discovered, 66 passed, 80 database-dependent skipped. iOS Python
checks: 9 + 4 + 5 passed; Swift lifecycle/registration and both environment/composition checks
passed. Production Swift parsing, Python syntax, exact migration/verification SQL and
`git diff --check` passed. The signing-preflight negative fixture prints an unavailable-macOS/
OpenSSL failure as expected; it is not a completed signing operation.

## Files changed by this task (excluding pre-existing local changes)

- `Sources/FamilyCarAgent/Auth/SessionComposition.swift` (new)
- `Sources/FamilyCarAgent/OfflineEvents/VehicleSessionRuntime.swift`
- `Sources/FamilyCarAgent/OfflineEvents/VehicleAppIntents.swift`
- `Sources/FamilyCarAgent/Vehicles/VehicleConnectionSetupView.swift`
- `Checks/SessionCompositionChecks.swift` (new), `Checks/run-native-push-checks.sh`
- `Checks/app-intents-poc.py`, `Checks/test-production-push.py`
- `backend/apple_credentials_security.py`, `backend/apple_revocation.py`
- `backend/tests/test_apple_credentials.py`, `backend/tests/test_apple_revocation.py`
- `backend/tests/test_apple_production.py`, `backend/tests/run_apple_offline.py` (new)
- `backend/tests/check_apple_production_migration.py` (new)
- Both `supabase/manual_migrations/2026111801_apple_production_credentials_revocation*.sql` files (new)
- This runbook (new).

iOS paths above are relative to `ios/`; backend and migration paths are relative to repository root.
