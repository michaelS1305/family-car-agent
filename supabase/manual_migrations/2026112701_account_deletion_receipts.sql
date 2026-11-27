-- Apply before enabling DELETION_RECEIPTS_ENABLED on ALL backend workers.
BEGIN;
CREATE TABLE public.account_deletion_receipts (
 operation_id uuid PRIMARY KEY,
 credential_digest bytea NOT NULL CHECK (octet_length(credential_digest)=32),
 job_ref uuid UNIQUE REFERENCES public.account_deletion_jobs(job_ref) ON DELETE RESTRICT,
 state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','completed')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK (isfinite(created_at)),
 completed_at timestamptz,
 expires_at timestamptz,
 CHECK ((state='pending' AND job_ref IS NOT NULL AND completed_at IS NULL AND expires_at IS NULL)
 OR (state='completed' AND job_ref IS NULL AND completed_at IS NOT NULL AND expires_at IS NOT NULL
 AND isfinite(completed_at) AND isfinite(expires_at) AND completed_at>=created_at
 AND expires_at-completed_at=interval '4320 hours'))
);
ALTER TABLE public.account_deletion_receipts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.account_deletion_receipts FROM PUBLIC, anon, authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.account_deletion_receipts TO service_role;
CREATE INDEX account_deletion_receipts_expiry_idx ON public.account_deletion_receipts(expires_at)
 WHERE state='completed';
-- Old workers must fail/retry rather than erase the only pending proof association.
CREATE FUNCTION public.guard_deletion_receipt_finalization() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM public.account_deletion_receipts WHERE job_ref=OLD.job_ref AND state='pending') THEN
  RAISE EXCEPTION 'deletion receipt finalization required';
 END IF;
 RETURN OLD;
END $$;
REVOKE ALL ON FUNCTION public.guard_deletion_receipt_finalization() FROM PUBLIC,anon,authenticated;
CREATE TRIGGER account_deletion_receipt_guard BEFORE DELETE ON public.account_deletion_jobs
 FOR EACH ROW EXECUTE FUNCTION public.guard_deletion_receipt_finalization();
COMMIT;
