# Stage 1 — native Apple credential capture (Development only)

This is **not account deletion or token revocation**. Existing native Supabase login
is unchanged. After its session is stored, iOS submits the short-lived authorization
code and original nonce once, with that session's pinned bearer token, in memory.
The task does not block onboarding. Logout cancels it; a late response never changes
session state. Cancellation cannot retract a request already received by the server.

## Contract and trust

`POST /api/account/apple-credential`, authenticated via the existing live Supabase
identity dependency (works before FCA family onboarding). Strict JSON: `code`,
`nonce`; no owner, email, Apple user identifier, or client identifier accepted.
Replies: `200 {"status":"stored"}`, `503 {"status":"unavailable"}`, sanitized
`422 {"status":"invalid_request"}`, or existing authentication errors.

The backend reads `auth.identities` for the verified JWT subject; exactly one Apple
identity must have matching nonempty `provider_id` and `identity_data.sub`. Additional
non-Apple providers do not change that check. No match means no exchange.
Apple's returned ID token must have valid RS256 signature, issuer, exact native
audience, subject, expiration, issued-at and SHA256(original nonce). Our native flow
always supplies a nonce: omission in Apple's exchange response fails capture closed.
This behavior must be verified with a real native Development login before rollout.
Apple JWKS is fetched only from the fixed official endpoint with caching/throttling.
No request body, provider response, exception, credential, or account identity is logged.

## Persistence and failure behavior

Apply `supabase/manual_migrations/2026111401_apple_credentials.sql` manually in
**Supabase Development only**, after review. It is not executed at startup.
Prerequisites: existing `auth.users`, `auth.identities`, account deletion jobs and
backend DB role able to read Auth identity data and access the two new tables.
Verify that role and RLS privileges locally/operationally; do not grant browser roles.
Migration is transactional and intentionally fails if tables already exist.
No live database has been inspected or modified by this implementation.

Two server-only tables:

- `apple_credential_attempts`: owner, one-way code digest, sequence generation,
  pending/stored state and timestamp. No raw code/nonce/ID token.
- `apple_credentials`: one current encrypted refresh token per owner, Apple subject,
  client/environment, generation, encryption key ID and timestamps.

Exclusive existing deletion identity lock serializes attempt allocation and final
commit. Each transaction rechecks live identity/deletion status. HTTP runs outside
transactions. The final transaction rechecks linked subject and newest generation,
and atomically stores ciphertext plus attempt success. Superseded responses cannot
overwrite newer credentials. Five new attempts per owner per rolling hour; duplicates
do not consume quota. Never retry the same code, even after a crash or timeout.

`pending` means **exchange outcome unknown or failed**, not a job to retry. A crash
after Apple consumes a code but before DB commit cannot recover that token. The last
committed credential is retained. A fresh Apple login may capture a new credential.
On a DB commit acknowledgment loss, resubmitting the same code reads the committed
attempt state; it does not repeat Apple's request. A successful replacement stores
the new token only; no token is revoked in Stage 1.

There is deliberately no cascading Auth/user FK: future revocation needs credentials
after FCA cleanup. **The existing deletion worker does not yet revoke or purge these
tables.** Retention/purge, manual Apple fallback and deletion integration remain Stage
2 work. Do not present Stage 1 as a complete deletion solution or enable Production.
Attempt rows are rate-bounded but have no scheduled pruning in this stage; retention
must be settled together with the deletion integration (do not prune replay guards
independently). Rolling back capture must retain keys and encrypted records.

## Render Development environment variables (owner configures manually)

| Name | Required format |
|---|---|
| `APPLE_CREDENTIAL_ENVIRONMENT` | Literal `dev` |
| `APPLE_NATIVE_CLIENT_ID` | Literal `com.familycaragent.app.dev` |
| `APPLE_TEAM_ID` | Apple Team ID, 10 uppercase letters/digits |
| `APPLE_KEY_ID` | Sign in with Apple key ID, 10 uppercase letters/digits |
| `APPLE_PRIVATE_KEY_BASE64` | Standard Base64 of the complete `.p8` PEM bytes, including PEM newlines; P-256 EC private key |
| `APPLE_CREDENTIAL_KEYS_JSON` | JSON object mapping key IDs to standard Base64 of independent random 32-byte AES keys; 1–4 entries |
| `APPLE_CREDENTIAL_ACTIVE_KEY_ID` | Key ID present in that JSON; 1–32 letters/digits/underscore/hyphen |

Existing `SUPABASE_URL` must equal the repository's Development project URL. No
Production fallback. Missing/malformed config disables capture only, not login.
Set these in the **Render Development Backend service Environment**, not the mobile
app, GitHub signing secrets, or Supabase client config. No Windows file path is used.
Encode PEM bytes before pasting: do not paste literal `\\n` escapes or raw PEM in the
Base64 variable. Do not put key material in shell arguments, logs or repository files.
Use newly generated Apple credential AES keys, never Native Push keys. Configuration
rejects equality with configured Native Push encryption/fingerprint keys.

Rotation: retain old entries for reads; add a new independent key under a new ID,
then change the active ID. Existing ciphertext retains its key ID. Removing an old
key before its records are handled makes them unreadable; no mass re-encryption or
rotation automation is included. AES-GCM associated data binds format version,
environment, authenticated owner, client ID, Apple subject and generation.
Apple ES256 client secrets are generated per exchange with a five-minute lifetime.

## Controlled integration checklist — requires separate operator authorization

1. Review source/tests and migration. Verify backend DB role can access the required
   Auth identity columns and new server-only tables. Do not display identity values.
2. Apply the single migration to Dev, then set the variables above in Render Dev.
3. Deploy reviewed Backend and build the reviewed native Dev app through existing
   Xcode/GitHub flow. No entitlement or manual iOS configuration change is needed.
4. Perform a fresh native Apple login on the iPhone (session restoration does not
   recapture). Verify login/onboarding works and an attempt becomes `stored` using
   safe counts, e.g. `SELECT status,count(*) FROM apple_credential_attempts GROUP BY status;`.
   Do not select ciphertext, tokens, subjects or private material for diagnostics.
5. Verify disabled/unavailable capture does not break login. Test logout/account
   switching while a synthetic delayed capture runs, then ordinary Google login.
6. Confirm a real Apple exchange including nonce and DB persistence before calling
   capture operational. Mock success is not Apple integration success.

Local focused commands (no external services):
`PYTHONPATH=backend python -m unittest backend.tests.test_apple_credentials backend.tests.test_apple_credentials_api backend.tests.test_account_deletion_api`
and `bash ios/Checks/run-auth-checks.sh` using the existing local Swift toolchain.
SQL tests use mocked transactions; migration execution, PostgreSQL permissions and
real concurrent database behavior still require an isolated integration environment.
