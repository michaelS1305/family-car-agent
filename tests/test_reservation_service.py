import importlib.util
from datetime import datetime
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from identity import CurrentUser


database_stub = types.ModuleType("database")
database_stub.cancel_current_user_reservation = Mock()
database_stub.create_current_user_reservation = Mock()
database_stub.list_family_reservations = Mock()
database_stub.update_current_user_reservation = Mock()


def load_service():
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
            ("מיכאל", "2026-09-08T10:00:00", "2026-09-08T11:00:00", True),
            ("נועה", "2026-09-09T10:00:00", "2026-09-09T11:00:00", False),
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


if __name__ == "__main__":
    unittest.main()
