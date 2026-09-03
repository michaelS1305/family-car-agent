import unittest
from unittest.mock import patch

from car_service import CarStatusError, get_car_status
from identity import CurrentUser


class CarStatusServiceTests(unittest.TestCase):
    def test_available_when_family_has_no_active_driver(self):
        current_user = CurrentUser(user_id=1, name="A1", family_id=10)

        with patch("car_service.get_active_driver", return_value=None) as lookup:
            self.assertEqual(get_car_status(current_user), "available")

        lookup.assert_called_once_with(10)

    def test_occupied_when_family_has_an_active_driver(self):
        current_user = CurrentUser(user_id=3, name="B1", family_id=20)

        with patch(
            "car_service.get_active_driver",
            return_value=("B1", 3),
        ) as lookup:
            self.assertEqual(get_car_status(current_user), "occupied")

        lookup.assert_called_once_with(20)

    def test_user_without_family_fails_closed_before_lookup(self):
        current_user = CurrentUser(user_id=1, name="A1", family_id=None)

        with patch("car_service.get_active_driver") as lookup:
            with self.assertRaises(CarStatusError) as raised:
                get_car_status(current_user)

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.code, "USER_WITHOUT_FAMILY")
        lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
