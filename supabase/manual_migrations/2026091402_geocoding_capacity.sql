-- MANUAL ONLY. Run before deploying the matching backend.
BEGIN;

DO $preflight$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_class
        WHERE oid = to_regclass('auth.users') AND relkind IN ('r', 'p')
    ) THEN
        RAISE EXCEPTION 'Expected auth.users table';
    END IF;
    IF to_regclass('public.geocoding_capacity_policies') IS NOT NULL
       OR to_regclass('public.geocoding_attempts') IS NOT NULL THEN
        RAISE EXCEPTION 'Geocoding capacity migration already applied or conflicting objects';
    END IF;
END
$preflight$;

CREATE TABLE public.geocoding_capacity_policies (
    capacity_pool text PRIMARY KEY
        CHECK (capacity_pool <> '' AND capacity_pool = btrim(capacity_pool)),
    max_concurrency integer NOT NULL CHECK (max_concurrency > 0),
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.geocoding_attempts (
    attempt_id uuid PRIMARY KEY,
    auth_user_id uuid NOT NULL
        REFERENCES auth.users(id) ON DELETE CASCADE,
    capacity_pool text NOT NULL
        REFERENCES public.geocoding_capacity_policies(capacity_pool) ON DELETE RESTRICT,
    admitted_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    permit_expires_at timestamptz,
    CHECK (
        isfinite(admitted_at)
        AND (permit_expires_at IS NULL OR (
            isfinite(permit_expires_at) AND permit_expires_at > admitted_at
        ))
    )
);

CREATE INDEX geocoding_attempts_user_admitted_idx
    ON public.geocoding_attempts (auth_user_id, admitted_at);
CREATE INDEX geocoding_attempts_active_expiry_idx
    ON public.geocoding_attempts (permit_expires_at)
    WHERE permit_expires_at IS NOT NULL;

INSERT INTO public.geocoding_capacity_policies (capacity_pool, max_concurrency)
VALUES ('google-geocoding', 20);

REVOKE ALL PRIVILEGES
ON TABLE public.geocoding_capacity_policies, public.geocoding_attempts
FROM PUBLIC, anon, authenticated;

COMMIT;
