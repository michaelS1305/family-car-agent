"""DB-free checks of the real History route, service and query contract."""
import ast
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
from identity import CurrentUser
from models import CarHistoryResponse
from tests.test_history_service import service, database_stub, identified
from tests.test_car_history_database import CarHistoryDatabaseTests


REF = str(UUID(int=42))


class HistoryContractTests(unittest.TestCase):
    def setUp(self):
        database_stub.get_car_usage_history.reset_mock(return_value=True, side_effect=True)
        database_stub.get_car_usage_history.return_value = []
        # Register the actual route function without importing application startup/pools.
        source = Path(__file__).resolve().parents[1] / 'main.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        route = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'car_history')
        app = FastAPI()
        namespace = dict(app=app, Depends=Depends, Response=Response, HTTPException=HTTPException,
                         UUID=UUID, CurrentUser=CurrentUser, CarHistoryResponse=CarHistoryResponse,
                         get_current_user=lambda: CurrentUser(user_id=17, name='A', family_id=42),
                         get_car_history=service.get_car_history, CarHistoryError=service.CarHistoryError)
        exec(compile(ast.Module(body=[route], type_ignores=[]), str(source), 'exec'), namespace)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def row(self, sid, active=False):
        return identified([('A', '2026-09-01T10:00:00+00:00',
                            None if active else '2026-09-01T11:00:00+00:00',
                            active, sid, 'Car', REF)])[0]

    def test_default_is_additive_and_keeps_multiple_active_and_public_ids(self):
        database_stub.get_car_usage_history.return_value = [self.row(4, True), self.row(3, True), self.row(2)]
        response = self.client.get('/api/car/history')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        body = response.json()
        self.assertEqual(body['active_usage'], body['active_usages'][0])
        self.assertEqual(len(body['active_usages']), 2)
        for row in body['active_usages'] + body['recent_usage']:
            # Fields checked by the existing Web isActiveCarUsage guard remain strings.
            for key in ('name', 'started_at', 'vehicle_name', 'vehicle_ref', 'session_ref', 'member_ref'):
                self.assertIsInstance(row[key], str)
            self.assertNotIn('id', row)
            self.assertEqual(row['member_ref'], str(UUID(int=17)))
        self.assertIn('ended_at', body['recent_usage'][0])
        self.assertNotIn('ended_at', body['active_usage'])
        self.assertFalse(body['has_more'])
        self.assertIsNone(body['next_cursor'])

    def test_first_next_last_pages_keep_equal_timestamp_rows_distinct(self):
        database_stub.get_car_usage_history.side_effect = [
            [self.row(9, True), self.row(4), self.row(3), self.row(2)],
            [self.row(9, True), self.row(2), self.row(1)], []]
        first = self.client.get('/api/car/history?limit=2').json()
        self.assertTrue(first['has_more'])
        self.assertEqual(first['next_cursor'], str(UUID(int=3)))
        second = self.client.get('/api/car/history', params={'limit': 2, 'cursor': first['next_cursor']}).json()
        self.assertFalse(second['has_more'])
        self.assertIsNone(second['next_cursor'])
        refs = [r['session_ref'] for b in (first, second) for r in b['recent_usage']]
        self.assertEqual(refs, [str(UUID(int=n)) for n in (4, 3, 2, 1)])
        self.assertEqual(len(set(refs)), 4)
        self.assertEqual(first['active_usages'], second['active_usages'])
        self.assertEqual(database_stub.get_car_usage_history.call_args.kwargs['cursor'], UUID(int=3))
        empty = self.client.get('/api/car/history').json()
        self.assertEqual(empty['recent_usage'], [])
        self.assertFalse(empty['has_more'])

    def test_individual_and_combined_filters_pass_typed_values(self):
        filters = dict(vehicle_ref=REF, member_ref=REF, cursor=REF,
                       from_datetime='2026-09-01T12:00:00+03:00',
                       to_datetime='2026-09-01T10:00:00Z', limit='2')
        for params in [{k: v} for k, v in filters.items()] + [filters]:
            with self.subTest(params=params):
                response = self.client.get('/api/car/history', params=params)
                self.assertEqual(response.status_code, 200, response.text)
                call = database_stub.get_car_usage_history.call_args
                self.assertEqual(call.args, (42,))
                for k in ('vehicle_ref', 'member_ref', 'cursor'):
                    self.assertEqual(call.kwargs[k], UUID(REF) if k in params else None)
        values = database_stub.get_car_usage_history.call_args.kwargs
        self.assertEqual(values['from_datetime'].astimezone(timezone.utc).hour, 9)
        self.assertEqual(values['to_datetime'].hour, 10)
        self.assertEqual(values['completed_limit'], 2)

    def test_invalid_parameters_fail_before_database_read(self):
        invalid = [{'limit': n} for n in (0, -1, 51, 'bad')] + [
            {k: 'bad'} for k in ('cursor', 'vehicle_ref', 'member_ref')] + [
            {k: v} for k in ('from_datetime', 'to_datetime')
            for v in ('bad', '2026-09-01', '2026-09-01T12:00:00', '12345')] + [
            {'from_datetime': '2026-09-02T00:00:00Z', 'to_datetime': '2026-09-01T00:00:00Z'}]
        for params in invalid:
            with self.subTest(params=params):
                self.assertEqual(self.client.get('/api/car/history', params=params).status_code, 422)
        database_stub.get_car_usage_history.assert_not_called()

    def test_unavailable_cursor_is_generic(self):
        database_stub.get_car_usage_history.return_value = None
        response = self.client.get('/api/car/history', params={'cursor': REF})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['detail']['code'], 'INVALID_HISTORY_CURSOR')
        self.assertNotIn(REF, response.text)


