-- PREPARED / UNEXECUTED. Review and apply manually on Dev only.
-- No existing installation, event, challenge or delivery rows are rewritten.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
DO $preflight$
BEGIN
    IF current_user <> 'postgres' OR NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolbypassrls
    ) THEN RAISE EXCEPTION 'Expected reviewed postgres/BYPASSRLS executor'; END IF;
    IF to_regclass('public.native_push_installations') IS NULL THEN
        RAISE EXCEPTION 'Native Push foundation is required';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_publication WHERE puballtables)
       OR EXISTS (SELECT 1 FROM pg_publication_namespace WHERE pnnspid='public'::regnamespace) THEN
        RAISE EXCEPTION 'Automatic publication would expose cancellation hashes';
    END IF;
END
$preflight$;
CREATE TABLE public.native_push_ios_revocations (
    installation_ref uuid PRIMARY KEY,
    user_id integer NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    provider_project text NOT NULL CHECK (btrim(provider_project)<>''),
    secret_hash bytea NOT NULL CHECK (octet_length(secret_hash)=32),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    revoked_at timestamptz CHECK (isfinite(revoked_at))
);
CREATE INDEX native_push_ios_revocations_owner_idx ON public.native_push_ios_revocations(user_id);
ALTER TABLE public.native_push_ios_revocations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.native_push_ios_revocations FROM PUBLIC, anon, authenticated, service_role;
-- Same postgres/BYPASSRLS Backend execution assumption as the foundation migration.
-- Deliberately no FK to installations: a durable cancellation may precede begin.
COMMIT;
