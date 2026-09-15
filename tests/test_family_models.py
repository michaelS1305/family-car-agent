import unittest

from pydantic import ValidationError

from models import (
    CreateFamilyAddressRequest,
    CreateFamilyRequest,
    FamilyAddressResolveRequest,
    FamilyRoleUpdateRequest,
    JoinFamilyCodeRequest,
    JoinFamilyCompleteRequest,
    JoinFamilyNameRequest,
    ReservationCancelRequest,
    ReservationIntervalRequest,
    ReservationUpdateRequest,
    JoinFamilyAddressRequest,
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


class AddressModelTests(unittest.TestCase):
    def test_all_geocoding_requests_limit_address_to_200_characters(self):
        for model in (
            CreateFamilyAddressRequest,
            JoinFamilyAddressRequest,
            FamilyAddressResolveRequest,
        ):
            with self.subTest(model=model.__name__):
                self.assertEqual(len(model(home_address="א" * 200).home_address), 200)
                with self.assertRaises(ValidationError):
                    model(home_address="א" * 201)


class OnboardingModelTests(unittest.TestCase):
    def test_create_forbids_creator_supplied_family_code(self):
        values = {
            "family_name": "כהן",
            "address_resolution_token": "opaque",
            "user_name": "מיכאל",
        }
        self.assertEqual(CreateFamilyRequest(**values).family_name, "כהן")
        with self.assertRaises(ValidationError):
            CreateFamilyRequest(**values, family_code="chosen1")

    def test_name_fields_are_bounded_without_restricting_unicode(self):
        self.assertEqual(
            JoinFamilyNameRequest(family_name="א" * 100).family_name,
            "א" * 100,
        )
        self.assertEqual(
            JoinFamilyCompleteRequest(user_name="é" * 100).user_name,
            "é" * 100,
        )
        for model, field in (
            (CreateFamilyRequest, "family_name"),
            (CreateFamilyRequest, "user_name"),
            (JoinFamilyNameRequest, "family_name"),
            (JoinFamilyCompleteRequest, "user_name"),
        ):
            values = {
                "family_name": "כהן",
                "address_resolution_token": "opaque",
                "user_name": "מיכאל",
            } if model is CreateFamilyRequest else {}
            values[field] = "א" * 101
            with self.subTest(model=model.__name__, field=field):
                with self.assertRaises(ValidationError):
                    model(**values)

    def test_join_family_code_transport_rejects_oversized_input_early(self):
        for code in ("k7m2q9", "00ab12", "abcdef", "123456"):
            with self.subTest(code=code):
                self.assertEqual(JoinFamilyCodeRequest(family_code=code).family_code, code)
        with self.assertRaises(ValidationError):
            JoinFamilyCodeRequest(family_code="abc1234")


if __name__ == "__main__":
    unittest.main()
