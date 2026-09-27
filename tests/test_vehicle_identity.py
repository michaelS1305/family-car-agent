import os
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import ValidationError

from identity import CurrentUser
from deletion_gate import IdentityUnavailable
import vehicle_identity as vi


class VehicleIdentityTests(unittest.TestCase):
    def setUp(self):
        self.user = CurrentUser(1, "User", 10)
        self.conn = Mock()
        self.gate = patch.object(vi, "require_user").start()
        self.addCleanup(patch.stopall)
        self.ref = uuid4()

    def rows(self, row):
        self.conn.execute.side_effect = [Mock(fetchone=lambda: (1,)), Mock(fetchone=lambda: row)]

    def test_vehicle_scope_and_safe_projection(self):
        self.rows((7, self.ref, "Car", None))
        vehicle = vi.resolve_vehicle(self.conn, self.user, self.ref)
        self.assertTrue(vehicle.is_active)
        self.assertEqual(set(vehicle.public().model_dump()), {"vehicle_ref", "display_name", "retired_at"})
        self.assertEqual(self.conn.execute.call_args.args[1], (10, self.ref))
        self.gate.assert_called_once_with(self.conn, 1)

    def test_missing_and_foreign_vehicle_have_same_error(self):
        for ref in (uuid4(), uuid4(), "invalid"):
            self.rows(None)
            with self.assertRaises(vi.VehicleIdentityError) as caught:
                vi.resolve_vehicle(self.conn, self.user, ref)
            self.assertEqual((caught.exception.code, caught.exception.status_code),
                             ("VEHICLE_NOT_FOUND_OR_UNAVAILABLE", 404))

    def test_retired_vehicle_can_be_read_but_not_resolved_as_active(self):
        row = (7, self.ref, "Car", datetime.now(timezone.utc))
        self.rows(row)
        self.assertFalse(vi.resolve_vehicle(self.conn, self.user, self.ref).is_active)
        self.rows(row)
        with self.assertRaises(vi.VehicleIdentityError):
            vi.resolve_vehicle(self.conn, self.user, self.ref, active_only=True)

    def test_device_owner_scope_sequence_and_projection(self):
        self.rows((8, self.ref, "ios", None, 42))
        device = vi.resolve_device(self.conn, self.user, self.ref)
        self.assertEqual(device.last_processed_sequence, 42)
        self.assertEqual(self.conn.execute.call_args.args[1], (1, self.ref))
        self.assertEqual(set(device.public().model_dump()), {"device_ref", "platform", "revoked_at"})
        self.assertTrue(all(call.args[0].startswith("SELECT") for call in self.conn.execute.call_args_list))

    def test_revoked_device_rejected_by_default_but_readable_explicitly(self):
        row = (8, self.ref, "android", datetime.now(timezone.utc), 42)
        self.rows(row)
        with self.assertRaises(vi.VehicleIdentityError):
            vi.resolve_device(self.conn, self.user, self.ref)
        self.rows(row)
        self.assertFalse(vi.resolve_device(self.conn, self.user, self.ref, active_only=False).is_active)

    def test_missing_device_is_generic(self):
        self.rows(None)
        with self.assertRaises(vi.VehicleIdentityError) as caught:
            vi.resolve_device(self.conn, self.user, self.ref)
        self.assertEqual(caught.exception.code, "DEVICE_NOT_FOUND_OR_UNAVAILABLE")

    def test_gate_and_stale_membership_fail_closed(self):
        self.gate.side_effect = IdentityUnavailable()
        with self.assertRaises(IdentityUnavailable):
            vi.list_vehicles(self.conn, self.user)
        self.conn.execute.assert_not_called()
        self.gate.side_effect = None
        self.conn.execute.return_value.fetchone.return_value = None
        with self.assertRaises(vi.VehicleIdentityError) as caught:
            vi.list_devices(self.conn, self.user)
        self.assertEqual(caught.exception.status_code, 403)

    def test_public_contract_rejects_internal_fields_and_bad_platform(self):
        with self.assertRaises(ValidationError):
            vi.VehicleView(vehicle_ref=self.ref, display_name="Car", retired_at=None, id=1)
        with self.assertRaises(ValidationError):
            vi.DeviceView(device_ref=self.ref, platform="other", revoked_at=None)


