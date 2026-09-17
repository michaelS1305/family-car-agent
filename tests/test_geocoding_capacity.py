"""Geocoding admission contracts and opt-in local PostgreSQL races."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
from pathlib import Path
from queue import Queue
import sys
import time
import types
import unittest
from unittest.mock import MagicMock, Mock, patch
from urllib.parse import urlsplit
from uuid import uuid4

database_stub = types.ModuleType("database")
database_stub.pool = Mock()
module_path = Path(__file__).resolve().parents[1] / "geocoding_capacity.py"
spec = importlib.util.spec_from_file_location("geocoding_capacity_under_test", module_path)
capacity = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"database": database_stub}):
    spec.loader.exec_module(capacity)


class GeocodingCapacityUnitTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(capacity, 'require_auth')
        guard.start()
        self.addCleanup(guard.stop)

    def test_logging_failure_does_not_change_capacity_rejection(self):
        rejection = capacity.GeocodingAdmissionError(
            "GEOCODING_RATE_LIMITED", 429, 8
        )
        with patch.object(capacity, "_acquire", side_effect=rejection), \
             patch.object(
                 capacity.logger,
                 "log",
                 side_effect=RuntimeError("logging unavailable"),
             ):
            with self.assertRaises(capacity.GeocodingAdmissionError) as raised:
                capacity.acquire("sensitive-auth-user")

        self.assertIs(raised.exception, rejection)
        self.assertEqual(raised.exception.status_code, 429)

    def test_logging_and_sqlstate_failures_cannot_mask_database_failure(self):
        class DatabaseFailure(Exception):
            @property
            def sqlstate(self):
                raise RuntimeError("metadata unavailable")

        original = DatabaseFailure("sensitive database detail")
        with patch.object(capacity, "_acquire", side_effect=original), \
             patch.object(
                 capacity.logger,
                 "log",
                 side_effect=RuntimeError("logging unavailable"),
             ):
            with self.assertRaises(DatabaseFailure) as raised:
                capacity.acquire("sensitive-auth-user")

        self.assertIs(raised.exception, original)

        with patch.object(capacity, "_acquire", side_effect=original):
            with self.assertLogs(capacity.logger, level="ERROR") as captured:
                with self.assertRaises(DatabaseFailure) as raised:
                    capacity.acquire("sensitive-auth-user")
        self.assertIs(raised.exception, original)
        output = " ".join(captured.output)
        self.assertIn("sqlstate=UNKNOWN", output)
        self.assertNotIn("metadata unavailable", output)
        self.assertNotIn("sensitive database detail", output)

    def test_policy_missing_and_database_failures_log_safe_stages(self):
        connection_context = MagicMock()
        conn = connection_context.__enter__.return_value
        conn.transaction.return_value.__enter__.return_value = None
        conn.execute.return_value.fetchone.return_value = None

        with patch.object(
            capacity.pool, "connection", return_value=connection_context
        ):
            with self.assertLogs(capacity.logger, level="ERROR") as captured:
                with self.assertRaisesRegex(RuntimeError, "not configured"):
                    capacity.acquire("sensitive-auth-user")
        output = " ".join(captured.output)
        self.assertIn("stage=capacity_policy_missing", output)
        self.assertNotIn("sensitive-auth-user", output)

        class DatabaseFailure(Exception):
            sqlstate = "42501"

        conn.execute.side_effect = DatabaseFailure("sensitive database detail")
        with patch.object(
            capacity.pool, "connection", return_value=connection_context
        ):
            with self.assertLogs(capacity.logger, level="ERROR") as captured:
                with self.assertRaises(DatabaseFailure):
                    capacity.acquire("sensitive-auth-user")
        output = " ".join(captured.output)
        self.assertIn("stage=capacity_database_error", output)
        self.assertIn("exception_class=DatabaseFailure", output)
        self.assertIn("sqlstate=42501", output)
        self.assertNotIn("sensitive database detail", output)
        self.assertNotIn("sensitive-auth-user", output)

    def test_capacity_rejection_and_release_failure_keep_existing_behavior(self):
        connection_context = MagicMock()
        conn = connection_context.__enter__.return_value
        conn.transaction.return_value.__enter__.return_value = None
        results = [Mock(), Mock(), Mock(), Mock()]
        results[0].fetchone.return_value = (20,)
        results[3].fetchone.return_value = (5.2,)
        conn.execute.side_effect = results

        with patch.object(
            capacity.pool, "connection", return_value=connection_context
        ):
            with self.assertLogs(capacity.logger, level="WARNING") as captured:
                with self.assertRaises(capacity.GeocodingAdmissionError) as raised:
                    capacity.acquire("sensitive-auth-user")
        self.assertEqual(raised.exception.code, "GEOCODING_USER_BUSY")
        output = " ".join(captured.output)
        self.assertIn("stage=capacity_rejected", output)
        self.assertIn("error_code=GEOCODING_USER_BUSY", output)
        self.assertNotIn("sensitive-auth-user", output)

        release_failure = RuntimeError("sensitive release detail")
        with patch.object(capacity, "acquire", return_value="attempt"), \
             patch.object(capacity, "finish", side_effect=release_failure):
            with self.assertLogs(capacity.logger, level="ERROR") as captured:
                with self.assertRaises(RuntimeError) as release_raised:
                    capacity.geocode_with_capacity(
                        "sensitive-auth-user", Mock(return_value="ok")
                    )
        self.assertIs(release_raised.exception, release_failure)
        output = " ".join(captured.output)
        self.assertIn("stage=permit_release_error", output)
        self.assertNotIn("sensitive release detail", output)
        self.assertNotIn("sensitive-auth-user", output)

        with patch.object(capacity, "acquire", return_value="attempt"), \
             patch.object(capacity, "finish", side_effect=release_failure), \
             patch.object(
                 capacity.logger,
                 "log",
                 side_effect=RuntimeError("logging unavailable"),
             ):
            with self.assertRaises(RuntimeError) as release_raised:
                capacity.geocode_with_capacity(
                    "sensitive-auth-user", Mock(return_value="ok")
                )
        self.assertIs(release_raised.exception, release_failure)

    def test_provider_deadline_is_shorter_than_active_permit(self):
        self.assertLess(
            capacity.PROVIDER_CALL_DEADLINE_SECONDS,
            capacity.PERMIT_SECONDS,
        )

    def test_success_releases_but_failure_retains_counted_attempt(self):
        provider = Mock(return_value="result")
        with patch.object(capacity, "acquire", return_value="attempt"), \
             patch.object(capacity, "finish") as finish:
            self.assertEqual(
                capacity.geocode_with_capacity("auth", provider, city="A"),
                "result",
            )
        finish.assert_called_once_with("attempt", uncertain=False)

        with patch.object(capacity, "acquire", return_value="attempt"), \
             patch.object(capacity, "finish") as finish:
            with self.assertRaises(TimeoutError):
                capacity.geocode_with_capacity(
                    "auth", Mock(side_effect=TimeoutError()), city="A"
                )
        finish.assert_called_once_with("attempt", uncertain=True)

    def test_zero_results_counts_and_provider_is_called_exactly_once(self):
        provider = Mock(return_value=None)
        with patch.object(capacity, "acquire", return_value="attempt"), \
             patch.object(capacity, "finish") as finish:
            self.assertIsNone(capacity.geocode_with_capacity("auth", provider))
        provider.assert_called_once_with()
        finish.assert_called_once_with("attempt", uncertain=False)

    def test_rejection_never_calls_provider(self):
        provider = Mock()
        rejection = capacity.GeocodingAdmissionError(
            "GEOCODING_RATE_LIMITED", 429, 2.1
        )
        with patch.object(capacity, "acquire", side_effect=rejection), \
             patch.object(capacity, "finish") as finish:
            with self.assertRaises(capacity.GeocodingAdmissionError):
                capacity.geocode_with_capacity("auth", provider)
        provider.assert_not_called()
        finish.assert_not_called()
        self.assertEqual(rejection.retry_after_seconds, 3)

    def test_migration_has_expected_policy_and_backend_only_acl(self):
        migration = Path(__file__).resolve().parents[1] / "supabase" / "manual_migrations" / "2026091402_geocoding_capacity.sql"
        sql = migration.read_text(encoding="utf-8")
        for fragment in (
            "CREATE TABLE public.geocoding_capacity_policies",
            "CREATE TABLE public.geocoding_attempts",
            "VALUES ('google-geocoding', 20)",
            "FROM PUBLIC, anon, authenticated",
            "REFERENCES auth.users(id) ON DELETE CASCADE",
        ):
            self.assertIn(fragment, sql)
        for prohibited in (
            "home_address", "latitude", "longitude", "API_KEY", "2026090602",
            "ENABLE ROW LEVEL SECURITY", "CREATE POLICY", "ALTER DEFAULT PRIVILEGES",
            "chat_requests", "gemini_call_permits",
        ):
            self.assertNotIn(prohibited, sql)


@unittest.skipUnless(
    os.environ.get("GEMINI_TEST_DATABASE_URL"),
    "No isolated local PostgreSQL test database configured",
)
class GeocodingPostgresConcurrencyTests(unittest.TestCase):
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
        guard = patch.object(capacity, 'require_auth')
        guard.start()
        self.addCleanup(guard.stop)
        self.schema = "geocoding_test_" + uuid4().hex
        with self.psycopg.connect(self.dsn) as conn:
            conn.execute(self.sql.SQL("CREATE SCHEMA {}").format(self.sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        self.pool = Mock()
        self.pool.connection = self.connection
        self.original_pool = capacity.pool
        capacity.pool = self.pool
        self.addCleanup(setattr, capacity, "pool", self.original_pool)
        with self.connection() as conn:
            conn.execute("CREATE TABLE geocoding_capacity_policies (capacity_pool text PRIMARY KEY, max_concurrency integer NOT NULL)")
            conn.execute("INSERT INTO geocoding_capacity_policies VALUES ('google-geocoding',20)")
            conn.execute("""CREATE TABLE geocoding_attempts (
                attempt_id uuid PRIMARY KEY, auth_user_id uuid NOT NULL,
                capacity_pool text NOT NULL, admitted_at timestamptz NOT NULL,
                permit_expires_at timestamptz)""")

    @contextmanager
    def connection(self):
        with self.psycopg.connect(self.dsn) as conn:
            conn.execute(self.sql.SQL("SET search_path TO {}").format(self.sql.Identifier(self.schema)))
            conn.commit()
            yield conn

    def drop_schema(self):
        with self.psycopg.connect(self.dsn) as conn:
            conn.execute(self.sql.SQL("DROP SCHEMA {} CASCADE").format(self.sql.Identifier(self.schema)))

    def test_concurrent_same_user_admits_exactly_one(self):
        auth = uuid4()
        def worker(_):
            try:
                return capacity.acquire(auth)
            except capacity.GeocodingAdmissionError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(worker, range(8)))
        self.assertEqual(results.count("GEOCODING_USER_BUSY"), 7)

    def test_global_capacity_is_twenty(self):
        with ThreadPoolExecutor(max_workers=24) as executor:
            results = list(executor.map(lambda _: self._acquire_code(uuid4()), range(25)))
        self.assertEqual(results.count("admitted"), 20)
        self.assertEqual(results.count("GEOCODING_CAPACITY_FULL"), 5)

    def _acquire_code(self, auth):
        try:
            capacity.acquire(auth)
            return "admitted"
        except capacity.GeocodingAdmissionError as error:
            return error.code

    def test_rolling_ten_minute_limit_and_identity_isolation(self):
        auth = uuid4()
        for _ in range(10):
            attempt = capacity.acquire(auth)
            capacity.finish(attempt)
        with self.assertRaises(capacity.GeocodingAdmissionError) as raised:
            capacity.acquire(auth)
        self.assertEqual(raised.exception.code, "GEOCODING_RATE_LIMITED")
        self.assertIsInstance(capacity.acquire(uuid4()), str)
        with self.connection() as conn:
            conn.execute(
                "UPDATE geocoding_attempts SET admitted_at = clock_timestamp() - INTERVAL '10 minutes 1 second', permit_expires_at=NULL WHERE auth_user_id=%s",
                (auth,),
            )
        self.assertIsInstance(capacity.acquire(auth), str)

    def test_uncertain_retention_and_bounded_race_safe_cleanup(self):
        retained = capacity.acquire(uuid4())
        capacity.finish(retained, uncertain=True)
        with self.connection() as conn:
            self.assertTrue(conn.execute(
                "SELECT permit_expires_at > clock_timestamp() FROM geocoding_attempts WHERE attempt_id=%s",
                (retained,),
            ).fetchone()[0])
            for _ in range(120):
                conn.execute(
                    "INSERT INTO geocoding_attempts VALUES (%s,%s,'google-geocoding',clock_timestamp()-INTERVAL '20 minutes',NULL)",
                    (uuid4(), uuid4()),
                )
        another = capacity.acquire(uuid4())
        with self.connection() as conn:
            old = conn.execute("SELECT count(*) FROM geocoding_attempts WHERE admitted_at < clock_timestamp()-INTERVAL '10 minutes'").fetchone()[0]
            retained_active = conn.execute("SELECT permit_expires_at > clock_timestamp() FROM geocoding_attempts WHERE attempt_id=%s", (retained,)).fetchone()[0]
        self.assertEqual(old, 20)
        self.assertTrue(retained_active)
        capacity.finish(another)

    def test_cleanup_rechecks_expiry_after_concurrent_uncertain_extension(self):
        retained = capacity.acquire(uuid4())
        with self.connection() as conn:
            conn.execute(
                "UPDATE geocoding_attempts SET permit_expires_at=clock_timestamp()-INTERVAL '1 second' WHERE attempt_id=%s",
                (retained,),
            )

        cleanup_pid = Queue()

        @contextmanager
        def cleanup_connection():
            with self.connection() as conn:
                cleanup_pid.put(conn.info.backend_pid)
                yield conn

        cleanup_pool = Mock()
        cleanup_pool.connection = cleanup_connection
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.connection() as retaining_conn:
                @contextmanager
                def retention_connection():
                    yield retaining_conn

                original_pool = capacity.pool
                capacity.pool = Mock(connection=retention_connection)
                try:
                    capacity.finish(retained, uncertain=True)
                finally:
                    capacity.pool = cleanup_pool
                future = executor.submit(capacity.acquire, uuid4())
                pid = cleanup_pid.get(timeout=5)
                with self.connection() as observer:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        if retaining_conn.info.backend_pid in observer.execute(
                            "SELECT pg_blocking_pids(%s)", (pid,)
                        ).fetchone()[0]:
                            break
                        time.sleep(0.01)
                    else:
                        self.fail("Cleanup did not compete with retained permit")
            future.result(timeout=5)
            capacity.pool = original_pool

        with self.connection() as conn:
            self.assertTrue(conn.execute(
                "SELECT permit_expires_at > clock_timestamp() FROM geocoding_attempts WHERE attempt_id=%s",
                (retained,),
            ).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
