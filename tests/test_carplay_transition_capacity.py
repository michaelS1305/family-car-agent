"""CarPlay transition admission contracts and opt-in local PostgreSQL races."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
from uuid import uuid4

from tests.test_database_atomic_creation import database


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "manual_migrations" / "2026091501_carplay_transition_rate_limit.sql"


def load_car_service(database_stub, push_stub):
    spec = importlib.util.spec_from_file_location(
        "car_service_capacity_under_test", ROOT / "car_service.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"database": database_stub, "push_service": push_stub}):
        spec.loader.exec_module(module)
    return module


class CarPlayTransitionServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = types.ModuleType("database")
        self.db.CarTransitionBusyError = type("CarTransitionBusyError", (Exception,), {})
        self.db.admit_car_transition_request = Mock(return_value={"admitted": True})
        self.db.connect_car_atomically = Mock(return_value={
            "transition": "connected", "event_id": 1, "event_time": "now",
        })
        self.db.disconnect_car_atomically = Mock(return_value={
            "transition": "disconnected", "event_id": 2, "event_time": "now",
        })
        self.db.get_active_driver = Mock(return_value=("Driver", 7))
        self.db.get_user_by_token = Mock(return_value=(7, "Driver", 11))
        self.db.get_family_by_id = Mock(return_value=(11, "Family", "Address", 31.0, 35.0))
        self.push = types.ModuleType("push_service")
        self.push.dispatch_car_transition_notification = Mock()
        self.service = load_car_service(self.db, self.push)

    def test_invalid_token_does_not_count(self):
        self.db.get_user_by_token.return_value = None
        self.assertEqual(
            self.service.connect_user("invalid"), {"message": "Invalid shortcut token"}
        )
        self.db.admit_car_transition_request.assert_not_called()

    def test_connect_noop_is_admitted_but_has_no_transition_effect(self):
        self.db.connect_car_atomically.return_value = {
            "transition": "none", "reason": "already_active", "current_driver": "Driver",
        }
        self.service.connect_user("token")
        self.db.admit_car_transition_request.assert_called_once_with(7, 11)
        self.push.dispatch_car_transition_notification.assert_not_called()

    def test_disconnect_prechecks_reject_before_admission(self):
        cases = [
            (None, (11, "Family", "Address", 31.0, 35.0), 31.0, 35.0),
            (("Other", 8), (11, "Family", "Address", 31.0, 35.0), 31.0, 35.0),
            (("Driver", 7), (11, "Family", "Address", None, None), 31.0, 35.0),
            (("Driver", 7), (11, "Family", "Address", 31.0, 35.0), 32.0, 35.0),
        ]
        for active, family, latitude, longitude in cases:
            with self.subTest(active=active, family=family):
                self.db.get_active_driver.return_value = active
                self.db.get_family_by_id.return_value = family
                self.service.disconnect_user("token", latitude, longitude)
                self.db.admit_car_transition_request.assert_not_called()
                self.db.disconnect_car_atomically.assert_not_called()
                self.db.admit_car_transition_request.reset_mock()
                self.db.disconnect_car_atomically.reset_mock()
                self.db.get_user_by_token.return_value = (7, "Driver", 11)

    def test_valid_disconnect_reaches_shared_admission_before_atomic_transition(self):
        calls = Mock()
        calls.attach_mock(self.db.admit_car_transition_request, "admit")
        calls.attach_mock(self.db.disconnect_car_atomically, "transition")
        self.service.disconnect_user("token", 31.0, 35.0)
        self.assertEqual([call[0] for call in calls.mock_calls], ["admit", "transition"])
        self.db.admit_car_transition_request.assert_called_once_with(7, 11)

    def test_rate_rejection_and_busy_are_side_effect_free(self):
        self.db.admit_car_transition_request.return_value = {
            "admitted": False,
            "code": "CARPLAY_USER_RATE_LIMITED",
            "retry_after_seconds": 2.1,
        }
        with self.assertRaises(self.service.CarTransitionError) as limited:
            self.service.connect_user("token")
        self.assertEqual(limited.exception.retry_after_seconds, 3)
        self.db.connect_car_atomically.assert_not_called()
        self.push.dispatch_car_transition_notification.assert_not_called()

        self.db.admit_car_transition_request.return_value = {"admitted": True}
        self.db.connect_car_atomically.side_effect = self.db.CarTransitionBusyError()
        with self.assertRaises(self.service.CarTransitionError) as busy:
            self.service.connect_user("token")
        self.assertEqual(busy.exception.code, "CARPLAY_TRANSITION_BUSY")
        self.db.admit_car_transition_request.assert_called()
        self.push.dispatch_car_transition_notification.assert_not_called()

    def test_lost_disconnect_response_retry_is_harmless_and_free(self):
        self.service.disconnect_user("token", 31.0, 35.0)
        self.db.get_active_driver.return_value = None
        self.assertEqual(
            self.service.disconnect_user("token", 31.0, 35.0),
            {"message": "הרכב כבר פנוי"},
        )
        self.db.disconnect_car_atomically.assert_called_once()
        self.db.admit_car_transition_request.assert_called_once()
        self.push.dispatch_car_transition_notification.assert_called_once()

    def test_migration_contract_is_backend_only_and_additive(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        for fragment in (
            "CREATE TABLE public.carplay_transition_admissions",
            "admission_id uuid PRIMARY KEY",
            "REFERENCES public.users(id) ON DELETE CASCADE",
            "REFERENCES public.families(id) ON DELETE CASCADE",
            "admitted_at timestamptz NOT NULL DEFAULT clock_timestamp()",
            "CHECK (isfinite(admitted_at))",
            "(user_id, admitted_at)",
            "(family_id, admitted_at)",
            "ON public.carplay_transition_admissions (admitted_at)",
            "FROM PUBLIC, anon, authenticated",
        ):
            self.assertIn(fragment, sql)
        for prohibited in (
            "ALTER TABLE public.users", "ALTER TABLE public.families",
            "ALTER TABLE public.car_events", "ENABLE ROW LEVEL SECURITY",
            "CREATE POLICY", "2026090602", "shortcut_token", "latitude", "longitude",
        ):
            self.assertNotIn(prohibited, sql)


@unittest.skipUnless(
    os.environ.get("GEMINI_TEST_DATABASE_URL"),
    "No isolated local PostgreSQL test database configured",
)
class CarPlayTransitionPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql

        cls.psycopg, cls.sql = psycopg, sql
        cls.dsn = os.environ["GEMINI_TEST_DATABASE_URL"]
        url = urlsplit(cls.dsn)
        if url.hostname not in {"localhost", "127.0.0.1", "::1"} or not url.path.startswith("/test_gemini"):
            raise RuntimeError("Only explicitly named local test_gemini databases are permitted")

    def setUp(self):
        self.schema = "carplay_capacity_test_" + uuid4().hex
        with self.psycopg.connect(self.dsn) as conn:
            conn.execute(self.sql.SQL("CREATE SCHEMA {}").format(self.sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        self.pool = Mock(connection=self.connection)
        self.original_pool = database.pool
        database.pool = self.pool
        self.addCleanup(setattr, database, "pool", self.original_pool)
        with self.connection() as conn:
            conn.execute("""CREATE TABLE carplay_transition_admissions (
                admission_id uuid PRIMARY KEY, user_id integer NOT NULL,
                family_id integer NOT NULL, admitted_at timestamptz NOT NULL)""")
            conn.execute("CREATE INDEX admissions_user_time ON carplay_transition_admissions(user_id, admitted_at)")
            conn.execute("CREATE INDEX admissions_family_time ON carplay_transition_admissions(family_id, admitted_at)")
            conn.execute("CREATE INDEX admissions_time ON carplay_transition_admissions(admitted_at)")
            conn.execute("""CREATE TABLE car_events (
                id bigserial PRIMARY KEY, user_id integer, driver_name text NOT NULL,
                status text NOT NULL, event_time text NOT NULL, family_id integer NOT NULL)""")

    @contextmanager
    def connection(self):
        with self.psycopg.connect(self.dsn) as conn:
            conn.execute(self.sql.SQL("SET search_path TO {}").format(self.sql.Identifier(self.schema)))
            conn.commit()
            yield conn

    def drop_schema(self):
        with self.psycopg.connect(self.dsn) as conn:
            conn.execute(self.sql.SQL("DROP SCHEMA {} CASCADE").format(self.sql.Identifier(self.schema)))

    def admissions(self):
        with self.connection() as conn:
            return conn.execute("SELECT count(*) FROM carplay_transition_admissions").fetchone()[0]

    def test_user_limit_and_rolling_expiry(self):
        for _ in range(5):
            self.assertTrue(database.admit_car_transition_request(1, 10)["admitted"])
        rejected = database.admit_car_transition_request(1, 10)
        self.assertEqual(rejected["code"], "CARPLAY_USER_RATE_LIMITED")
        self.assertEqual(self.admissions(), 5)
        with self.connection() as conn:
            conn.execute("UPDATE carplay_transition_admissions SET admitted_at=clock_timestamp()-INTERVAL '61 seconds'")
        self.assertTrue(database.admit_car_transition_request(1, 10)["admitted"])

    def test_family_limit_across_users_and_no_partial_row(self):
        for user_id in (1, 2):
            for _ in range(5):
                self.assertTrue(database.admit_car_transition_request(user_id, 10)["admitted"])
        rejected = database.admit_car_transition_request(3, 10)
        self.assertEqual(rejected["code"], "CARPLAY_FAMILY_RATE_LIMITED")
        self.assertEqual(self.admissions(), 10)

    def test_both_limits_choose_user_and_safe_retry_after(self):
        for user_id in (1, 2):
            for _ in range(5):
                database.admit_car_transition_request(user_id, 10)
        rejected = database.admit_car_transition_request(1, 10)
        self.assertEqual(rejected["code"], "CARPLAY_USER_RATE_LIMITED")
        self.assertGreater(rejected["retry_after_seconds"], 0)
        self.assertEqual(self.admissions(), 10)

    def test_concurrent_user_requests_admit_exactly_five(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(
                lambda _: database.admit_car_transition_request(1, 10), range(8)
            ))
        self.assertEqual(sum(result["admitted"] for result in results), 5)
        self.assertEqual(self.admissions(), 5)

    def test_concurrent_family_requests_admit_exactly_ten(self):
        with ThreadPoolExecutor(max_workers=15) as executor:
            results = list(executor.map(
                lambda user_id: database.admit_car_transition_request(user_id, 10),
                range(1, 16),
            ))
        self.assertEqual(sum(result["admitted"] for result in results), 10)
        self.assertEqual(self.admissions(), 10)

    def test_transition_lock_is_fail_fast_and_family_scoped(self):
        with self.connection() as holder:
            with holder.transaction():
                holder.execute(
                    "SELECT pg_advisory_xact_lock(%s, %s)",
                    (database.CAR_TRANSITION_LOCK_NAMESPACE, 10),
                )
                with self.assertRaises(database.CarTransitionBusyError):
                    database.connect_car_atomically(1, "A", 10)
                other_family = database.connect_car_atomically(2, "B", 20)
                self.assertEqual(other_family["transition"], "connected")

        with self.connection() as conn:
            events = conn.execute(
                "SELECT user_id, family_id, status FROM car_events ORDER BY id"
            ).fetchall()
        self.assertEqual(events, [(2, 20, "connected")])


if __name__ == "__main__":
    unittest.main()
