-- Apply before enabling the metadata reader. Existing writers advance revisions via triggers.
BEGIN;
ALTER TABLE public.families ADD COLUMN projection_revision bigint NOT NULL DEFAULT 0 CHECK(projection_revision>=0);
CREATE FUNCTION public.bump_vehicle_projection_revision() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE family integer;
BEGIN
 IF TG_OP='DELETE' THEN family=OLD.family_id; ELSE family=NEW.family_id; END IF;
 UPDATE public.families SET projection_revision=projection_revision+1 WHERE id=family;
 IF TG_OP='UPDATE' AND OLD.family_id IS DISTINCT FROM NEW.family_id THEN
  UPDATE public.families SET projection_revision=projection_revision+1 WHERE id=OLD.family_id;
 END IF;
 RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION public.bump_vehicle_projection_revision() FROM PUBLIC;
CREATE TRIGGER session_projection_revision AFTER INSERT OR UPDATE OR DELETE ON public.vehicle_driver_sessions
 FOR EACH ROW EXECUTE FUNCTION public.bump_vehicle_projection_revision();
CREATE TRIGGER event_projection_revision AFTER INSERT OR UPDATE OR DELETE ON public.vehicle_events
 FOR EACH ROW EXECUTE FUNCTION public.bump_vehicle_projection_revision();
CREATE TRIGGER resolution_projection_revision AFTER INSERT OR DELETE ON public.vehicle_return_reconciliations
 FOR EACH ROW EXECUTE FUNCTION public.bump_vehicle_projection_revision();
CREATE FUNCTION public.bump_checkpoint_projection_revision() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 NEW.projection_revision=OLD.projection_revision+1;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.bump_checkpoint_projection_revision() FROM PUBLIC;
CREATE TRIGGER checkpoint_projection_revision BEFORE UPDATE OF vehicle_finalized_through,vehicle_reconciliation_generation ON public.families
 FOR EACH ROW WHEN (OLD.vehicle_finalized_through IS DISTINCT FROM NEW.vehicle_finalized_through OR OLD.vehicle_reconciliation_generation IS DISTINCT FROM NEW.vehicle_reconciliation_generation)
 EXECUTE FUNCTION public.bump_checkpoint_projection_revision();
-- Availability changes alter metadata responses even without a session mutation.
CREATE TRIGGER vehicle_metadata_revision AFTER UPDATE OF retired_at ON public.vehicles
 FOR EACH ROW WHEN (OLD.retired_at IS DISTINCT FROM NEW.retired_at)
 EXECUTE FUNCTION public.bump_vehicle_projection_revision();
CREATE FUNCTION public.bump_binding_metadata_revision() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE device bigint;
BEGIN
 IF TG_OP='DELETE' THEN device=OLD.device_id; ELSE device=NEW.device_id; END IF;
 UPDATE public.families SET projection_revision=projection_revision+1
 WHERE id IN (SELECT u.family_id FROM public.users u JOIN public.registered_devices d ON d.user_id=u.id WHERE d.id=device);
 RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION public.bump_binding_metadata_revision() FROM PUBLIC;
CREATE TRIGGER binding_metadata_revision AFTER INSERT OR DELETE ON public.registered_device_vehicle_bindings
 FOR EACH ROW EXECUTE FUNCTION public.bump_binding_metadata_revision();
COMMIT;
