"""Read-only catalogue contract and offline migration checks. No DB required."""
from contextlib import nullcontext
from pathlib import Path
import re
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from identity import CurrentUser
import vehicle_reference_api as api


class ManufacturerApiTests(unittest.TestCase):
    def setUp(self):
        self.user = CurrentUser(7, 'Member', 11, auth_user_id='owner')
        self.conn = Mock()
        self.pool = Mock(connection=lambda: nullcontext(self.conn))
        self.app = FastAPI()
        self.app.include_router(api.router)
        self.app.dependency_overrides[api.get_current_user] = lambda: self.user
        self.app.dependency_overrides[api.vehicle_pool] = lambda: self.pool
        self.client = TestClient(self.app)

    def test_read_uses_active_only_deterministic_query_and_scoped_identity(self):
        self.conn.execute.return_value.fetchall.return_value = [(4, 'GAC'), (2, 'אאודי')]
        with patch.object(api, '_bounded_connection', return_value=nullcontext(self.conn)), \
                patch.object(api, '_scope', return_value=nullcontext()) as scope:
            response = self.client.get('/api/reference/manufacturers')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{'id': 4, 'name_he': 'GAC'}, {'id': 2, 'name_he': 'אאודי'}])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        scope.assert_called_once_with(self.conn, self.user)
        self.conn.execute.assert_called_once_with(
            'SELECT id,name_he FROM vehicle_manufacturers WHERE is_active '
            'ORDER BY name_he COLLATE "C" ASC,id ASC')
        parameters = self.client.get('/openapi.json').json()['paths']['/api/reference/manufacturers']['get'].get('parameters', [])
        self.assertNotIn('family_id', [p['name'] for p in parameters])

    def test_auth_required_and_no_write_routes(self):
        def denied():
            raise HTTPException(401)
        self.app.dependency_overrides[api.get_current_user] = denied
        self.assertEqual(self.client.get('/api/reference/manufacturers').status_code, 401)
        self.conn.execute.assert_not_called()
        for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            self.assertEqual(self.client.request(method, '/api/reference/manufacturers').status_code, 405)


class VehicleMetadataMigrationTests(unittest.TestCase):
    def test_additive_schema_seed_acl_and_no_historical_rewrite(self):
        path = Path(__file__).resolve().parents[2] / 'supabase/manual_migrations/2026101301_vehicle_metadata_and_manufacturers.sql'
        sql = path.read_text(encoding='utf-8')
        seed = sql.split('INSERT INTO public.vehicle_manufacturers (name_he) VALUES', 1)[1].split('ON CONFLICT', 1)[0]
        names = [name.replace("''", "'") for name in re.findall(r"\('((?:[^']|'')*)'\)", seed)]
        expected = """אאודי|אוואטר|אומודה|אופל|אורה|איווייס|איון|איסוזו|אלפא רומיאו|אסטון מרטין|אקסלנטיקס|אקספנג|ארקפוקס|ב.מ.וו|באייק|ביואיק|בי ווי די|בנטלי|ג'אקו|ג'אק|ג'ילי|ג'יפ|ג'נסיס|GAC|גרייט וול|דאצ'יה|דודג'|דונגפנג|די אס|דייהו|דייהטסו|דיפאל|האמר|הונדה|הונגצ'י|WEY|וויה|וולבו|זיקר|טויוטה|טסלה|יגואר|יונדאי|למבורגיני|לינק אנד קו|ליפמוטור|לנד רובר|לנצ'יה|לקסוס|לוטוס|מ.ג|מזארטי|מזדה|מיני|מיצובישי|מקסוס|מרצדס בנץ|ניאו|ניסאן|סאאב|סאנגיונג|סובארו|סוזוקי|סיאט|סיטרואן|סמארט|סקודה|סקיוול|סרס|פאריזון|פולסטאר|פולקסווגן|פורד|פורשה|פורתינג|פיאט|פיג'ו|פרארי|צ'רי|קאדילאק|קופרה|קיה|KG Mobility|קרייזלר|RAM|רובר|רולס רויס|רנו|שברולט""".split('|')
        self.assertEqual(names, expected)
        self.assertEqual(len(set(names)), 89)
        self.assertIn('ON CONFLICT (name_he) DO NOTHING', sql)
        for column, kind in [('category', 'text'), ('manufacturer_id', 'integer'), ('model', 'text'), ('license_plate', 'text')]:
            self.assertIn(f'ADD COLUMN {column} {kind},', sql)
        self.assertIn('ON UPDATE NO ACTION ON DELETE RESTRICT', sql)
        self.assertIn("('hatchback','sedan','crossover','minivan','suv')", sql)
        self.assertIn('ENABLE ROW LEVEL SECURITY', sql)
        self.assertIn('NO FORCE ROW LEVEL SECURITY', sql)
        self.assertIn('FROM PUBLIC, anon, authenticated, service_role', sql)
        self.assertIn('GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER, TRUNCATE', sql)
        self.assertIn('GRANT USAGE, SELECT, UPDATE ON SEQUENCE', sql)
        statements = '\n'.join(line for line in sql.splitlines() if not line.startswith('--'))
        self.assertNotRegex(statements, r'(?i)\b(DROP|CREATE POLICY|UPDATE public\.vehicles|DELETE FROM)\b')
        self.assertEqual(sql.count('BEGIN;'), 1)
        self.assertEqual(sql.count('COMMIT;'), 1)