class HistoryQueryTests(CarHistoryDatabaseTests):
    def test_combined_filtered_keyset_and_active_independence(self):
        from tests.test_database_atomic_creation import database
        start = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.connection.execute.return_value.fetchone.return_value = (start, 7)
        self.connection.execute.return_value.fetchall.return_value = []
        database.get_car_usage_history(42, completed_limit=2, cursor=UUID(REF),
            vehicle_ref=UUID(int=1), member_ref=UUID(int=2), from_datetime=start, to_datetime=start)
        lookup, active, completed = [c.args for c in self.connection.execute.call_args_list]
        self.assertIn('WHERE family_id=%s AND session_ref=%s AND ended_at IS NOT NULL', lookup[0])
        self.assertEqual(lookup[1], (42, UUID(REF)))
        self.assertEqual(active[1], (42,))
        for clause in ('WHERE s.family_id=%s', 'v.vehicle_ref=%s AND v.family_id=s.family_id',
                       'u.member_public_id=%s AND u.family_id=s.family_id', 's.started_at >= %s',
                       's.started_at <= %s', '(s.started_at,s.id) < (%s,%s)',
                       'ORDER BY s.started_at DESC,s.id DESC LIMIT %s'):
            self.assertIn(clause, completed[0])
        self.assertEqual(completed[1], (42, UUID(int=1), UUID(int=2), start, start, start, 7, 3))

    def test_missing_or_foreign_or_active_cursor_stops_before_data_query(self):
        from tests.test_database_atomic_creation import database
        self.connection.execute.return_value.fetchone.return_value = None
        self.assertIsNone(database.get_car_usage_history(42, cursor=UUID(REF)))
        self.assertEqual(self.connection.execute.call_count, 1)

    def test_foreign_vehicle_and_member_have_no_separate_existence_lookup(self):
        from tests.test_database_atomic_creation import database
        for field in ('vehicle_ref', 'member_ref'):
            with self.subTest(field=field):
                self.connection.reset_mock()
                self.connection.execute.return_value.fetchall.return_value = []
                self.assertEqual(database.get_car_usage_history(42, **{field: UUID(REF)}), [])
                self.assertEqual(self.connection.execute.call_count, 2)
                sql, params = self.connection.execute.call_args.args
                self.assertIn('WHERE s.family_id=%s', sql)
                self.assertEqual(params, (42, UUID(REF), 51))
