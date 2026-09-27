-- PREPARED ONLY. Stop old/new CarPlay writers before applying; see README.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
DO $preflight$
BEGIN
    IF current_user <> 'postgres'
       OR to_regclass('public.carplay_vehicle_bindings') IS NOT NULL
       OR to_regclass('public.vehicle_events') IS NULL
       OR to_regclass('public.vehicle_driver_sessions') IS NULL
       OR to_regprocedure('public.broadcast_car_status_changed()') IS NULL THEN
        RAISE EXCEPTION 'Unexpected role, missing foundation, or conflicting binding table';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_trigger WHERE tgrelid='public.car_events'::regclass
                   AND tgname='car_events_broadcast_car_status' AND NOT tgisinternal
                   AND tgfoid='public.broadcast_car_status_changed()'::regprocedure) THEN
        RAISE EXCEPTION 'Expected legacy broadcast trigger missing';
    END IF;
END
$preflight$;

-- Temporary detector routing, not authentication or globally single-car users.
CREATE TABLE public.carplay_vehicle_bindings (
    user_id integer PRIMARY KEY,
    family_id integer NOT NULL,
    vehicle_id integer NOT NULL,
    CONSTRAINT carplay_binding_user_family_fk FOREIGN KEY (user_id,family_id)
        REFERENCES public.users(id,family_id) ON DELETE CASCADE,
    CONSTRAINT carplay_binding_vehicle_family_fk FOREIGN KEY (vehicle_id,family_id)
        REFERENCES public.vehicles(id,family_id) ON DELETE CASCADE
);
CREATE INDEX carplay_bindings_vehicle_idx ON public.carplay_vehicle_bindings(vehicle_id,family_id);
ALTER TABLE public.carplay_vehicle_bindings ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.carplay_vehicle_bindings FROM PUBLIC, anon, authenticated;
-- Bound active History/status lookup independently of accumulated ended history.
CREATE INDEX vehicle_sessions_family_active_idx ON public.vehicle_driver_sessions(family_id,started_at,id)
    WHERE ended_at IS NULL;

-- The existing function publishes an empty invalidation payload. Receive-topic
-- authorization and function privileges are unchanged. No legacy dual emission.
DROP TRIGGER car_events_broadcast_car_status ON public.car_events;
CREATE TRIGGER vehicle_events_broadcast_car_status
AFTER INSERT ON public.vehicle_events
FOR EACH ROW WHEN (NEW.admission_outcome = 'accepted')
EXECUTE FUNCTION public.broadcast_car_status_changed();

-- Account cleanup removes sessions before deleting the user. Invalidate only
-- surviving families, without inventing a physical RETURN or a legacy event.
CREATE FUNCTION public.broadcast_vehicle_member_deleted()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path TO '' AS $function$
BEGIN
    IF OLD.family_id IS NOT NULL AND EXISTS (
        SELECT FROM public.families WHERE id=OLD.family_id
    ) THEN
        PERFORM realtime.send('{}'::jsonb, 'car_status_changed',
            'family:' || OLD.family_id::text || ':car-status', true);
    END IF;
    RETURN OLD;
END;
$function$;
REVOKE ALL ON FUNCTION public.broadcast_vehicle_member_deleted() FROM PUBLIC, anon, authenticated;
CREATE TRIGGER users_broadcast_vehicle_member_deleted AFTER DELETE ON public.users
FOR EACH ROW EXECUTE FUNCTION public.broadcast_vehicle_member_deleted();
COMMIT;
