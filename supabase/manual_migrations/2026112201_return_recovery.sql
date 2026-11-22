-- Phase 1 only. Apply separately, BEFORE deploying the recording API.
-- NOT executed by application startup. Existing vehicle evidence is untouched.
BEGIN;

CREATE TABLE public.return_recovery_candidates (
    event_id uuid PRIMARY KEY,
    family_id integer NOT NULL,
    user_id integer NOT NULL,
    device_id integer NOT NULL,
    vehicle_id integer NOT NULL,
    device_sequence bigint NOT NULL CHECK (device_sequence > 0),
    take_event_id uuid NOT NULL CHECK (take_event_id <> event_id),
    occurred_at timestamptz NOT NULL CHECK (isfinite(occurred_at)),
    rejection_code text NOT NULL CHECK (rejection_code IN ('RETURN_HOME_UNAVAILABLE','RETURN_OUTSIDE_HOME')),
    payload_fingerprint text NOT NULL CHECK (payload_fingerprint ~ '^[0-9a-f]{64}$'),
    original_evidence jsonb NOT NULL CHECK (jsonb_typeof(original_evidence) = 'object'),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK (isfinite(recorded_at)),
    UNIQUE (device_id, device_sequence),
    FOREIGN KEY (vehicle_id, family_id) REFERENCES public.vehicles(id, family_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id, family_id) REFERENCES public.users(id, family_id) ON DELETE CASCADE,
    FOREIGN KEY (device_id, user_id) REFERENCES public.registered_devices(id, user_id) ON DELETE CASCADE,
    FOREIGN KEY (take_event_id, user_id, vehicle_id, family_id)
        REFERENCES public.vehicle_events(event_id, user_id, vehicle_id, family_id) ON DELETE CASCADE
);
CREATE INDEX return_recovery_candidates_owner_idx ON public.return_recovery_candidates(user_id, family_id);
CREATE INDEX return_recovery_candidates_family_idx ON public.return_recovery_candidates(family_id);
CREATE INDEX return_recovery_candidates_vehicle_idx ON public.return_recovery_candidates(vehicle_id, family_id);
CREATE INDEX return_recovery_candidates_take_idx ON public.return_recovery_candidates(take_event_id);

CREATE TABLE public.return_recovery_attempts (
    event_id uuid NOT NULL REFERENCES public.return_recovery_candidates(event_id) ON DELETE CASCADE,
    recovery_id uuid NOT NULL,
    payload_fingerprint text NOT NULL CHECK (payload_fingerprint ~ '^[0-9a-f]{64}$'),
    invoked_at timestamptz NOT NULL CHECK (isfinite(invoked_at)),
    location_at timestamptz NOT NULL CHECK (isfinite(location_at)),
    received_at timestamptz NOT NULL CHECK (isfinite(received_at)),
    -- Deliberately no verification latitude/longitude. Store result + fingerprint.
    result jsonb NOT NULL CHECK (jsonb_typeof(result) = 'object'),
    PRIMARY KEY (event_id, recovery_id)
);

-- Immutable even for retries. Deletion cascades remain available for account
-- cleanup, including _checkpoint_vehicle_identity's existing TAKE deletion.
CREATE FUNCTION public.guard_return_recovery_evidence() RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    RAISE EXCEPTION 'Return recovery evidence is immutable';
END;
$$;
CREATE TRIGGER return_recovery_candidate_immutable BEFORE UPDATE ON public.return_recovery_candidates
    FOR EACH ROW EXECUTE FUNCTION public.guard_return_recovery_evidence();
CREATE TRIGGER return_recovery_attempt_immutable BEFORE UPDATE ON public.return_recovery_attempts
    FOR EACH ROW EXECUTE FUNCTION public.guard_return_recovery_evidence();

-- Same backend-only ACL model as vehicle identity; also deny browser RLS access.
ALTER TABLE public.return_recovery_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.return_recovery_attempts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.return_recovery_candidates, public.return_recovery_attempts FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, DELETE ON public.return_recovery_candidates, public.return_recovery_attempts TO service_role;
REVOKE ALL ON FUNCTION public.guard_return_recovery_evidence() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.guard_return_recovery_evidence() TO service_role;

-- Retain idempotency evidence for the same lifetime as its causal vehicle event.
-- No age-based deletion: expiry prevents NEW recovery, not retrieval of a commit.
-- Existing account/family/vehicle/TAKE cleanup cascades to both tables.
COMMIT;
