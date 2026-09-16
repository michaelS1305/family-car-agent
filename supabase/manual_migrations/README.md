# Manual Supabase migrations

These SQL files are intentionally run by hand in the Supabase SQL Editor. They are
not executed by application startup and must not be run through `init_db()`.

For the family-role rollout, run the files in filename order:

1. `2026090601_family_roles_expand.sql` before deploying the matching application.
2. Deploy and verify the application, then audit all creator relationships.
3. `2026090602_family_creator_contract.sql` only after that audit succeeds.

Both migrations fail on unmet data assumptions instead of inferring or repairing a
family creator. Keep `RUN_DB_INIT=false` in production.

`2026090603_push_subscriptions.sql` is an independent Web Push migration and was
executed successfully in production. After its original execution, all privileges
on `public.push_subscriptions` were manually revoked from `anon` and
`authenticated`; the audited remaining grantees are `postgres` and `service_role`.
The migration file now includes that same `REVOKE` before `COMMIT`, so a fresh
execution creates the intended backend-only access state directly. Do not rerun
the migration in production: the table and audited privilege state already exist.

`2026090602_family_creator_contract.sql` remains pending and unexecuted.

`2026090801_revoke_browser_application_data_access.sql` was manually executed and
verified successfully in production on 2026-09-08. Do not rerun it in production.
It independently revokes table, column, and owned-sequence privileges from `anon`,
`authenticated`, and `PUBLIC` on nine application tables. It locks and checks the
unused Telegram `onboarding_sessions` table before dropping it only if empty;
unexpected dependencies or nonempty contents abort the transaction. No RLS,
Realtime policy/function ACL, or default-privilege changes are included.

Production verification confirmed no effective browser table CRUD, column access,
or owned-sequence access on the nine remaining tables; `onboarding_sessions` is
absent. The `pwa_join_sessions` RLS and Realtime function ACL/security snapshots
were unchanged. Authenticated app load, Chat history/request-response, car status,
Family, Reservations, and History smoke tests passed. Fresh Realtime connections
on two iPhones propagated both connect and disconnect without manual refresh.
No Render deployment was required. These results were reported by the operator.

Keep `2026090801_verify_browser_application_data_access.sql` as the read-only
audit record. For a future execution on another database, save its results and an
ACL/schema backup first, then compare the verification results afterward and
regression-test FastAPI/Auth/private Realtime. This does not require or execute
the pending Family CONTRACT.
An error rolls back all changes; after commit, restoring the legacy table requires
its saved definition, and any privilege restoration must be narrowly reviewed.

Future backend-only public-table migrations must explicitly revoke `anon`,
`authenticated`, and `PUBLIC` table/column and owned-sequence privileges in the
creation transaction. Discover serial/identity ownership through `pg_depend`
(`a`/`i` dependencies); do not assume sequence names. Review function access
separately. Do not rely on default privileges to enforce this boundary.

`2026091402_geocoding_capacity.sql` was executed manually in production on
2026-09-15. It creates backend-only, PostgreSQL-authoritative rolling admission
and active-permit state; it stores no address, coordinates, provider URL, or API
key. Do not run it from application startup.

`2026091501_carplay_transition_rate_limit.sql` is a pending manual migration.
Run it successfully before deploying its matching backend. It adds backend-only,
PostgreSQL-authoritative rolling admission history for CarPlay connect/disconnect
requests; it stores only server-derived user/family references and admission time.

`2026091601_family_code_history.sql` is prepared only, not executed. It creates a
backend-only persistent set of previously assigned codes and backfills all current
family codes. No timestamps or ownership metadata are required for the preference
rule. Released codes remain reusable; `families.family_code` remains authoritative
for current assignments. Codes deleted before this registry existed cannot be
reconstructed by this backfill. Preserve this table in test-data cleanups.

Later cutover: first prepare and validate the matching application implementation,
then pause Create/Join traffic and drain in-flight requests on every old worker.
Run the migration manually as postgres, deploy the history-aware Create/regeneration
allocator to every worker, verify it, then resume Create/Join and enable regeneration.
Do not serve regeneration alongside old Join workers: their transactions do not
participate in the new code-verification/invalidation lock protocol. The migration's
table lock protects its backfill only until COMMIT; it does not stop old workers
from creating unrecorded codes afterward. Do not execute this preparation alone
while old workers continue serving Create traffic. If rollout fails, keep Create
paused; do not resume old writers without a separately reviewed recovery plan.

The migration checks TEXT UNIQUE NOT NULL and canonical ASCII codes before creating
anything, and fails on existing registry objects rather than silently rerunning.
Errors roll back the whole transaction. No existing code or Join session changes.
There are no foreign keys or sequences, so family DELETE/TRUNCATE CASCADE cannot
erase history. Browser/PUBLIC table and column privileges are revoked; postgres
owns the table. No RLS, function ACL or default-privilege changes are made.
It is independent of pending `2026090602_family_creator_contract.sql`.
After commit, dropping the registry would lose persistent usage knowledge; any
rollback must preserve that data and coordinate with the matching application.

The shared allocator samples up to 20 random six-character codes per round. It
chooses the first never-used sample, or the first released sample only if that
round finds no never-used code. Active/current codes are excluded. At most five
rounds/assignment attempts run; only the family-code UNIQUE collision is retried.
Assignment and history insertion share a transaction/savepoint. Creation,
regeneration and Join DB transitions acquire the existing family-creation advisory
lock before row locks; no provider call runs under it. History is never removed.

`2026091602_family_address_confirmations.sql` is prepared only, not executed.
It adds a backend-only, ephemeral pending-confirmation table; no memory backfill
is included. The matching application uses SHA-256 digests (32-byte BYTEA), never raw
tokens, identify confirmations. Create binds auth identity; Update additionally
binds internal user/family. Independent FKs enforce existence, not membership or
creator status: application transactions recheck those relationships.
Successful confirmation must consume the row in the same transaction as the
authorized address mutation; rollback must preserve it. Enforce expiry using
PostgreSQL time after lock waits. Replacement must reset the 15-minute expiry.
The purpose-specific unique indexes preserve one Create per auth user and one
Update per internal user. Expired unused rows need bounded application cleanup;
no scheduler is installed. Deleting a referenced identity/family cascades only
its pending confirmations, without changing existing deletion restrictions.
The postgres-owned table explicitly revokes PUBLIC/anon/authenticated table and
column access; no RLS policies, extensions, default ACLs or existing rows change.
The migration fails on conflicting objects/rerun and rolls back transactionally.
It is independent of Family CONTRACT and family-code history. A later deployment
must apply this migration before starting the matching backend and consistently
use shared storage across workers; old in-memory confirmations
may expire and require address revalidation. Do not assume they are backfilled.
Issuance and consumption acquire the family-creation advisory lock before
confirmation/family row locks. Google runs outside these transactions. Both
Create and Update recheck the inclusive 50-metre location invariant under that
same lock; Update excludes its own family before LIMIT. Successful writes delete
the confirmation atomically. Issuance also deletes at most 100 expired rows.
