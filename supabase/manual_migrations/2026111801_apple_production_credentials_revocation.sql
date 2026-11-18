-- MANUAL ONLY: fresh Apple schema on the verified four-column deletion foundation.
-- Stop ALL deletion workers/API writers first; deploy only the matching backend afterwards.
-- Existing Dev Apple tables are intentionally rejected, not recreated or rewritten.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
DO $preflight$
DECLARE actual text[]; item record; definition text;
BEGIN
 IF current_user <> 'postgres' THEN RAISE EXCEPTION 'Run as postgres after worker shutdown'; END IF;
 IF to_regclass('public.account_deletion_jobs') IS NULL THEN
   RAISE EXCEPTION 'Missing account deletion foundation'; END IF;
 LOCK TABLE public.account_deletion_jobs IN ACCESS EXCLUSIVE MODE;
 IF EXISTS (SELECT 1 FROM pg_class WHERE oid='public.account_deletion_jobs'::regclass AND relkind <> 'r') THEN
   RAISE EXCEPTION 'Expected ordinary deletion table'; END IF;
 SELECT array_agg(attname::text || ':' || format_type(atttypid,atttypmod) || ':' || attnotnull::text ORDER BY attname)
 INTO actual FROM pg_attribute WHERE attrelid='public.account_deletion_jobs'::regclass AND attnum>0 AND NOT attisdropped;
 IF actual IS DISTINCT FROM ARRAY['auth_user_id:uuid:true','created_at:timestamp with time zone:true',
      'next_attempt_at:timestamp with time zone:true','phase:text:true'] THEN
   RAISE EXCEPTION 'Unexpected deletion columns; inspect metadata before migration'; END IF;
 SELECT array_agg(conname::text ORDER BY conname) INTO actual FROM pg_constraint
 WHERE conrelid='public.account_deletion_jobs'::regclass;
 IF actual IS DISTINCT FROM ARRAY['account_deletion_jobs_check','account_deletion_jobs_created_at_check',
   'account_deletion_jobs_next_attempt_at_check','account_deletion_jobs_phase_check','account_deletion_jobs_pkey'] THEN
   RAISE EXCEPTION 'Unexpected deletion constraints'; END IF;
 FOR item IN SELECT * FROM (VALUES
   ('account_deletion_jobs_check', 'CHECK (next_attempt_at >= created_at)'),
   ('account_deletion_jobs_created_at_check', 'CHECK (isfinite(created_at))'),
   ('account_deletion_jobs_next_attempt_at_check', 'CHECK (isfinite(next_attempt_at))'),
   ('account_deletion_jobs_phase_check', 'CHECK (phase = ANY (ARRAY[''draining''::text, ''auth_pending''::text]))'),
   ('account_deletion_jobs_pkey', 'PRIMARY KEY (auth_user_id)')
 ) AS expected(name, expression) LOOP
   SELECT pg_get_constraintdef(oid) INTO definition FROM pg_constraint
   WHERE conrelid='public.account_deletion_jobs'::regclass AND conname=item.name AND convalidated;
   IF regexp_replace(definition, '[[:space:]()]', '', 'g') IS DISTINCT FROM
      regexp_replace(item.expression, '[[:space:]()]', '', 'g') THEN
     RAISE EXCEPTION 'Unexpected deletion constraint definition: %', item.name; END IF;
 END LOOP;
 FOR item IN SELECT * FROM (VALUES ('phase', '''draining''::text'),
       ('created_at', 'clock_timestamp()'), ('next_attempt_at', 'clock_timestamp()')) AS expected(name, expression) LOOP
   SELECT pg_get_expr(d.adbin,d.adrelid) INTO definition FROM pg_attrdef d JOIN pg_attribute a
     ON a.attrelid=d.adrelid AND a.attnum=d.adnum
     WHERE d.adrelid='public.account_deletion_jobs'::regclass AND a.attname=item.name;
   IF definition IS DISTINCT FROM item.expression THEN RAISE EXCEPTION 'Unexpected default: %', item.name; END IF;
 END LOOP;
 IF to_regclass('public.apple_credentials') IS NOT NULL OR to_regclass('public.apple_credential_attempts') IS NOT NULL
   OR to_regclass('public.apple_credential_attempts_generation_seq') IS NOT NULL
   OR to_regprocedure('public.resolve_apple_deletion_manually(uuid,text,boolean)') IS NOT NULL THEN
   RAISE EXCEPTION 'Apple schema already exists; this is not a repeatable migration'; END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') OR
    NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN RAISE EXCEPTION 'Expected Supabase roles'; END IF;
 IF to_regclass('auth.users') IS NULL OR to_regclass('auth.identities') IS NULL THEN
   RAISE EXCEPTION 'Missing Supabase Auth schema'; END IF;
END
$preflight$;
CREATE TABLE public.apple_credential_attempts (
    generation bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    auth_user_id uuid NOT NULL,
    code_digest bytea NOT NULL CHECK (octet_length(code_digest)=32),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','stored')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(auth_user_id, code_digest)
);
CREATE INDEX apple_credential_attempts_owner_time ON public.apple_credential_attempts(auth_user_id,created_at);
CREATE TABLE public.apple_credentials (
    auth_user_id uuid PRIMARY KEY,
    environment text NOT NULL,
    client_id text NOT NULL,
    CONSTRAINT apple_credentials_environment_client_check CHECK (
      (environment='dev' AND client_id='com.familycaragent.app.dev') OR
      (environment='prod' AND client_id='com.familycaragent.app')),
    apple_subject text NOT NULL,
    generation bigint NOT NULL REFERENCES public.apple_credential_attempts(generation),
    key_id text NOT NULL,
    refresh_ciphertext bytea NOT NULL CHECK (octet_length(refresh_ciphertext)>28),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
-- Deliberately no cascading auth/users FK: later revocation must survive FCA cleanup.
-- No user-facing read endpoints or RLS policies. Backend DB role only.
ALTER TABLE public.apple_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.apple_credential_attempts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.apple_credentials, public.apple_credential_attempts FROM PUBLIC, anon, authenticated;
REVOKE ALL ON SEQUENCE public.apple_credential_attempts_generation_seq FROM PUBLIC, anon, authenticated;
ALTER TABLE public.account_deletion_jobs
 ADD COLUMN job_ref uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
 ADD COLUMN apple_state text NOT NULL DEFAULT 'unclassified'
   CHECK (apple_state IN ('unclassified','pending','revoked','not_applicable','manual_required')),
 ADD COLUMN apple_generation bigint,
 ADD COLUMN apple_capture_uncertain boolean NOT NULL DEFAULT false,
 ADD COLUMN apple_confirmed_at timestamptz,
 ADD COLUMN apple_resolution_reason text CHECK (apple_resolution_reason IN
   ('apple_credential_missing','apple_capture_unresolved','apple_manual_operator_resolution')),
 ADD COLUMN attempt_count bigint NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
 ADD COLUMN last_operation text NOT NULL DEFAULT 'queued',
 ADD COLUMN last_attempt_at timestamptz,
 ADD COLUMN failure_category text,
 ADD COLUMN operator_attention boolean NOT NULL DEFAULT false,
 ADD CONSTRAINT apple_deletion_manual_reason_check
   CHECK (apple_state <> 'manual_required' OR apple_resolution_reason IS NOT NULL),
 ADD CONSTRAINT apple_deletion_confirmed_check
   CHECK (apple_state <> 'revoked' OR (apple_generation IS NOT NULL AND apple_confirmed_at IS NOT NULL));

-- Explicit, trusted database-only escape hatch. No public/admin HTTP endpoint.
-- An operator must arrange manual instructions, then resolve a specific observed
-- failure. Compare-and-set prevents an old decision from overriding progress.
-- instructions_arranged is an operator assertion, NOT evidence that instructions
-- were delivered/read or that the user revoked Apple access. No such claim is stored.
CREATE FUNCTION public.resolve_apple_deletion_manually(
    target_job uuid, expected_category text, instructions_arranged boolean)
RETURNS boolean LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
DECLARE changed integer;
BEGIN
 IF instructions_arranged IS DISTINCT FROM true THEN RETURN false; END IF;
 -- Takes only the job row lock, never an identity lock afterwards. Workers use
 -- identity -> job order and conditional updates, including after external I/O.
 UPDATE public.account_deletion_jobs SET apple_state='manual_required',
   apple_resolution_reason='apple_manual_operator_resolution',
   failure_category='apple_manual_operator_resolution', operator_attention=false,
   last_operation='manual_resolution', next_attempt_at=GREATEST(created_at,clock_timestamp())
 WHERE job_ref=target_job AND (apple_state IN ('pending','unclassified')
     OR (apple_state IN ('revoked','not_applicable') AND failure_category='apple_credential_mismatch'))
   AND failure_category=expected_category
   AND expected_category IN ('apple_credential_mismatch','apple_decryption_failed',
     'apple_client_configuration_invalid','apple_revocation_timeout',
     'apple_revocation_network_error','apple_revocation_provider_rejected');
 GET DIAGNOSTICS changed = ROW_COUNT;
 RETURN changed=1;
END;
$$;
REVOKE ALL ON FUNCTION public.resolve_apple_deletion_manually(uuid,text,boolean)
 FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.account_deletion_jobs FROM PUBLIC, anon, authenticated;
ALTER TABLE public.account_deletion_jobs ENABLE ROW LEVEL SECURITY;
COMMIT;
