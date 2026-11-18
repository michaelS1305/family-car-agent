-- Development only. Review/apply manually with deletion workers stopped.
-- Start only the matching Stage 2 backend after this additive migration.
BEGIN;
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
COMMIT;
