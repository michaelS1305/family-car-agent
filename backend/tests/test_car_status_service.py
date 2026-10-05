import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from identity import CurrentUser


class CarStatusServiceTests(unittest.TestCase):
    def setUp(self):
        # Load the real service without importing database.py or opening a pool.
        # Include the database imports of its real push_service dependency too.
        database_stub = types.ModuleType("database")
        for name in (
            "admit_car_transition_request", "apply_carplay_transition",
            "get_active_driver", "get_user_by_token", "get_family_by_id",
            "get_family_push_subscriptions", "remove_dead_push_subscription",
            "remove_push_subscription", "upsert_push_subscription",
        ):
            setattr(database_stub, name, Mock(
                side_effect=AssertionError(f"Unexpected database call: {name}")))
        for name in ("CarTransitionBusyError", "PushSubscriptionOwnershipError"):
            setattr(database_stub, name, type(name, (Exception,), {}))
        path = Path(__file__).resolve().parents[1] / "car_service.py"
        spec = importlib.util.spec_from_file_location("isolated_car_status_service", path)
        self.service = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"database": database_stub}):
            spec.loader.exec_module(self.service)

    def test_available_when_family_has_no_active_driver(self):
        current_user = CurrentUser(user_id=1, name="A1", family_id=10)

        with patch.object(self.service, "get_active_driver", return_value=None) as lookup:
            self.assertEqual(self.service.get_car_status(current_user), "available")

        lookup.assert_called_once_with(10)

    def test_occupied_when_family_has_an_active_driver(self):
        current_user = CurrentUser(user_id=3, name="B1", family_id=20)

        with patch.object(
            self.service, "get_active_driver",
            return_value=("B1", 3),
        ) as lookup:
            self.assertEqual(self.service.get_car_status(current_user), "occupied")

        lookup.assert_called_once_with(20)

    def test_user_without_family_fails_closed_before_lookup(self):
        current_user = CurrentUser(user_id=1, name="A1", family_id=None)

        with patch.object(self.service, "get_active_driver") as lookup:
            with self.assertRaises(self.service.CarStatusError) as raised:
                self.service.get_car_status(current_user)

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.code, "USER_WITHOUT_FAMILY")
        lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
