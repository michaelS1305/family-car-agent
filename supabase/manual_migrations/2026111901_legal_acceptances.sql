-- MANUAL ONLY. Apply separately to Development, then Production before Backend rollout.
-- No backfill: only explicit acknowledgments from updated onboarding clients.
BEGIN;

DO $preflight$
BEGIN
    IF current_user <> 'postgres' THEN
        RAISE EXCEPTION 'Run this manual migration as postgres';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_attribute
        WHERE attrelid = to_regclass('auth.users') AND attname = 'id'
          AND NOT attisdropped AND attnotnull
          AND format_type(atttypid, atttypmod) = 'uuid'
    ) THEN
        RAISE EXCEPTION 'Expected auth.users.id uuid NOT NULL';
    END IF;
    IF to_regclass('public.legal_acceptances') IS NOT NULL THEN
        RAISE EXCEPTION 'Legal acceptance migration already applied or conflicting table';
    END IF;
END
$preflight$;

CREATE TABLE public.legal_acceptances (
    auth_user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    terms_version text NOT NULL,
    privacy_version text NOT NULL,
    accepted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (auth_user_id, terms_version, privacy_version)
);

ALTER TABLE public.legal_acceptances ENABLE ROW LEVEL SECURITY;
-- Existing trusted Backend connections use postgres; no client policies/grants.
REVOKE ALL PRIVILEGES ON TABLE public.legal_acceptances FROM PUBLIC, anon, authenticated;
REVOKE ALL PRIVILEGES (auth_user_id, terms_version, privacy_version, accepted_at)
    ON TABLE public.legal_acceptances FROM PUBLIC, anon, authenticated;

COMMIT;
