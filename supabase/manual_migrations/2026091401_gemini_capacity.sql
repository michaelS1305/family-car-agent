-- MANUAL ONLY. Deploy the matching backend only after this transaction succeeds.
-- Existing requests have no auditable attempt history: conservatively exhaust
-- their processing allowance. Completed/failed replay and completed-action-only
-- finalization remain available. New requests start at one attempt.
BEGIN;

DO $preflight$
DECLARE
    expected record;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_class WHERE oid = to_regclass('public.chat_requests')
                   AND relkind IN ('r', 'p')) THEN
        RAISE EXCEPTION 'Expected public.chat_requests table';
    END IF;
    FOR expected IN SELECT * FROM (VALUES
        ('id', 'bigint'), ('user_id', 'integer'), ('family_id', 'integer'),
        ('request_id', 'uuid'), ('lease_token', 'uuid'),
        ('lease_expires_at', 'timestamp with time zone'),
        ('created_at', 'timestamp with time zone'), ('status', 'text')
    ) AS required(name, kind)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_attribute
                       WHERE attrelid = 'public.chat_requests'::regclass
                         AND attname = expected.name AND NOT attisdropped AND attnotnull
                         AND format_type(atttypid, atttypmod) = expected.kind) THEN
            RAISE EXCEPTION 'Unexpected chat_requests column: %', expected.name;
        END IF;
    END LOOP;
    IF to_regclass('public.gemini_capacity_policies') IS NOT NULL
       OR to_regclass('public.gemini_call_permits') IS NOT NULL
       OR EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'public.chat_requests'::regclass
                  AND attname = 'processing_attempts' AND NOT attisdropped) THEN
        RAISE EXCEPTION 'Gemini capacity migration already applied or conflicting objects';
    END IF;
END
$preflight$;

ALTER TABLE public.chat_requests
    ADD COLUMN processing_attempts smallint NOT NULL DEFAULT 3
    CONSTRAINT chat_requests_processing_attempts_check CHECK (processing_attempts BETWEEN 1 AND 3);
ALTER TABLE public.chat_requests ALTER COLUMN processing_attempts SET DEFAULT 1;

CREATE TABLE public.gemini_capacity_policies (
    capacity_pool text PRIMARY KEY CHECK (capacity_pool <> '' AND capacity_pool = btrim(capacity_pool)),
    max_concurrency integer NOT NULL CHECK (max_concurrency > 0),
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE public.gemini_call_permits (
    permit_id uuid PRIMARY KEY,
    chat_request_id bigint NOT NULL UNIQUE REFERENCES public.chat_requests(id) ON DELETE RESTRICT,
    attempt_token uuid NOT NULL,
    capacity_pool text NOT NULL REFERENCES public.gemini_capacity_policies(capacity_pool) ON DELETE RESTRICT,
    acquired_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at timestamptz NOT NULL,
    CHECK (isfinite(acquired_at) AND isfinite(expires_at) AND expires_at > acquired_at)
);
CREATE INDEX gemini_call_permits_pool_expiry_idx
    ON public.gemini_call_permits (capacity_pool, expires_at);
INSERT INTO public.gemini_capacity_policies (capacity_pool, max_concurrency)
VALUES ('gemini-default', 50);
REVOKE ALL PRIVILEGES ON TABLE public.gemini_capacity_policies, public.gemini_call_permits
FROM PUBLIC, anon, authenticated;
COMMIT;
