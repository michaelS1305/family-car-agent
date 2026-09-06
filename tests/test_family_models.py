import unittest

from pydantic import ValidationError

from models import FamilyRoleUpdateRequest


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

    def test_rejects_client_supplied_identity_fields(self):
        with self.assertRaises(ValidationError):
            FamilyRoleUpdateRequest(role="parent", family_id=42, user_id=17)


if __name__ == "__main__":
    unittest.main()
