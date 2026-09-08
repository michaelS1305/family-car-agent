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