@unittest.skipUnless(os.environ.get("GEMINI_TEST_DATABASE_URL"), "No isolated PostgreSQL configured")
class VehicleIdentityPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        dsn = os.environ["GEMINI_TEST_DATABASE_URL"]
        url = urlsplit(dsn)
        if url.hostname not in {"localhost", "127.0.0.1", "::1"} or not url.path.startswith("/test_gemini"):
            raise RuntimeError("Only isolated local test_gemini databases are permitted")
        self.conn = psycopg.connect(dsn, connect_timeout=3)
        self.addCleanup(self.conn.close)
        # Transaction-local temp fixtures: use actual migration table definitions.
        # Nothing is committed; no public schema or production migration executes.
        self.conn.execute("CREATE TEMP TABLE families(id integer PRIMARY KEY)")
        self.conn.execute("CREATE TEMP TABLE users(id integer PRIMARY KEY, family_id integer)")
        sql = (Path(__file__).resolve().parents[1] / "supabase/manual_migrations/2026092001_vehicle_identity_foundation.sql").read_text()
        for table in ("vehicles", "registered_devices"):
            definition = sql.split(f"CREATE TABLE public.{table} (", 1)[1].split("\n);", 1)[0]
            self.conn.execute(f"CREATE TEMP TABLE {table} (" + definition.replace("public.", "pg_temp.") + "\n)")
        self.conn.execute("INSERT INTO families VALUES (10),(20)")
        self.conn.execute("INSERT INTO users VALUES (1,10),(2,10),(3,20)")
        # Identity gating has separate regression coverage; exercise real scope SQL here.
        self.gate = patch.object(vi, "require_user").start()
        self.addCleanup(patch.stopall)
        self.user = CurrentUser(1, "User", 10)

    def test_real_family_owner_resolution_and_lists(self):
        own = self.conn.execute("INSERT INTO vehicles(family_id,display_name) VALUES(10,'Own') RETURNING vehicle_ref").fetchone()[0]
        foreign = self.conn.execute("INSERT INTO vehicles(family_id,display_name) VALUES(20,'Other') RETURNING vehicle_ref").fetchone()[0]
        self.assertEqual(vi.resolve_vehicle(self.conn, self.user, own).display_name, "Own")
        self.assertEqual(len(vi.list_vehicles(self.conn, self.user)), 1)
        errors = []
        for ref in (foreign, uuid4()):
            with self.assertRaises(vi.VehicleIdentityError) as caught:
                vi.resolve_vehicle(self.conn, self.user, ref)
            errors.append((caught.exception.code, str(caught.exception)))
        self.assertEqual(errors[0], errors[1])
        for owner in (1, 2, 3):
            ref = self.conn.execute("INSERT INTO registered_devices(user_id,platform,last_processed_sequence) VALUES(%s,'ios',9) RETURNING device_ref", (owner,)).fetchone()[0]
            if owner == 1:
                self.assertEqual(vi.resolve_device(self.conn, self.user, ref).last_processed_sequence, 9)
            else:
                with self.assertRaises(vi.VehicleIdentityError):
                    vi.resolve_device(self.conn, self.user, ref)
        self.assertEqual(len(vi.list_devices(self.conn, self.user)), 1)
        self.assertEqual(self.conn.execute("SELECT DISTINCT last_processed_sequence FROM registered_devices").fetchall(), [(9,)])

    def test_real_lifecycle_and_schema_constraints(self):
        ref = self.conn.execute("INSERT INTO vehicles(family_id,display_name,retired_at) VALUES(10,'Old',clock_timestamp()+interval '1 second') RETURNING vehicle_ref").fetchone()[0]
        self.assertFalse(vi.resolve_vehicle(self.conn, self.user, ref).is_active)
        with self.assertRaises(vi.VehicleIdentityError):
            vi.resolve_vehicle(self.conn, self.user, ref, active_only=True)
        ref = self.conn.execute("INSERT INTO registered_devices(user_id,platform,revoked_at) VALUES(1,'android',clock_timestamp()+interval '1 second') RETURNING device_ref").fetchone()[0]
        with self.assertRaises(vi.VehicleIdentityError):
            vi.resolve_device(self.conn, self.user, ref)
        self.assertFalse(vi.resolve_device(self.conn, self.user, ref, active_only=False).is_active)
        import psycopg
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.conn.transaction():
                self.conn.execute("INSERT INTO registered_devices(user_id,platform) VALUES(1,'invalid')")
