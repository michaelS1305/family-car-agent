"""Offline migration contract; never executes the prepared migration."""
from pathlib import Path
import unittest


class AuthorityMigrationTests(unittest.TestCase):
    def test_minimal_binding_is_backend_only_and_family_constrained(self):
        sql = (Path(__file__).resolve().parents[1] /
               'supabase/manual_migrations/2026092502_carplay_vehicle_authority.sql').read_text()
        for fragment in (
            'BEGIN;', 'COMMIT;', 'user_id integer PRIMARY KEY', 'vehicle_id integer NOT NULL',
            'REFERENCES public.users(id,family_id) ON DELETE CASCADE',
            'REFERENCES public.vehicles(id,family_id) ON DELETE CASCADE',
            'ENABLE ROW LEVEL SECURITY', 'FROM PUBLIC, anon, authenticated',
            'DROP TRIGGER car_events_broadcast_car_status ON public.car_events',
            "WHEN (NEW.admission_outcome = 'accepted')",
            'EXECUTE FUNCTION public.broadcast_car_status_changed()',
            'AFTER DELETE ON public.users', "SET search_path TO ''",
        ):
            self.assertIn(fragment, sql)
        for forbidden in ('CREATE OR REPLACE', 'DROP TABLE', 'INSERT INTO public.car_events',
                          'GRANT', 'CREATE POLICY', 'can_receive_car_status_topic',
                          'ALTER TABLE public.families', 'shortcut_token', 'latitude', 'longitude'):
            self.assertNotIn(forbidden, sql)

    def test_no_legacy_state_reconstruction_or_mutation_remains(self):
        root = Path(__file__).resolve().parents[1]
        database = (root / 'database.py').read_text(encoding='utf-8')
        service = (root / 'car_service.py').read_text(encoding='utf-8')
        self.assertNotIn('FROM car_events', database)
        self.assertNotIn('INSERT INTO car_events', database)
        self.assertNotIn('connect_car_atomically', service)
        self.assertNotIn('disconnect_car_atomically', service)
        deletion = (root / 'account_deletion.py').read_text(encoding='utf-8')
        self.assertIn('DELETE FROM car_events', deletion)  # privacy, not authority
        self.assertNotIn('_insert_car_event_on_connection', deletion)
