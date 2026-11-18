# Stage 2 — Development account deletion

This extends `account_deletion_jobs`; it does not add a worker. Public phases
remain `draining` / `auth_pending`, with the existing absence-based `completed`
response only after the job is removed. Do not deploy this Development-only
credential configuration to Production.

## Ordering and recovery

1. An existing authenticated confirmation creates the durable deletion fence.
2. The worker commits a random job reference, attempt number and Apple credential
   generation binding before external operations. Existing identity locks exclude
   credential capture commits once deletion starts.
3. Existing application cleanup commits `auth_pending` without changing family,
   vehicle, reservation or reconciliation behavior.
4. Apple revocation runs outside all DB connections/locks. Only HTTP 200 is
   confirmed. An already-invalidated token also returns 200 according to Apple.
5. The result is conditional on job, attempt and credential generation. A lost
   response or failed result commit causes safe repetition, not invented success.
6. Supabase hard deletion runs only after `revoked`, `not_applicable`, or an
   explicit `manual_required` resolution. Actual Auth absence is checked locally.
7. Finalization atomically deletes the encrypted credential, capture attempts and
   deletion job. A failure rolls all three back. The completed log is emitted
   only after commit. No permanent personal deletion receipt is retained.

Claim scheduling remains 60 seconds / 10 jobs per pass, with the existing
five-second loop delay. Each DB transaction has lock/statement timeouts; HTTP has
5-second connect / 10-second read timeouts and no response-body processing.
These requests timeouts are not a hard operating-system deadline on DNS stalls.
An exception is isolated by the existing per-job worker catch. A crash leaves
the scheduled job discoverable. No retry limit converts failure into success.

## Manual resolution and uncertainty

Missing stored credentials are recorded as `manual_required`, never `revoked`.
If capture was pending when deletion fenced it, an unknown token may have been
issued externally. The known stored token is still revoked when available, but
the final resolution remains `manual_required`; `apple_confirmed_at` then refers
only to the bound stored generation. A late Stage 1 finish cannot recreate the
credential, account or authorization after the fence. The pending authorization
code is never replayed. No claim is made that an unknowable external token was
revoked, or that external operations can be rolled back.

Configuration, identity, decryption and provider failures retain credentials and
retry. Operators with existing trusted DB access may explicitly resolve a
prolonged failure, after arranging manual instructions. There is no public
administrative endpoint and no automatic timeout-based fallback.

Public, account-independent help remains available after logout/Auth deletion:
`GET /api/account/deletion/apple-instructions`. It returns only generic guidance
and Apple's support URL, not the outcome of a particular deletion. No JWT,
account identifier, receipt secret or database access is involved. This does not
implement client UI or guarantee that a user has read/completed the instructions.
Preview, confirmation and status responses advertise this existing help endpoint
in a `Link` header (`rel="help"`), without changing their JSON/public phases. The
preview exposes it before confirmation can start Auth deletion. A header does
not prove that an existing client displays it or that a user receives it.
The future deletion UI should make this URL available before signing out. For a
controlled Dev test the operator must supply it to the tester directly.

## Safe read-only diagnostics

Use the existing trusted database connection, not an end-user API:

```sql
SELECT job_ref, phase, apple_state, apple_capture_uncertain,
       apple_confirmed_at, apple_resolution_reason, last_operation, last_attempt_at, attempt_count,
       next_attempt_at, failure_category, operator_attention,
       CASE WHEN apple_state IN ('revoked','not_applicable','manual_required')
            THEN 'auth/finalization_pending' ELSE 'apple_pending' END AS finalization_state
FROM public.account_deletion_jobs
ORDER BY next_attempt_at;
```

All remaining rows are scheduled for retry, including rows flagged for operator
attention. No tokens, ciphertext, subjects or account identifiers are selected.
`failure_category` is the last recorded outcome, not a current authorization
decision. Retries revalidate the actual credential and live Apple identity;
progress-only notes preserve diagnostics/attention until a new result is known.
Structured logs contain only random `job_ref`, operation, internal state and a
fixed normalized category. If the database itself is unavailable, diagnostics
cannot be made durable; the existing worker emits a fixed failure category and
retries. Logging handler failure never changes processing.

The migration defines an owner-only, `SECURITY INVOKER` function
`resolve_apple_deletion_manually(job_ref, expected_category, instructions_arranged)`.
Do not call it as part of testing against real accounts or during deployment.
It compares the observed category and allowed state, requires true confirmation
that instructions were arranged, and records `apple_manual_operator_resolution`.
This is solely an operator assertion: delivery, reading and manual revocation
are not verified. Automatic missing-credential fallback also has no delivery proof.
It does not claim Apple success or delete data itself. Normal worker recovery
performs all finalization checks. Its execute privilege is revoked from PUBLIC,
anon and authenticated. It needs existing trusted database-owner privileges.

## Deployment order (requires separate approval)

1. Review changes and the additive migration; retain all active decryption keys.
2. Stop old deletion workers during the coordinated Dev backend update. Do not
   overlap old workers with Stage 2 jobs: old code can bypass the new final gate.
3. Apply `2026111501_apple_revocation.sql` in Dev only, after the Stage 1 schema.
4. Start the matching backend. Confirm Apple Dev configuration and database
   privileges without printing secrets. No signing/iOS build change is involved.
5. With a disposable Dev Apple account and stored credential, confirm deletion
   using the existing authenticated API; record only the random job reference.
6. Observe prepare -> cleanup -> Apple -> Auth -> finalization. Confirm job and
   credential/attempt removal using trusted queries, and rejection of stale JWTs.
7. Verify generic manual instructions remain accessible without a session.

Provider fault injection, crash and concurrency tests belong in disposable local
PostgreSQL fixtures with mocked Apple/Supabase calls, not live Dev manipulation.
No migration or live request is needed to run those tests.
