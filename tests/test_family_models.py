import unittest

from pydantic import ValidationError

from models import (
    FamilyRoleUpdateRequest,
    ReservationCancelRequest,
    ReservationIntervalRequest,
    ReservationUpdateRequest,
)


class FamilyRoleModelTests(unittest.TestCase):
    def test_accepts_exact_cosmetic_roles_and_null(self):
        for role in ("parent", "child", None):
            with self.subTest(role=role):
                self.assertEqual(FamilyRoleUpdateRequest(role=role).role, role)

    def test_rejects_every_other_role(self):
        for role in ("admin", "creator", "driver", ""):
            with self.subTest(role=role):
                with self.assertRaises(ValidationError):
                    FamilyRoleUpdateRequest(role=role)


class ReservationModelTests(unittest.TestCase):
    def test_interval_parses_iso_times_and_forbids_browser_identity(self):
        request = ReservationIntervalRequest(
            start_time="2026-09-08T10:00:00",
            end_time="2026-09-08T11:00:00",
        )
        self.assertEqual(request.start_time.hour, 10)
        with self.assertRaises(ValidationError):
            ReservationIntervalRequest(
                start_time="2026-09-08T10:00:00",
                end_time="2026-09-08T11:00:00",
                user_id=999,
            )

    def test_original_locator_is_valid_iso_but_preserves_exact_text(self):
        update = ReservationUpdateRequest(
            original_start_time="2026-09-08T10:00:00.123",
            original_end_time="2026-09-08T11:00:00.123",
            start_time="2026-09-08T12:00:00",
            end_time="2026-09-08T13:00:00",
        )
        self.assertEqual(update.original_start_time, "2026-09-08T10:00:00.123")
        with self.assertRaises(ValidationError):
            ReservationCancelRequest(
                original_start_time="not-a-date",
                original_end_time="2026-09-08T11:00:00",
            )

    def test_rejects_client_supplied_identity_fields(self):
        with self.assertRaises(ValidationError):
            FamilyRoleUpdateRequest(role="parent", family_id=42, user_id=17)


if __name__ == "__main__":
    unittest.main()
