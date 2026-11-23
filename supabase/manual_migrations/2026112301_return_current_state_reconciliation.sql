-- Additive. Apply before compatible Backend; enable endpoint only after old processes drain.
BEGIN;
CREATE TABLE public.return_reconciliation_attempts (
 event_id uuid NOT NULL REFERENCES public.return_recovery_candidates(event_id) ON DELETE CASCADE,
 reconciliation_id uuid NOT NULL,
 payload_fingerprint text NOT NULL CHECK(payload_fingerprint ~ '^[0-9a-f]{64}$'),
 invoked_at timestamptz NOT NULL CHECK(isfinite(invoked_at)),
 location_at timestamptz NOT NULL CHECK(isfinite(location_at)),
 received_at timestamptz NOT NULL CHECK(isfinite(received_at)),
 result jsonb NOT NULL CHECK(jsonb_typeof(result)='object'),
 PRIMARY KEY(event_id,reconciliation_id)
);
CREATE TABLE public.vehicle_return_reconciliations (
 operation_id uuid PRIMARY KEY,
 original_event_id uuid NOT NULL UNIQUE REFERENCES public.return_recovery_candidates(event_id) ON DELETE CASCADE,
 reconciliation_id uuid NOT NULL,
 family_id integer NOT NULL,
 user_id integer NOT NULL,
 device_id integer NOT NULL,
 vehicle_id integer NOT NULL,
 take_event_id uuid NOT NULL,
 anchor uuid NOT NULL,
 session_ref uuid NOT NULL,
 effective_at timestamptz NOT NULL CHECK(isfinite(effective_at)),
 observed_boundary timestamptz CHECK(isfinite(observed_boundary)),
 effective_boundary timestamptz NOT NULL CHECK(isfinite(effective_boundary)),
 checkpoint_generation bigint NOT NULL CHECK(checkpoint_generation>0),
 blocked_by_checkpoint boolean NOT NULL,
 blocked_by_window boolean NOT NULL,
 CHECK(blocked_by_checkpoint OR blocked_by_window),
 CHECK(effective_at>effective_boundary),
 FOREIGN KEY(original_event_id,reconciliation_id) REFERENCES public.return_reconciliation_attempts(event_id,reconciliation_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(vehicle_id,family_id) REFERENCES public.vehicles(id,family_id) ON DELETE CASCADE,
 FOREIGN KEY(user_id,family_id) REFERENCES public.users(id,family_id) ON DELETE CASCADE,
 FOREIGN KEY(device_id,user_id) REFERENCES public.registered_devices(id,user_id) ON DELETE CASCADE,
 FOREIGN KEY(anchor,user_id,vehicle_id,family_id) REFERENCES public.vehicle_events(event_id,user_id,vehicle_id,family_id) ON DELETE CASCADE,
 FOREIGN KEY(take_event_id,user_id,vehicle_id,family_id) REFERENCES public.vehicle_events(event_id,user_id,vehicle_id,family_id) ON DELETE CASCADE
);
CREATE INDEX vehicle_return_reconciliation_suffix ON public.vehicle_return_reconciliations(family_id,effective_at,operation_id);
CREATE INDEX vehicle_return_reconciliation_user ON public.vehicle_return_reconciliations(user_id);
CREATE INDEX vehicle_return_reconciliation_device ON public.vehicle_return_reconciliations(device_id);
CREATE INDEX vehicle_return_reconciliation_vehicle ON public.vehicle_return_reconciliations(vehicle_id);
CREATE INDEX vehicle_return_reconciliation_anchor ON public.vehicle_return_reconciliations(anchor);
CREATE INDEX vehicle_return_reconciliation_take ON public.vehicle_return_reconciliations(take_event_id);
ALTER TABLE public.vehicle_driver_sessions ADD COLUMN end_reconciliation_id uuid REFERENCES public.vehicle_return_reconciliations(operation_id) ON DELETE SET NULL;
ALTER TABLE public.vehicle_driver_sessions DROP CONSTRAINT vehicle_driver_sessions_end_reason_check;
ALTER TABLE public.vehicle_driver_sessions ADD CONSTRAINT vehicle_driver_sessions_end_reason_check CHECK(end_reason IN ('return','handover','vehicle_switch','account_deletion','current_state_reconciliation'));
-- A null reference may survive privacy cleanup, just like end_event_id.
ALTER TABLE public.vehicle_driver_sessions ADD CONSTRAINT vehicle_session_resolution_end CHECK (
 end_reconciliation_id IS NULL OR (end_reason='current_state_reconciliation' AND ended_at IS NOT NULL AND end_event_id IS NULL));
CREATE TRIGGER return_reconciliation_attempt_immutable BEFORE UPDATE ON public.return_reconciliation_attempts FOR EACH ROW EXECUTE FUNCTION public.guard_return_recovery_evidence();
CREATE TRIGGER vehicle_return_reconciliation_immutable BEFORE UPDATE ON public.vehicle_return_reconciliations FOR EACH ROW EXECUTE FUNCTION public.guard_return_recovery_evidence();
ALTER TABLE public.return_reconciliation_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.vehicle_return_reconciliations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.return_reconciliation_attempts,public.vehicle_return_reconciliations FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,DELETE ON public.return_reconciliation_attempts,public.vehicle_return_reconciliations TO service_role;
COMMIT;
