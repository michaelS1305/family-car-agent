import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from identity import CurrentUser


database_stub = types.ModuleType("database")
database_stub.get_car_usage_history = Mock()


def load_service():
    path = Path(__file__).resolve().parents[1] / "history_service.py"
    spec = importlib.util.spec_from_file_location("history_service_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"database": database_stub}):
        spec.loader.exec_module(module)
    return module


service = load_service()


class HistoryServiceTests(unittest.TestCase):
    def setUp(self):
        database_stub.get_car_usage_history.reset_mock(return_value=True, side_effect=True)
        database_stub.get_car_usage_history.return_value = []

    @staticmethod
    def user(family_id=42):
        return CurrentUser(user_id=17, name="מיכאל", family_id=family_id)

    def test_family_is_derived_from_current_user_and_history_is_bounded(self):
        service.get_car_history(self.user())
        database_stub.get_car_usage_history.assert_called_once_with(
            42,
            completed_limit=50,
        )

    def test_active_usage_is_separate_and_has_no_fabricated_end(self):
        database_stub.get_car_usage_history.return_value = [
            ("מיכאל", "2026-09-06T08:00:00", None, True, 9),
            ("נועה", "2026-09-05T10:00:00", "2026-09-05T11:00:00", False, 7),
        ]
        result = service.get_car_history(self.user())
        self.assertEqual(result["active_usage"], {
            "name": "מיכאל",
            "started_at": "2026-09-06T08:00:00",
        })
        self.assertNotIn("ended_at", result["active_usage"])
        self.assertEqual(result["recent_usage"][0]["name"], "נועה")
        self.assertNotIn("sort_id", repr(result))

    def test_completed_usage_preserves_canonical_reverse_order_and_safe_fields(self):
        database_stub.get_car_usage_history.return_value = [
            ("נועה", "2026-09-05T10:00:00", "2026-09-05T11:00:00", False, 7),
            ("מיכאל", "2026-09-04T08:00:00", "2026-09-04T09:00:00", False, 3),
        ]
        result = service.get_car_history(self.user())
        self.assertEqual([usage["name"] for usage in result["recent_usage"]], ["נועה", "מיכאל"])
        for prohibited in ("event_id", "user_id", "family_id", "auth_user_id", "shortcut_token"):
            self.assertNotIn(prohibited, repr(result))

    def test_mapped_user_without_family_fails_closed(self):
        with self.assertRaises(service.CarHistoryError) as raised:
            service.get_car_history(self.user(family_id=None))
        self.assertEqual(raised.exception.status_code, 403)
        database_stub.get_car_usage_history.assert_not_called()


if __name__ == "__main__":
    unittest.main()
