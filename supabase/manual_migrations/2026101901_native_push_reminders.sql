-- Manual Dev migration; NOT executed against any cloud database by this change.
-- Preserve vehicle event invariants and all existing table ACL/RLS settings.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='60s';
DO $$ BEGIN
 IF current_user<>'postgres' OR NOT EXISTS
   (SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolbypassrls) THEN
   RAISE EXCEPTION 'Requires verified postgres/BYPASSRLS executor';
 END IF;
END $$;

ALTER TABLE public.vehicle_maintenance ADD COLUMN completed boolean NOT NULL DEFAULT false;
ALTER TABLE public.native_push_events
 ALTER COLUMN source_event_id DROP NOT NULL,
 ADD COLUMN reservation_ref uuid REFERENCES public.reservations(reservation_ref) ON DELETE CASCADE,
 ADD COLUMN maintenance_ref uuid REFERENCES public.vehicle_maintenance(maintenance_ref) ON DELETE CASCADE,
 ADD COLUMN scheduled_for timestamptz,
 DROP CONSTRAINT native_push_events_event_type_check,
 DROP CONSTRAINT native_push_events_ttl_check,
 ADD CONSTRAINT native_push_events_kind_source_check CHECK (
   (event_type IN ('vehicle_taken','vehicle_returned') AND source_event_id IS NOT NULL
    AND reservation_ref IS NULL AND maintenance_ref IS NULL AND scheduled_for IS NULL
    AND expires_at=occurred_at+interval '5 minutes')
   OR
   (event_type IN ('reservation_reminder','maintenance_reminder') AND source_event_id IS NULL
    AND scheduled_for IS NOT NULL AND isfinite(scheduled_for)
    AND expires_at>occurred_at AND expires_at<=occurred_at+interval '5 minutes'
    AND expires_at<=scheduled_for
    AND ((event_type='reservation_reminder' AND reservation_ref IS NOT NULL AND maintenance_ref IS NULL)
      OR (event_type='maintenance_reminder' AND maintenance_ref IS NOT NULL AND reservation_ref IS NULL)))
 ),
 ADD CONSTRAINT native_push_events_reservation_occurrence_key
   UNIQUE(reservation_ref,scheduled_for,actor_user_id,vehicle_id),
 ADD CONSTRAINT native_push_events_maintenance_occurrence_key
   UNIQUE(maintenance_ref,scheduled_for,actor_user_id,vehicle_id);

-- New columns must not acquire any independently granted client privileges.
REVOKE ALL (reservation_ref,maintenance_ref,scheduled_for) ON public.native_push_events
 FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL (completed) ON public.vehicle_maintenance FROM PUBLIC,anon,authenticated;
COMMIT;
