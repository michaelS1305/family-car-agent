"""Real PostgreSQL admission tests in a disposable, uniquely named local schema."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

from identity import CurrentUser
import vehicle_admission as va
from vehicle_reconciliation import ReconciliationError


BASE = datetime(2020, 1, 1, tzinfo=timezone.utc)


class EnvelopeTests(unittest.TestCase):
    def test_malformed_never_opens_transaction(self):
        event = va.NativeEvent(uuid4(), uuid4(), uuid4(), "take", BASE, 1)
        for invalid in (None, replace(event, device_sequence=True), replace(event, device_sequence=0),
                        replace(event, occurred_at=BASE.replace(tzinfo=None)),
                        replace(event, event_type="return"), replace(event, take_event_id=uuid4()),
                        replace(event, device_sequence=2**63), replace(event, event_id="invalid")):
            self.assertEqual(va.admit_native_event(None, None, invalid).kind, "malformed")


@unittest.skipUnless(os.environ.get("GEMINI_TEST_DATABASE_URL"), "No isolated local PostgreSQL configured")
class VehicleAdmissionPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        self.pg, self.sql = psycopg, sql
        self.dsn = os.environ["GEMINI_TEST_DATABASE_URL"]
        url = urlsplit(self.dsn)
        if url.hostname not in {"127.0.0.1", "localhost", "::1"} or url.path != "/test_gemini":
            raise RuntimeError("Only disposable local test_gemini permitted")
        self.schema = "vehicle_admission_test_" + uuid4().hex
        with psycopg.connect(self.dsn, connect_timeout=3) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        with self.connection() as conn:
            conn.execute("CREATE TABLE auth_users(id uuid PRIMARY KEY)")
            conn.execute("CREATE TABLE account_deletion_jobs(auth_user_id uuid PRIMARY KEY)")
            conn.execute("CREATE TABLE families(id integer PRIMARY KEY, created_by_user_id integer)")
            conn.execute("CREATE TABLE users(id integer PRIMARY KEY,family_id integer REFERENCES families,auth_user_id uuid UNIQUE REFERENCES auth_users)")
            # Exact foundation constraints, functions, triggers and indexes, in
            # an isolated schema. Not execution of the production migration.
            source = (Path(__file__).resolve().parents[1] / "supabase/manual_migrations/2026092001_vehicle_identity_foundation.sql").read_text()
            ddl = source.split("ALTER TABLE public.users ADD CONSTRAINT", 1)[1].split("-- Nullable-first UUID backfill", 1)[0]
            conn.execute(("ALTER TABLE public.users ADD CONSTRAINT" + ddl).replace("public.", self.schema + "."))
            conn.execute("INSERT INTO families(id) VALUES(10),(20)")
        self.users = {}
        for user_id, family in ((1, 10), (2, 10), (3, 20)):
            auth = uuid4()
            self.query("INSERT INTO auth_users VALUES(%s)", (auth,))
            self.query("INSERT INTO users VALUES(%s,%s,%s)", (user_id, family, auth))
            self.users[user_id] = CurrentUser(user_id, "User", family, auth_user_id=str(auth))
        self.devices = {user: self.query("INSERT INTO registered_devices(user_id,platform) VALUES(%s,'ios') RETURNING device_ref", (user,))[0][0] for user in self.users}
        self.vehicles = [self.query("INSERT INTO vehicles(family_id,display_name) VALUES(%s,'Car') RETURNING vehicle_ref", (family,))[0][0] for family in (10, 10, 20)]

    @contextmanager
    def connection(self):
        with self.pg.connect(self.dsn, connect_timeout=3) as conn:
            conn.execute(self.sql.SQL("SET search_path TO {},pg_catalog").format(self.sql.Identifier(self.schema)))
            conn.execute("SET statement_timeout='10s'")
            conn.commit()

            class Isolated:
                def execute(inner, query, params=None):
                    return conn.execute(query.replace("auth.users", "auth_users"), params)

                def transaction(inner):
                    return conn.transaction()

            yield Isolated()

    def drop_schema(self):
        with self.pg.connect(self.dsn, connect_timeout=3) as conn:
            conn.execute(self.sql.SQL("DROP SCHEMA {} CASCADE").format(self.sql.Identifier(self.schema)))

    def query(self, query, params=None):
        with self.connection() as conn:
            cursor = conn.execute(query, params)
            return cursor.fetchall() if cursor.description else []

    def event(self, seq=1, minute=0, user=1, vehicle=0, cause=None, device=None):
        return va.NativeEvent(uuid4(), device or self.devices[user], self.vehicles[vehicle],
                              "return" if cause else "take", BASE + timedelta(minutes=minute), seq, cause)

    def admit(self, event, user=1):
        with self.connection() as conn:
            return va.admit_native_event(conn, self.users[user], event)

    def sessions(self):
        return self.query("SELECT session_ref,user_id,vehicle_id,started_at,ended_at,end_reason,start_event_id,end_event_id,checkpoint_generation FROM vehicle_driver_sessions ORDER BY started_at,id")

    def snapshot(self):
        return tuple(self.query(f"SELECT * FROM {table} ORDER BY id") for table in
                     ("vehicle_events", "vehicle_driver_sessions", "registered_devices"))

    def sequence(self, user=1):
        return self.query("SELECT last_processed_sequence FROM registered_devices WHERE device_ref=%s", (self.devices[user],))[0][0]

    def terminal(self, event, outcome, user=1):
        before = self.sessions()
        result = self.admit(event, user)
        self.assertEqual(result, va.AdmissionResult("terminal", outcome))
        self.assertEqual(self.sessions(), before)
        self.assertEqual(self.sequence(user), event.device_sequence)
        self.assertEqual(self.query("SELECT admission_outcome FROM vehicle_events WHERE event_id=%s", (event.event_id,)), [(outcome,)])

    def test_take_return_and_stable_ref(self):
        take = self.event()
        self.assertEqual(self.admit(take).kind, "accepted")
        ref = self.sessions()[0][0]
        self.assertEqual(self.sequence(), 1)
        self.assertEqual(self.admit(self.event(2, 1, cause=take.event_id)).kind, "accepted")
        self.assertEqual(self.sessions()[0][0], ref)
        self.assertEqual(self.sessions()[0][5], "return")
        self.assertEqual(self.sequence(), 2)
        self.assertTrue(self.query("SELECT received_at IS NOT NULL FROM vehicle_events")[0][0])

    def test_redundant_alias_return(self):
        first, alias = self.event(), self.event(2, 1)
        self.admit(first)
        self.admit(alias)
        self.assertEqual(len(self.sessions()), 1)
        self.assertEqual(self.query("SELECT projection_take_event_id FROM vehicle_events WHERE event_id=%s", (alias.event_id,)), [(first.event_id,)])
        self.admit(self.event(3, 2, cause=alias.event_id))
        self.assertEqual(self.sessions()[0][5], "return")

    def test_handover(self):
        self.admit(self.event())
        self.admit(self.event(user=2, minute=1), 2)
        self.assertEqual([row[5] for row in self.sessions()], ["handover", None])

    def test_switch(self):
        self.admit(self.event())
        self.admit(self.event(2, 1, vehicle=1))
        self.assertEqual([row[5] for row in self.sessions()], ["vehicle_switch", None])

    def test_switch_and_handover(self):
        self.admit(self.event())
        self.admit(self.event(user=2, vehicle=1, minute=1), 2)
        self.admit(self.event(2, 2, vehicle=1))
        self.assertEqual([row[5] for row in self.sessions()], ["vehicle_switch", "handover", None])

    def test_retry_bypasses_reconciliation_and_preserves_every_row(self):
        event = self.event()
        self.admit(event)
        before = self.snapshot()
        with patch.object(va, "reconcile", side_effect=AssertionError("Retry must not replay")):
            self.assertEqual(self.admit(event), va.AdmissionResult("retry", "accepted"))
        self.assertEqual(self.snapshot(), before)

    def test_conflicting_uuid_and_sequence(self):
        event = self.event()
        self.admit(event)
        before = self.snapshot()
        for conflict in (replace(event, occurred_at=BASE + timedelta(minutes=1)),
                         replace(event, device_sequence=2), self.event(),
                         replace(event, vehicle_ref=self.vehicles[1])):
            self.assertEqual(self.admit(conflict).kind, "conflict")
            self.assertEqual(self.snapshot(), before)

    def test_gap_then_expected(self):
        before = self.snapshot()
        self.assertEqual(self.admit(self.event(2)).kind, "gap")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.admit(self.event()).kind, "accepted")

    def test_backward_chronology_and_terminal_retry(self):
        self.admit(self.event(minute=10))
        event = self.event(2, 9)
        self.terminal(event, "invalid_chronology")
        before = self.snapshot()
        self.assertEqual(self.admit(event), va.AdmissionResult("retry", "invalid_chronology"))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.admit(self.event(3, 10)).kind, "accepted")

    def test_boundary_inclusive_consumes(self):
        self.query("UPDATE families SET vehicle_reconciliation_generation=1,vehicle_finalized_through=%s WHERE id=10", (BASE,))
        self.terminal(self.event(minute=-1), "before_finalized_boundary")
        self.terminal(self.event(2), "before_finalized_boundary")
        self.assertEqual(self.admit(self.event(3, 1)).kind, "accepted")

    def test_causal_missing_other_user_vehicle_return_and_future(self):
        take = self.event()
        self.admit(take)
        ret = self.event(2, 1, cause=take.event_id)
        self.admit(ret)
        self.terminal(self.event(3, 2, cause=uuid4()), "causal_conflict")
        self.terminal(self.event(4, 3, vehicle=1, cause=take.event_id), "causal_conflict")
        self.terminal(self.event(5, 4, cause=ret.event_id), "causal_conflict")
        self.terminal(self.event(user=2, minute=1, cause=take.event_id), "causal_conflict", 2)
        other_device = self.query("INSERT INTO registered_devices(user_id,platform) VALUES(1,'android') RETURNING device_ref")[0][0]
        event = self.event(minute=-1, device=other_device, cause=take.event_id)
        self.assertEqual(self.admit(event), va.AdmissionResult("terminal", "causal_conflict"))

    def test_retired_take_terminal_no_projection_change(self):
        self.query("UPDATE vehicles SET retired_at=created_at+interval '1 second' WHERE vehicle_ref=%s", (self.vehicles[0],))
        self.terminal(self.event(), "vehicle_retired")

    def test_late_take_preserves_later_session_ref(self):
        later = self.event(user=2, minute=30)
        self.admit(later, 2)
        ref = self.sessions()[0][0]
        self.admit(self.event())
        self.assertEqual([row[1] for row in self.sessions()], [1, 2])
        self.assertEqual(self.sessions()[0][5], "handover")
        self.assertEqual(self.sessions()[1][0], ref)

    def test_late_return_and_old_alias_do_not_close_reacquisition(self):
        take, alias = self.event(), self.event(2, 1)
        self.admit(take)
        self.admit(alias)
        self.admit(self.event(3, 2, cause=take.event_id))
        self.admit(self.event(4, 3))
        ref = self.sessions()[1][0]
        self.admit(self.event(5, 4, cause=alias.event_id))
        self.assertEqual(self.sessions()[1][0], ref)
        self.assertIsNone(self.sessions()[1][4])
        device = self.query("INSERT INTO registered_devices(user_id,platform) VALUES(1,'ios') RETURNING device_ref")[0][0]
        self.admit(self.event(minute=1.5, cause=take.event_id, device=device))
        self.assertEqual(self.sessions()[0][4], BASE + timedelta(minutes=1.5))
        self.assertIsNone(self.sessions()[1][4])

    def test_earlier_take_keeps_ref_when_old_start_becomes_alias(self):
        later = self.event(minute=10)
        self.admit(later)
        ref = self.sessions()[0][0]
        device = self.query("INSERT INTO registered_devices(user_id,platform) VALUES(1,'ios') RETURNING device_ref")[0][0]
        earlier = self.event(device=device)
        self.admit(earlier)
        self.assertEqual(len(self.sessions()), 1)
        self.assertEqual(self.sessions()[0][0], ref)
        self.assertEqual(self.sessions()[0][6], earlier.event_id)

    def test_partial_materialization_failure_restores_sessions_and_aliases(self):
        self.admit(self.event())
        before = self.snapshot()
        original = va._materialize

        def fail_after_writes(*args):
            original(*args)
            raise RuntimeError("after projection writes")

        with patch.object(va, "_materialize", side_effect=fail_after_writes):
            with self.assertRaises(RuntimeError):
                self.admit(self.event(2, 1, vehicle=1))
        self.assertEqual(self.snapshot(), before)

    def test_checkpoint_includes_ended_seed_and_preserves_frozen_history(self):
        first = self.event(minute=-4)
        self.admit(first)
        self.admit(self.event(2, -3, cause=first.event_id))
        current = self.event(3, -2)
        self.admit(current)
        frozen = self.query("SELECT * FROM vehicle_driver_sessions WHERE ended_at IS NOT NULL")
        seed_ref = self.sessions()[1][0]
        self.query("UPDATE families SET vehicle_reconciliation_generation=1,vehicle_finalized_through=%s WHERE id=10", (BASE,))
        self.query("UPDATE vehicle_driver_sessions SET checkpoint_generation=1 WHERE ended_at IS NULL")
        self.admit(self.event(user=2, minute=2), 2)
        self.admit(self.event(4, 1, cause=current.event_id))
        self.assertEqual(self.sessions()[1][0], seed_ref)
        self.assertEqual(self.sessions()[1][5], "return")
        self.assertEqual(self.sessions()[1][8], 1)
        self.assertEqual(self.query("SELECT * FROM vehicle_driver_sessions WHERE session_ref=%s", (frozen[0][1],)), frozen)

    def test_checkpoint_alias_return(self):
        first, alias = self.event(minute=-2), self.event(2, -1)
        self.admit(first)
        self.admit(alias)
        self.query("UPDATE families SET vehicle_reconciliation_generation=1,vehicle_finalized_through=%s WHERE id=10", (BASE,))
        self.query("UPDATE vehicle_driver_sessions SET checkpoint_generation=1")
        self.admit(self.event(3, 1, cause=alias.event_id))
        self.assertEqual(self.sessions()[0][5], "return")

    def test_frozen_ended_return_is_noop_and_survives_later_replay(self):
        first = self.event(minute=-4)
        self.admit(first)
        self.admit(self.event(2, -3, cause=first.event_id))
        frozen = self.query("SELECT * FROM vehicle_driver_sessions")
        self.query("UPDATE families SET vehicle_reconciliation_generation=1,vehicle_finalized_through=%s WHERE id=10", (BASE,))
        ret = self.event(3, 1, cause=first.event_id)
        self.assertEqual(self.admit(ret).kind, "accepted")
        self.assertEqual(self.query("SELECT * FROM vehicle_driver_sessions"), frozen)
        self.assertEqual(self.admit(self.event(4, 2)).kind, "accepted")
        self.assertEqual(self.query("SELECT * FROM vehicle_driver_sessions WHERE session_ref=%s", (frozen[0][1],)), frozen)
        self.assertEqual(self.query("SELECT projection_take_event_id FROM vehicle_events WHERE event_id=%s", (ret.event_id,)), [(first.event_id,)])

    def test_preexisting_noop_return_after_new_checkpoint(self):
        first = self.event(minute=-4)
        self.admit(first)
        self.admit(self.event(2, -3, cause=first.event_id))
        self.admit(self.event(3, 1, cause=first.event_id))
        self.query("UPDATE families SET vehicle_reconciliation_generation=1,vehicle_finalized_through=%s WHERE id=10", (BASE,))
        self.assertEqual(self.admit(self.event(4, 2)).kind, "accepted")

    def test_unavailable_cross_family_device_and_revocation(self):
        for event in (self.event(vehicle=2), replace(self.event(), vehicle_ref=uuid4()),
                      self.event(device=self.devices[2]), self.event(device=self.devices[3])):
            before = self.snapshot()
            self.assertEqual(self.admit(event).kind, "unavailable")
            self.assertEqual(self.snapshot(), before)
        self.query("UPDATE registered_devices SET revoked_at=created_at+interval '1 second' WHERE user_id=1")
        self.assertEqual(self.admit(self.event()).kind, "unavailable")
        self.assertEqual(self.sequence(), 0)

    def test_deletion_gate_and_stale_mapping(self):
        self.query("INSERT INTO account_deletion_jobs VALUES(%s)", (self.users[1].auth_user_id,))
        self.assertEqual(self.admit(self.event()).kind, "unavailable")
        self.assertEqual(self.sequence(), 0)
        self.query("DELETE FROM account_deletion_jobs")
        self.users[1] = replace(self.users[1], family_id=20)
        self.assertEqual(self.admit(self.event()).kind, "unavailable")

    def test_materialization_and_reconciliation_failure_rollback(self):
        for name in ("_materialize", "reconcile"):
            before = self.snapshot()
            with patch.object(va, name, side_effect=RuntimeError("forced")):
                with self.assertRaises(RuntimeError):
                    self.admit(self.event())
            self.assertEqual(self.snapshot(), before)

    def test_terminal_sequence_failure_rolls_back_evidence(self):
        self.query("ALTER TABLE registered_devices ADD CONSTRAINT injected_failure CHECK(last_processed_sequence=0)")
        before = self.snapshot()
        with self.assertRaises(self.pg.errors.CheckViolation):
            self.admit(self.event(cause=uuid4()))
        self.assertEqual(self.snapshot(), before)

    def race(self, calls):
        barrier = threading.Barrier(len(calls))

        def run(call):
            barrier.wait(timeout=5)
            return self.admit(*call)

        with ThreadPoolExecutor(max_workers=len(calls)) as executor:
            return list(executor.map(run, calls))

    def test_concurrent_same_event_retry(self):
        event = self.event()
        results = self.race([(event, 1), (event, 1)])
        self.assertEqual(sorted(result.kind for result in results), ["accepted", "retry"])
        self.assertEqual(self.sequence(), 1)
        self.assertEqual(len(self.sessions()), 1)

    def test_future_clock_guard_is_non_consuming_and_correctable(self):
        now = self.query('SELECT clock_timestamp()')[0][0]
        event = replace(self.event(), occurred_at=now + timedelta(minutes=6))
        before = self.snapshot()
        self.assertEqual(self.admit(event).kind, 'future_clock_skew')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.sequence(), 0)
        corrected = replace(event, occurred_at=now)
        self.assertEqual(self.admit(corrected).kind, 'accepted')
        self.assertEqual(self.admit(corrected).kind, 'retry')

    def test_five_minute_future_boundary_allowed(self):
        now = self.query('SELECT clock_timestamp()')[0][0]
        self.assertEqual(self.admit(replace(self.event(), occurred_at=now + timedelta(minutes=5))).kind, 'accepted')

    def test_exact_database_clock_boundary_and_python_clock_independence(self):
        # Freeze only the database clock expression to a PostgreSQL-produced
        # value. Compare at microsecond precision, without timing tolerances.
        now = self.query('SELECT clock_timestamp()')[0][0]
        with self.connection() as conn:
            class Clock:
                transaction = conn.transaction

                def execute(inner, sql, params=None):
                    if sql.startswith('SELECT %s::timestamptz > clock_timestamp()'):
                        return conn.execute(sql.replace('clock_timestamp()', '%s::timestamptz'), (*params, now))
                    return conn.execute(sql, params)

            event = replace(self.event(), occurred_at=now + timedelta(minutes=5, microseconds=1))
            self.assertEqual(va.admit_native_event(Clock(), self.users[1], event).kind, 'future_clock_skew')
            allowed = replace(event, occurred_at=now + timedelta(minutes=5))
            self.assertEqual(va.admit_native_event(Clock(), self.users[1], allowed).kind, 'accepted')
        # Production admission has no application datetime.now()/utcnow().
        import inspect
        self.assertNotIn('datetime.now', inspect.getsource(va.admit_native_event))
        self.assertNotIn('utcnow', inspect.getsource(va.admit_native_event))

    def test_pre_guard_future_receipt_retry_precedes_clock_guard(self):
        now = self.query('SELECT clock_timestamp()')[0][0]
        event = replace(self.event(), occurred_at=now + timedelta(days=365))
        self.query("INSERT INTO vehicle_events(event_id,family_id,vehicle_id,user_id,device_id,source,event_type,occurred_at,device_sequence,admission_outcome) "
                   "SELECT %s,10,v.id,1,d.id,'native','take',%s,1,'accepted' FROM vehicles v,registered_devices d WHERE v.vehicle_ref=%s AND d.device_ref=%s",
                   (event.event_id, event.occurred_at, event.vehicle_ref, event.device_ref))
        self.query('UPDATE registered_devices SET last_processed_sequence=1 WHERE device_ref=%s', (event.device_ref,))
        self.assertEqual(self.admit(event).kind, 'retry')
        self.assertEqual(self.admit(replace(event, occurred_at=now)).kind, 'conflict')
        self.assertEqual(self.admit(replace(event, event_id=uuid4(), device_sequence=3)).kind, 'gap')

    def test_concurrent_conflicting_sequence(self):
        results = self.race([(self.event(), 1), (self.event(vehicle=1), 1)])
        self.assertEqual(sorted(result.kind for result in results), ["accepted", "conflict"])
        self.assertEqual(self.query("SELECT count(*) FROM vehicle_events"), [(1,)])

    def test_concurrent_family_handover(self):
        results = self.race([(self.event(), 1), (self.event(user=2, minute=1), 2)])
        self.assertTrue(all(result.kind == "accepted" for result in results))
        self.assertEqual([row[5] for row in self.sessions()], ["handover", None])

    def test_global_uuid_race_across_families(self):
        first = self.event()
        second = replace(self.event(user=3, vehicle=2), event_id=first.event_id)
        # Force both preflight lookups to finish before INSERT, testing the DB
        # unique conflict path rather than only a sequential lookup conflict.
        barrier = threading.Barrier(2)
        original = va.reconcile

        def paused(*args):
            result = original(*args)
            barrier.wait(timeout=5)
            return result

        with patch.object(va, "reconcile", side_effect=paused):
            results = self.race([(first, 1), (second, 3)])
        self.assertEqual(sorted(result.kind for result in results), ["accepted", "conflict"])
        self.assertEqual(self.sequence(1) + self.sequence(3), 1)


if __name__ == "__main__":
    unittest.main()
