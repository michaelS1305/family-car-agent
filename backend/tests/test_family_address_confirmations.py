"""Disposable local PostgreSQL fixtures only; never execute a migration."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import math
import os
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from tests.test_database_atomic_creation import load_database_module_without_real_connection


database = load_database_module_without_real_connection()


@unittest.skipUnless(os.environ.get("GEMINI_TEST_DATABASE_URL"), "Isolated PostgreSQL not configured")
class FamilyAddressPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        self.psycopg, self.sql = psycopg, sql
        self.dsn = os.environ["GEMINI_TEST_DATABASE_URL"]
        url = urlsplit(self.dsn)
        if url.hostname not in {"localhost", "127.0.0.1", "::1"} or url.path != "/test_gemini":
            raise RuntimeError("Only isolated local test_gemini database allowed")
        self.schema = "address_test_" + uuid4().hex
        with psycopg.connect(self.dsn, connect_timeout=3) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        for name, value in (("pool", Mock(connection=self.connection)), ("UniqueViolation", psycopg.errors.UniqueViolation), ("ForeignKeyViolation", psycopg.errors.ForeignKeyViolation)):
            patcher = patch.object(database, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        with self.connection() as conn:
            conn.execute("CREATE TABLE auth_users (id uuid PRIMARY KEY)")
            conn.execute("""CREATE TABLE families (id serial PRIMARY KEY, name text,
                family_code text UNIQUE NOT NULL, home_address text NOT NULL,
                home_latitude double precision, home_longitude double precision,
                created_at text, created_by_user_id integer)""")
            conn.execute("""CREATE TABLE users (id serial PRIMARY KEY, name text,
                auth_user_id uuid CONSTRAINT users_auth_user_id_unique UNIQUE
                REFERENCES auth_users(id), family_id integer REFERENCES families(id))""")
            conn.execute("ALTER TABLE families ADD FOREIGN KEY (created_by_user_id) REFERENCES users(id)")
            conn.execute("CREATE TABLE family_code_history (code text PRIMARY KEY)")
            conn.execute("""CREATE TABLE family_address_confirmations (
                token_digest bytea PRIMARY KEY CHECK(octet_length(token_digest)=32),
                purpose text NOT NULL CHECK(purpose IN ('create_family','family_address_update')),
                auth_user_id uuid NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
                user_id integer REFERENCES users(id) ON DELETE CASCADE,
                family_id integer REFERENCES families(id) ON DELETE CASCADE,
                normalized_address text NOT NULL CHECK(length(btrim(normalized_address))>0),
                display_address text NOT NULL CHECK(length(btrim(display_address))>0),
                latitude double precision NOT NULL CHECK(latitude BETWEEN -90 AND 90),
                longitude double precision NOT NULL CHECK(longitude BETWEEN -180 AND 180),
                expires_at timestamptz NOT NULL DEFAULT(clock_timestamp()+INTERVAL '15 minutes')
                    CHECK(isfinite(expires_at)),
                CHECK((purpose='create_family' AND user_id IS NULL AND family_id IS NULL)
                   OR (purpose='family_address_update' AND user_id IS NOT NULL AND family_id IS NOT NULL)))""")
            conn.execute("CREATE UNIQUE INDEX pending_create ON family_address_confirmations(auth_user_id) WHERE purpose='create_family'")
            conn.execute("CREATE UNIQUE INDEX pending_update ON family_address_confirmations(user_id) WHERE purpose='family_address_update'")

    @contextmanager
    def connection(self):
        with self.psycopg.connect(self.dsn, connect_timeout=3) as conn:
            conn.execute(self.sql.SQL("SET search_path TO {}").format(self.sql.Identifier(self.schema)))
            conn.execute("SET statement_timeout='8s'")
            conn.commit()
            class IsolatedConnection:
                # Keep auth fixtures inside this test's schema, never auth/public.
                def execute(self, statement, parameters=()):
                    return conn.execute(statement.replace("auth.users", "auth_users"), parameters)
                def transaction(self):
                    return conn.transaction()
            yield IsolatedConnection()

    def drop_schema(self):
        with self.psycopg.connect(self.dsn, connect_timeout=3) as conn:
            conn.execute(self.sql.SQL("DROP SCHEMA {} CASCADE").format(self.sql.Identifier(self.schema)))

    def query(self, statement, parameters=()):
        with self.connection() as conn:
            cursor = conn.execute(statement, parameters)
            return cursor.fetchall() if cursor.description else []

    def auth(self):
        auth = str(uuid4())
        self.query("INSERT INTO auth_users VALUES (%s)", (auth,))
        return auth

    def issue(self, auth, latitude=0, longitude=0, user=None, family=None, address="confirmed"):
        return database.issue_family_address_confirmation(auth, address, "display", latitude, longitude, user_id=user, family_id=family)

    def create(self, auth, token):
        return database.create_family_with_first_user("family", None, "creator", auth_user_id=auth, resolution_token=token)

    def family(self, latitude=10, longitude=10):
        auth = self.auth()
        family = self.create(auth, self.issue(auth, latitude, longitude))
        user = self.query("SELECT id FROM users WHERE auth_user_id=%s", (auth,))[0][0]
        return auth, user, family

    def update(self, identity, token):
        auth, user, family = identity
        return database.update_family_address(user, family, auth, token)

    def test_digest_bindings_ttl_and_independent_connections(self):
        auth = self.auth()
        token = self.issue(auth)
        row = self.query("SELECT token_digest,purpose,auth_user_id,user_id,family_id,expires_at-clock_timestamp() FROM family_address_confirmations")[0]
        self.assertEqual(row[0], hashlib.sha256(token.encode("ascii")).digest())
        self.assertNotIn(token, repr(row))
        self.assertEqual(row[1:5], ("create_family", UUID(auth), None, None))
        self.assertTrue(890 < row[5].total_seconds() <= 900)
        # A fresh module has no process-local state and consumes the same row.
        other = load_database_module_without_real_connection()
        with patch.object(other, "pool", database.pool):
            other.create_family_with_first_user("family", None, "creator", auth_user_id=auth, resolution_token=token)
        self.assertEqual(self.query("SELECT count(*) FROM family_address_confirmations"), [(0,)])
        self.assertEqual(self.query("SELECT count(*) FROM family_code_history"), [(1,)])

    def test_replacement_expiration_wrong_identity_and_replay(self):
        auth, stranger = self.auth(), self.auth()
        old, token = self.issue(auth), self.issue(auth)
        for who, value in ((auth, old), (stranger, token)):
            with self.assertRaises(database.AddressConfirmationInvalidError):
                self.create(who, value)
        self.query("UPDATE family_address_confirmations SET expires_at=clock_timestamp()-INTERVAL '1 second'")
        with self.assertRaises(database.AddressConfirmationInvalidError):
            self.create(auth, token)
        token = self.issue(auth)
        self.create(auth, token)
        with self.assertRaises(database.AddressConfirmationInvalidError):
            self.create(auth, token)

    def test_update_exact_bindings_purpose_and_creator(self):
        identity = self.family()
        auth, user, family = identity
        token = self.issue(auth, 10, 10, user, family)
        for who, uid, fid in ((self.auth(), user, family), (auth, user+1, family), (auth, user, family+1)):
            with self.assertRaises(database.AddressConfirmationInvalidError):
                database.update_family_address(uid, fid, who, token)
        with self.assertRaises(database.AddressConfirmationInvalidError):
            self.create(auth, token)
        self.query("UPDATE families SET created_by_user_id=NULL WHERE id=%s", (family,))
        with self.assertRaises(database.FamilyAddressForbiddenError):
            self.update(identity, token)
        with self.assertRaises(database.FamilyAddressForbiddenError):
            self.issue(auth, 10, 10, user, family)
        self.assertEqual(self.query("SELECT count(*) FROM family_address_confirmations"), [(1,)])

    def test_create_eligibility_and_rollback(self):
        auth = self.auth()
        token = self.issue(auth)
        with patch.object(database, "_allocate_family_code", side_effect=RuntimeError("fixture failure")):
            with self.assertRaises(RuntimeError):
                self.create(auth, token)
        self.assertEqual(self.query("SELECT count(*) FROM users"), [(0,)])
        self.assertEqual(self.query("SELECT count(*) FROM families"), [(0,)])
        self.assertEqual(self.query("SELECT count(*) FROM family_address_confirmations"), [(1,)])
        self.create(auth, token)
        with self.assertRaises(database.AuthUserAlreadyMappedError):
            self.issue(auth)

    def test_update_failure_rolls_back_then_same_token_succeeds(self):
        identity = self.family()
        auth, user, family = identity
        token = self.issue(auth, 11, 11, user, family, "reject")
        self.query("ALTER TABLE families ADD CONSTRAINT fixture_failure CHECK(home_address <> 'reject')")
        with self.assertRaises(self.psycopg.errors.CheckViolation):
            self.update(identity, token)
        self.assertEqual(self.query("SELECT home_latitude FROM families"), [(10.0,)])
        self.assertEqual(self.query("SELECT count(*) FROM family_address_confirmations"), [(1,)])
        self.query("ALTER TABLE families DROP CONSTRAINT fixture_failure")
        self.assertEqual(self.update(identity, token), ("reject",))
        with self.assertRaises(database.AddressConfirmationInvalidError):
            self.update(identity, token)

    def race(self, operations, expected_error=database.FamilyAlreadyExistsAtLocationError):
        barrier = threading.Barrier(len(operations))
        def run(operation):
            barrier.wait(timeout=5)
            try:
                operation()
                return "success"
            except expected_error:
                return "rejected"
        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            results = list(executor.map(run, operations))
        self.assertEqual(sorted(results), ["rejected", "success"])

    def test_create_create_race(self):
        a, b = self.auth(), self.auth()
        ta, tb = self.issue(a), self.issue(b)
        self.race([lambda: self.create(a, ta), lambda: self.create(b, tb)])
        self.assertEqual(self.query("SELECT count(*) FROM families"), [(1,)])
        self.assertEqual(self.query("SELECT count(*) FROM family_code_history"), [(1,)])

    def test_create_update_race(self):
        identity = self.family()
        auth = self.auth()
        create_token = self.issue(auth)
        update_token = self.issue(identity[0], 0, 0, identity[1], identity[2])
        self.race([lambda: self.create(auth, create_token), lambda: self.update(identity, update_token)])

    def test_update_update_race(self):
        a, b = self.family(10, 10), self.family(20, 20)
        ta, tb = self.issue(a[0], 0, 0, a[1], a[2]), self.issue(b[0], 0, 0, b[1], b[2])
        self.race([lambda: self.update(a, ta), lambda: self.update(b, tb)])

    def test_same_token_concurrent_consumption(self):
        auth = self.auth()
        token = self.issue(auth)
        self.race([lambda: self.create(auth, token)]*2, database.AddressConfirmationInvalidError)
        self.assertEqual(self.query("SELECT count(*) FROM families"), [(1,)])

    def test_boundary_null_and_own_family_exclusion(self):
        a = self.family(0, 0)
        degrees = lambda meters: math.degrees(meters/6371000)
        with self.connection() as conn:
            self.assertIsNotNone(database._get_family_by_location(conn, 0, degrees(50)))
            self.assertIsNone(database._get_family_by_location(conn, 0, degrees(50.01)))
        b = self.family(0, degrees(80))
        # Own home is closer (35m) but must not mask the other home (45m).
        token = self.issue(a[0], 0, degrees(35), a[1], a[2])
        with self.assertRaises(database.FamilyAlreadyExistsAtLocationError):
            self.update(a, token)
        token = self.issue(a[0], 0, 0, a[1], a[2])
        self.update(a, token)
        self.query("UPDATE families SET home_latitude=NULL, home_longitude=NULL WHERE id=%s", (b[2],))
        token = self.issue(a[0], 0, degrees(80), a[1], a[2])
        self.update(a, token)

    def test_stale_confirmation_rechecks_and_remains_retryable(self):
        a, b = self.auth(), self.auth()
        stale = self.issue(a)
        self.create(b, self.issue(b))
        with self.assertRaises(database.FamilyAlreadyExistsAtLocationError):
            self.create(a, stale)
        self.assertEqual(self.query("SELECT count(*) FROM family_address_confirmations"), [(1,)])

    def test_update_replacement_and_non_creator_issuance(self):
        identity = self.family()
        auth, user, family = identity
        old = self.issue(auth, 10, 10, user, family)
        token = self.issue(auth, 11, 11, user, family)
        with self.assertRaises(database.AddressConfirmationInvalidError):
            self.update(identity, old)
        stranger = self.auth()
        member = self.query("INSERT INTO users(name,auth_user_id,family_id) VALUES ('member',%s,%s) RETURNING id", (stranger, family))[0][0]
        with self.assertRaises(database.FamilyAddressForbiddenError):
            self.issue(stranger, 10, 10, member, family)
        self.update(identity, token)
        self.assertEqual(self.query("SELECT home_latitude,home_longitude FROM families"), [(11.0, 11.0)])

    def test_expiry_checked_after_confirmation_row_lock_wait(self):
        auth = self.auth()
        token = self.issue(auth)
        entered = threading.Event()
        original = database._lock_address_confirmation
        def entering(*args, **kwargs):
            entered.set()
            return original(*args, **kwargs)
        with patch.object(database, "_lock_address_confirmation", side_effect=entering), ThreadPoolExecutor(max_workers=1) as executor:
            with self.connection() as holder:
                holder.execute("SELECT token_digest FROM family_address_confirmations FOR UPDATE")
                future = executor.submit(self.create, auth, token)
                self.assertTrue(entered.wait(5))
                # Expire while the consumer waits on this row; then commit.
                holder.execute("UPDATE family_address_confirmations SET expires_at=clock_timestamp()-INTERVAL '1 second'")
            with self.assertRaises(database.AddressConfirmationInvalidError):
                future.result(timeout=10)
        self.assertEqual(self.query("SELECT count(*) FROM families"), [(0,)])

    def test_cleanup_bounded_and_does_not_remove_live_confirmations(self):
        for _ in range(102):
            auth = self.auth()
            self.query("""INSERT INTO family_address_confirmations
                (token_digest,purpose,auth_user_id,normalized_address,display_address,latitude,longitude,expires_at)
                VALUES (%s,'create_family',%s,'test','test',0,0,clock_timestamp()-INTERVAL '1 second')""",
                (hashlib.sha256(auth.encode("ascii")).digest(), auth))
        live_auth = self.auth()
        self.issue(live_auth)
        self.assertEqual(self.query("SELECT count(*) FROM family_address_confirmations WHERE expires_at<=clock_timestamp()"), [(2,)])
        self.assertEqual(self.query("SELECT count(*) FROM family_address_confirmations WHERE expires_at>clock_timestamp()"), [(1,)])
