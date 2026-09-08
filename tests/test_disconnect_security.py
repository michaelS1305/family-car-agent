import ast
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from models import CarConnection, CarDisconnectRequest


ROOT = Path(__file__).resolve().parents[1]
INVALID = [(float('nan'), 35), (31, float('nan')),
           (float('inf'), 35), (31, float('-inf')),
           (91, 35), (-91, 35), (31, 181), (31, -181), (391, 35), (31, 395)]


class DisconnectSecurityTests(unittest.TestCase):
    def setUp(self):
        self.db = types.ModuleType('database')
        for name in ('get_user_by_token', 'get_active_driver', 'get_family_by_id',
                     'connect_car_atomically', 'disconnect_car_atomically'):
            setattr(self.db, name, Mock())
        self.push = types.ModuleType('push_service')
        self.push.dispatch_car_transition_notification = Mock()
        spec = importlib.util.spec_from_file_location('isolated_disconnect', ROOT / 'car_service.py')
        self.service = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'database': self.db, 'push_service': self.push}):
            spec.loader.exec_module(self.service)
        self.db.get_user_by_token.return_value = (1, 'Driver', 10)
        self.db.get_active_driver.return_value = ('Driver', 1)
        self.db.get_family_by_id.return_value = (10, 'Family', 'Address', 31, 35)
        self.db.disconnect_car_atomically.return_value = {
            'transition': 'disconnected', 'event_id': 123, 'event_time': 'test-time'
        }

    def assert_no_effects(self):
        self.db.disconnect_car_atomically.assert_not_called()
        self.db.connect_car_atomically.assert_not_called()
        self.push.dispatch_car_transition_notification.assert_not_called()

    def test_http_invalid_inputs_are_safe_422_before_service(self):
        # Execute the actual route/handler definitions without importing startup/DB.
        tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
        selected = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name in ('disconnect_car', 'safe_disconnect_validation_error')]
        app = FastAPI()
        handler = Mock()
        namespace = dict(app=app, CarDisconnectRequest=CarDisconnectRequest,
                         disconnect_user=handler, RequestValidationError=RequestValidationError,
                         JSONResponse=JSONResponse,
                         request_validation_exception_handler=request_validation_exception_handler)
        exec(compile(ast.Module(body=selected, type_ignores=[]), 'main.py', 'exec'), namespace)
        client = TestClient(app, raise_server_exceptions=False)
        bodies = [dict(shortcut_token='private-test-credential', latitude=str(lat), longitude=str(lon))
                  for lat, lon in INVALID]
        bodies += [dict(shortcut_token='private-test-credential'),
                   dict(shortcut_token='private-test-credential', latitude=None, longitude=35)]
        for body in bodies:
            with self.subTest(body=body):
                response = client.post('/car/disconnect', json=body)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json(), {'detail': 'Invalid disconnect request'})
        response = client.post('/car/disconnect', content='{"shortcut_token":"private-test-credential","latitude":NaN,"longitude":35}',
                               headers={'content-type': 'application/json'})
        self.assertEqual(response.status_code, 422)
        handler.assert_not_called()

    def test_direct_service_invalid_caller_is_side_effect_free(self):
        for lat, lon in INVALID + [(None, 35), (31, None)]:
            with self.subTest(lat=lat, lon=lon):
                self.service.disconnect_user('test', lat, lon)
                self.assert_no_effects()

    def test_invalid_stored_home_is_side_effect_free(self):
        for lat, lon in INVALID + [(None, 35), (31, None)]:
            with self.subTest(lat=lat, lon=lon):
                self.db.get_family_by_id.return_value = (10, 'Family', 'Address', lat, lon)
                self.service.disconnect_user('test', 31, 35)
                self.assert_no_effects()

    def test_invalid_calculated_distance_is_side_effect_free(self):
        for value in (float('nan'), float('inf'), float('-inf')):
            with patch.object(self.service, 'calculate_distance_meters', return_value=value):
                self.service.disconnect_user('test', 31, 35)
                self.assert_no_effects()
        with patch.object(self.service, 'calculate_distance_meters', side_effect=ValueError):
            self.service.disconnect_user('test', 31, 35)
            self.assert_no_effects()

    def test_success_preserves_metadata_without_distance(self):
        result = self.service.disconnect_user('test', 31, 35)
        self.assertEqual(result, {'message': 'הרכב שוחרר בהצלחה', 'result': {
            'message': 'Car disconnected', 'user': 'Driver', 'event_time': 'test-time'}})
        self.db.disconnect_car_atomically.assert_called_once_with(1, 10)
        self.push.dispatch_car_transition_notification.assert_called_once()

    def test_outside_response_has_no_distance(self):
        self.assertEqual(self.service.disconnect_user('test', 32, 35),
                         {'message': 'הרכב לא שוחרר כי הוא לא נמצא ליד הבית'})
        self.assert_no_effects()

    def test_exact_500_boundary_allowed(self):
        with patch.object(self.service, 'calculate_distance_meters', return_value=500):
            self.service.disconnect_user('test', 31, 35)
        self.db.disconnect_car_atomically.assert_called_once()

    def test_over_500_boundary_rejected(self):
        with patch.object(self.service, 'calculate_distance_meters', return_value=500.001):
            self.service.disconnect_user('test', 31, 35)
        self.assert_no_effects()

    def test_coordinate_endpoints_accepted_and_connect_unchanged(self):
        for lat, lon in [(-90, -180), (90, 180)]:
            CarDisconnectRequest(shortcut_token='test', latitude=lat, longitude=lon)
        self.assertIsNone(CarConnection(shortcut_token='test').latitude)


if __name__ == '__main__':
    unittest.main()
