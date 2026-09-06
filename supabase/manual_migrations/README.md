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
