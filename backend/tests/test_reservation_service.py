import importlib.util
from datetime import datetime
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from identity import CurrentUser


database_stub = types.ModuleType("database")
database_stub.VEHICLE_UNSET = object()
database_stub.cancel_current_user_reservation = Mock()
database_stub.create_current_user_reservation = Mock()
database_stub.list_family_reservations = Mock()
database_stub.update_current_user_reservation = Mock()


def load_service(vehicle_unset=None):
    if vehicle_unset is not None:
        database_stub.VEHICLE_UNSET = vehicle_unset
    path = Path(__file__).resolve().parents[1] / "reservation_service.py"
    spec = importlib.util.spec_from_file_location("reservation_service_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"database": database_stub}):
        spec.loader.exec_module(module)
    return module


service = load_service()


class ReservationServiceTests(unittest.TestCase):
    def setUp(self):
        for mock in (
            database_stub.cancel_current_user_reservation,
            database_stub.create_current_user_reservation,
            database_stub.list_family_reservations,
            database_stub.update_current_user_reservation,
        ):
            mock.reset_mock(return_value=True, side_effect=True)
        database_stub.list_family_reservations.return_value = [
            ("מיכאל", "2026-09-08T10:00:00", "2026-09-08T11:00:00", True, '00000000-0000-0000-0000-000000000001', None, None),
            ("נועה", "2026-09-09T10:00:00", "2026-09-09T11:00:00", False, '00000000-0000-0000-0000-000000000002', None, None),
        ]
        database_stub.list_family_reservations.return_value = [
            (*row, '00000000-0000-0000-0000-000000000003', None)
            for row in database_stub.list_family_reservations.return_value
        ]
        database_stub.create_current_user_reservation.return_value = {"success": True}
        database_stub.update_current_user_reservation.return_value = {
            "success": True, "start_time": "2026-09-08T12:00:00", "end_time": "2026-09-08T13:00:00"
        }
        database_stub.cancel_current_user_reservation.return_value = {"success": True}
        self.now_patch = patch.object(
            service,
            "_local_now",
            return_value=datetime(2026, 9, 6, 12, 0, 0),
        )
        self.now_patch.start()

    def tearDown(self):
        self.now_patch.stop()

    @staticmethod
    def user(user_id=17, family_id=42):
        return CurrentUser(user_id=user_id, name="מיכאל", family_id=family_id)

    def test_default_list_uses_future_all_and_returns_no_internal_ids(self):
        result = service.list_reservations(self.user())
        database_stub.list_family_reservations.assert_called_once_with(
            42, 17, "future", "all", "2026-09-06T12:00:00"
        )
        self.assertEqual(result[0]["owner_name"], "מיכאל")
        self.assertTrue(result[0]["is_mine"])
        self.assertFalse(result[1]["is_mine"])
        for prohibited in ("reservation_id", "user_id", "family_id", "auth_user_id", "shortcut_token"):
            self.assertNotIn(prohibited, repr(result))

    def test_mine_and_past_filters_are_forwarded_with_current_identity(self):
        service.list_reservations(self.user(), "past", "mine")
        database_stub.list_family_reservations.assert_called_once_with(
            42, 17, "past", "mine", "2026-09-06T12:00:00"
        )

    def test_invalid_filters_are_rejected(self):
        for time_filter, scope in (("now", "all"), ("future", "family")):
            with self.subTest(time_filter=time_filter, scope=scope):
                with self.assertRaises(service.ReservationCenterError) as raised:
                    service.list_reservations(self.user(), time_filter, scope)
                self.assertEqual(raised.exception.code, "INVALID_RESERVATION_FILTER")

    def test_create_assigns_only_current_user_and_reuses_database_conflict_rules(self):
        created = service.create_reservation_for_current_user(
            self.user(),
            datetime(2026, 9, 8, 10),
            datetime(2026, 9, 8, 11),
        )
        database_stub.create_current_user_reservation.assert_called_once_with(
            17, 42, "2026-09-08T10:00:00", "2026-09-08T11:00:00"
        )
        self.assertEqual(created["owner_name"], "מיכאל")
        self.assertTrue(created["is_mine"])

        database_stub.create_current_user_reservation.return_value = {
            "success": False,
            "code": "RESERVATION_CONFLICT",
        }
        with self.assertRaises(service.ReservationCenterError) as raised:
            service.create_reservation_for_current_user(
                self.user(),
                datetime(2026, 9, 8, 10),
                datetime(2026, 9, 8, 11),
            )
        self.assertEqual(raised.exception.status_code, 409)

    def test_update_passes_current_identity_and_original_time_locator(self):
        service.update_reservation_for_current_user(
            self.user(),
            "2026-09-08T10:00:00",
            "2026-09-08T11:00:00",
            datetime(2026, 9, 8, 12),
            datetime(2026, 9, 8, 13),
        )
        database_stub.update_current_user_reservation.assert_called_once_with(
            17,
            42,
            "2026-09-08T10:00:00",
            "2026-09-08T11:00:00",
            "2026-09-06T12:00:00",
            datetime(2026, 9, 8, 12),
            datetime(2026, 9, 8, 13),
        )

    def test_cancel_passes_current_identity_and_original_time_locator(self):
        result = service.cancel_reservation_for_current_user(
            self.user(),
            "2026-09-08T10:00:00",
            "2026-09-08T11:00:00",
        )
        self.assertEqual(result, {"cancelled": True})
        database_stub.cancel_current_user_reservation.assert_called_once_with(
            17,
            42,
            "2026-09-08T10:00:00",
            "2026-09-08T11:00:00",
            "2026-09-06T12:00:00",
        )

    def test_past_or_foreign_targets_share_not_found_response(self):
        database_stub.update_current_user_reservation.return_value = {
            "success": False,
            "code": "RESERVATION_NOT_FOUND_OR_UNAVAILABLE",
        }
        with self.assertRaises(service.ReservationCenterError) as raised:
            service.update_reservation_for_current_user(
                self.user(),
                "2020-01-01T10:00:00",
                "2020-01-01T11:00:00",
                datetime(2026, 9, 8, 12),
                datetime(2026, 9, 8, 13),
            )
        self.assertEqual(raised.exception.code, "RESERVATION_NOT_FOUND_OR_UNAVAILABLE")
        self.assertEqual(raised.exception.status_code, 404)

    def test_invalid_or_past_new_interval_is_rejected_before_database(self):
        cases = (
            (datetime(2026, 9, 8, 11), datetime(2026, 9, 8, 10)),
            (datetime(2026, 9, 5, 10), datetime(2026, 9, 5, 11)),
        )
        for start, end in cases:
            with self.subTest(start=start, end=end):
                with self.assertRaises(service.ReservationCenterError):
                    service.create_reservation_for_current_user(self.user(), start, end)
        database_stub.create_current_user_reservation.assert_not_called()

    def test_missing_family_fails_closed(self):
        with self.assertRaises(service.ReservationCenterError) as raised:
            service.list_reservations(self.user(family_id=None))
        self.assertEqual(raised.exception.status_code, 403)

    def test_vehicle_required_preserves_safe_choices_in_structured_error(self):
        choices = [{'vehicle_ref': '00000000-0000-0000-0000-000000000001', 'display_name': 'Car'}]
        database_stub.create_current_user_reservation.return_value = {
            'success': False, 'code': 'VEHICLE_REQUIRED', 'message': 'יש לבחור רכב.', 'vehicles': choices}
        with self.assertRaises(service.ReservationCenterError) as raised:
            service.create_reservation_for_current_user(self.user(), '2026-09-08T10:00:00', '2026-09-08T11:00:00')
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.vehicles, choices)

    def test_explicit_general_update_and_opaque_locator_are_forwarded(self):
        ref = '00000000-0000-0000-0000-000000000001'
        service.update_reservation_for_current_user(self.user(), None, None,
            '2026-09-08T12:00:00', '2026-09-08T13:00:00', reservation_ref=ref, vehicle_ref=None)
        self.assertEqual(database_stub.update_current_user_reservation.call_args.kwargs,
                         {'reservation_ref': ref, 'vehicle_ref': None})

    def test_bounded_normalization_and_combined_filters(self):
        ref = '00000000-0000-0000-0000-000000000003'
        result = service.list_reservations(self.user(), range_start='2026-09-01T21:00:00Z',
            range_end='2026-09-03T00:00:00+03:00', vehicle_ref=ref, member_ref=ref)
        self.assertEqual(database_stub.list_family_reservations.call_args.kwargs, {
            'range_start': '2026-09-02T00:00:00', 'range_end': '2026-09-03T00:00:00',
            'vehicle_ref': ref, 'member_ref': ref})
        self.assertEqual(result[0]['member_ref'], ref)
        self.assertIsNone(result[0]['vehicle_category'])

    def test_invalid_bounded_filters_and_ranges(self):
        bounds = dict(range_start='2026-09-01T00:00:00', range_end='2026-09-02T00:00:00')
        cases = [
            ({'range_start': bounds['range_start']}, 'RANGE'),
            ({'range_end': bounds['range_end']}, 'RANGE'),
            ({**bounds, 'range_start': ''}, 'RANGE'),
            ({**bounds, 'range_end': 'bad'}, 'RANGE'),
            ({**bounds, 'range_end': bounds['range_start']}, 'RANGE'),
            ({**bounds, 'range_end': '2026-08-31T00:00:00'}, 'RANGE'),
            ({**bounds, 'range_end': '2026-10-13T00:00:01'}, 'RANGE'),
            ({**bounds, 'time_filter': 'future'}, 'FILTER'),
            ({**bounds, 'scope': ''}, 'FILTER'),
            ({'time_filter': ''}, 'FILTER'),
            ({'vehicle_ref': 'bad'}, 'FILTER'),
            ({'member_ref': ''}, 'FILTER'),
            ({**bounds, 'vehicle_ref': ''}, 'FILTER'),
            ({**bounds, 'member_ref': 'bad'}, 'FILTER'),
            ({**bounds, 'member_ref': '00000000-0000-0000-0000-000000000003', 'scope': 'mine'}, 'FILTER'),
        ]
        for kwargs, suffix in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(service.ReservationCenterError) as caught:
                service.list_reservations(self.user(), **kwargs)
            self.assertEqual(caught.exception.code, 'INVALID_RESERVATION_' + suffix)
            self.assertEqual(caught.exception.status_code, 422)
        database_stub.list_family_reservations.assert_not_called()

    def test_42_local_days_across_dst_and_mine(self):
        service.list_reservations(self.user(), scope='mine',
            range_start='2026-10-01T00:00:00+03:00', range_end='2026-11-12T00:00:00+02:00')
        self.assertEqual(database_stub.list_family_reservations.call_args.args[3], 'mine')
        self.assertEqual(database_stub.list_family_reservations.call_args.kwargs,
                         {'range_start': '2026-10-01T00:00:00', 'range_end': '2026-11-12T00:00:00'})

    def test_unavailable_filter_is_safe_404_and_empty_results_are_not_errors(self):
        database_stub.list_family_reservations.return_value = None
        with self.assertRaises(service.ReservationCenterError) as caught:
            service.list_reservations(self.user(), range_start='2026-09-01', range_end='2026-09-02',
                                     vehicle_ref='00000000-0000-0000-0000-000000000003')
        self.assertEqual(caught.exception.code, 'RESERVATION_FILTER_NOT_FOUND_OR_UNAVAILABLE')
        self.assertEqual(caught.exception.status_code, 404)
        self.assertNotIn('00000000', caught.exception.message)
        database_stub.list_family_reservations.return_value = []
        self.assertEqual(service.list_reservations(self.user()), [])

    def test_create_and_edit_forward_public_enrichment(self):
        metadata = dict(member_ref='00000000-0000-0000-0000-000000000003', vehicle_category='sedan')
        database_stub.create_current_user_reservation.return_value.update(metadata)
        database_stub.update_current_user_reservation.return_value.update(metadata)
        created = service.create_reservation_for_current_user(self.user(), '2026-09-08T10:00:00', '2026-09-08T11:00:00')
        edited = service.update_reservation_for_current_user(self.user(), None, None,
            '2026-09-08T12:00:00', '2026-09-08T13:00:00', reservation_ref='opaque')
        for result in (created, edited):
            for key, value in metadata.items():
                self.assertEqual(result[key], value)

    def test_list_metadata_preserves_general_and_legacy_vehicle_nulls(self):
        ref = '00000000-0000-0000-0000-000000000003'
        for vehicle_ref, name, category in ((None, None, None), (ref, 'Car', None), (ref, 'Retired car', 'suv')):
            database_stub.list_family_reservations.return_value = [
                ('User', '2026-09-01T00:00:00', '2026-09-02T00:00:00', False,
                 ref, vehicle_ref, name, ref, category)]
            result = service.list_reservations(self.user())[0]
            self.assertEqual((result['vehicle_ref'], result['vehicle_display_name'], result['vehicle_category']),
                             (vehicle_ref, name, category))
            self.assertEqual(result['member_ref'], ref)


if __name__ == "__main__":
    unittest.main()
