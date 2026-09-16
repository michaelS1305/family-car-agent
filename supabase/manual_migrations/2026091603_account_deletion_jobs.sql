-- MANUAL ONLY. Prepared, not executed. Coordination schema only; no deletion runtime.
BEGIN;

DO $preflight$
DECLARE
    expected record;
    object_name text;
BEGIN
    IF current_user <> 'postgres' THEN
        RAISE EXCEPTION 'Run this manual migration as postgres';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
       OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        RAISE EXCEPTION 'Expected Supabase browser roles';
    END IF;
    FOR expected IN SELECT * FROM (VALUES
        ('auth.users', 'id', 'uuid', true),
        ('public.users', 'id', 'integer', true),
        ('public.users', 'auth_user_id', 'uuid', false),
        ('public.users', 'family_id', 'integer', false),
        ('public.families', 'id', 'integer', true),
        ('public.families', 'created_by_user_id', 'integer', true)
    ) AS required(table_name, column_name, type_name, require_not_null)
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_class
            WHERE oid = to_regclass(expected.table_name) AND relkind IN ('r', 'p')
        ) OR NOT EXISTS (
            SELECT 1 FROM pg_attribute
            WHERE attrelid = to_regclass(expected.table_name)
              AND attname = expected.column_name AND NOT attisdropped
              AND format_type(atttypid, atttypmod) = expected.type_name
              AND (NOT expected.require_not_null OR attnotnull)
        ) THEN
            RAISE EXCEPTION 'Unexpected required column: %.%',
                expected.table_name, expected.column_name;
        END IF;
    END LOOP;
    FOREACH object_name IN ARRAY ARRAY[
        'account_deletion_jobs', 'account_deletion_jobs_pkey',
        'account_deletion_jobs_next_attempt_idx'
    ] LOOP
        IF to_regclass('public.' || object_name) IS NOT NULL THEN
            RAISE EXCEPTION 'Deletion coordination already applied or conflicting object: %', object_name;
        END IF;
    END LOOP;
END
$preflight$;

-- Auth UUID is the idempotency/retry key, NOT an account profile.
-- Deliberately no FK: the job must survive app-user, family and Auth deletion.
-- No terminal rows: after confirmed Auth absence, delete the job. Runtime must
-- reject absent Auth identities even when no job remains (stale JWT protection).
CREATE TABLE public.account_deletion_jobs (
    auth_user_id uuid PRIMARY KEY,
    phase text NOT NULL DEFAULT 'draining'
        CHECK (phase IN ('draining', 'auth_pending')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        CHECK (isfinite(created_at)),
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp()
        CHECK (isfinite(next_attempt_at)),
    CHECK (next_attempt_at >= created_at)
);

-- Runtime may atomically advance next_attempt_at to claim a bounded retry window.
-- It is scheduling state, NOT authority to skip capacity drain/fencing checks.
-- Phase transition must commit with app cleanup; never hold a transaction over HTTP.
CREATE INDEX account_deletion_jobs_next_attempt_idx
    ON public.account_deletion_jobs (next_attempt_at, auth_user_id);

REVOKE ALL PRIVILEGES ON TABLE public.account_deletion_jobs
FROM PUBLIC, anon, authenticated;
REVOKE ALL PRIVILEGES (auth_user_id, phase, created_at, next_attempt_at)
ON TABLE public.account_deletion_jobs
FROM PUBLIC, anon, authenticated;

COMMIT;
