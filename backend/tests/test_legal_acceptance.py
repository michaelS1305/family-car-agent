"""Focused contracts; no live services or production database imports."""
import unittest
from unittest.mock import Mock, patch

from pydantic import ValidationError
from legal_acceptance import LegalAcceptance, record_legal_acceptance
from models import CreateFamilyRequest, JoinFamilyCompleteRequest
from tests.test_database_atomic_creation import load_database_module_without_real_connection, RecordingContext


ACCEPTANCE = dict(legal_accepted=True, terms_version="1.2", privacy_version="1.2")


class LegalAcceptanceTests(unittest.TestCase):
    def test_completion_models_require_exact_explicit_acknowledgment(self):
        for model, fields in (
            (CreateFamilyRequest, dict(family_name="Family", user_name="Name", address_resolution_token="opaque")),
            (JoinFamilyCompleteRequest, dict(user_name="Name")),
        ):
            self.assertTrue(model(**fields, **ACCEPTANCE).legal_accepted)
            invalid = [{}]
            for key in ACCEPTANCE:
                invalid.append({k: v for k, v in ACCEPTANCE.items() if k != key})
            invalid += [dict(ACCEPTANCE, legal_accepted=value) for value in (False, None, 1, 0, "true", "false", [], {})]
            for key in ("terms_version", "privacy_version"):
                invalid += [dict(ACCEPTANCE, **{key: value}) for value in ("1.1", "1.2 ", 1.2, None)]
            for key in ("auth_user_id", "accepted_at"):
                invalid.append(dict(ACCEPTANCE, **{key: "forged"}))
            for payload in invalid:
                with self.subTest(model=model.__name__, payload=payload), self.assertRaises(ValidationError):
                    model(**fields, **payload)

    def test_insert_never_updates_original_timestamp_or_uses_client_identity(self):
        conn = Mock()
        for _ in range(2):
            record_legal_acceptance(conn, "jwt-user", ACCEPTANCE)
        sql, args = conn.execute.call_args.args
        self.assertEqual(args, ("jwt-user", "1.2", "1.2"))
        self.assertIn("ON CONFLICT (auth_user_id, terms_version, privacy_version) DO NOTHING", sql)
        self.assertNotIn("accepted_at", sql)
        self.assertNotIn("UPDATE", sql)
        conn.reset_mock()
        with self.assertRaises(ValidationError):
            record_legal_acceptance(conn, "jwt-user", dict(ACCEPTANCE, accepted_at="forged"))
        conn.execute.assert_not_called()

    def test_acceptance_failure_rolls_back_both_completion_transactions(self):
        for creating in (True, False):
            db = load_database_module_without_real_connection()
            conn = Mock()
            transaction = RecordingContext()
            conn.transaction.return_value = transaction
            db.pool.connection.return_value = RecordingContext(conn)
            def execute(sql, args):
                if "INSERT INTO legal_acceptances" in sql:
                    self.assertTrue(transaction.entered)
                    raise RuntimeError("synthetic persistence failure")
                if "SELECT id FROM users" in sql:
                    return Mock(fetchone=lambda: None)
                return Mock(fetchone=lambda: (1,))
            conn.execute.side_effect = execute
            with patch.object(db, "_lock_address_confirmation", return_value=(b"digest", ("address", 1, 2))), \
                 patch.object(db, "_get_family_by_location", return_value=None), \
                 patch.object(db, "_allocate_family_code", side_effect=lambda c, assign: ("abc123", assign("abc123"))), \
                 patch.object(db, "_lock_pwa_join_session", return_value={"step": "user_name", "family_id": 1}):
                with self.assertRaisesRegex(RuntimeError, "synthetic persistence"):
                    if creating:
                        db.create_family_with_first_user("Family", None, "Name", auth_user_id="jwt-user", resolution_token="opaque", legal_acceptance=ACCEPTANCE)
                    else:
                        db.complete_pwa_join("jwt-user", "Name", legal_acceptance=ACCEPTANCE)
            self.assertTrue(transaction.rolled_back)
            self.assertFalse(transaction.committed)
            self.assertFalse(any("DELETE FROM" in call.args[0] for call in conn.execute.call_args_list))


if __name__ == "__main__":
    unittest.main()
