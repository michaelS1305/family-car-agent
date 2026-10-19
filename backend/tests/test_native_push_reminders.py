"""Real local PostgreSQL tests; inherits the loopback-only disposable DB guard."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from psycopg import sql

import native_push_reminders as reminders
import native_push_worker as worker
import native_push_refresh as refresh
from native_push_fcm import Result
from tests import test_native_push as fixtures
CONFIG = fixtures.CONFIG


class DisabledTests(unittest.TestCase):
    def test_disabled_never_opens_database(self):
        with patch.dict(os.environ, {'NATIVE_PUSH_REMINDERS_ENABLED': 'false'}):
            reminders.schedule(None, 'unused')
            self.assertEqual(reminders.eligibility(), 'd.recipient_user_id<>e.actor_user_id')
        with patch.dict(os.environ, {'NATIVE_PUSH_ENABLED': 'false', 'NATIVE_PUSH_REMINDERS_ENABLED': 'true'}):
            reminders.schedule(None, 'unused')


@unittest.skipUnless(os.getenv('GEMINI_TEST_DATABASE_URL'), 'Disposable local PostgreSQL required')
class ReminderTests(unittest.TestCase):
    connection = fixtures.PostgresTests.connection
    cleanup = fixtures.PostgresTests.cleanup
    query = fixtures.PostgresTests.query
    begin = fixtures.PostgresTests.begin
    nonce = fixtures.PostgresTests.nonce
    confirm = fixtures.PostgresTests.confirm
    activate = fixtures.PostgresTests.activate

    def setUp(self):
        fixtures.PostgresTests.setUp(self)
        self.query("ALTER TABLE users ADD COLUMN name text NOT NULL DEFAULT 'User'")
        self.query("ALTER TABLE vehicles ADD COLUMN display_name text NOT NULL DEFAULT 'Car', ADD COLUMN retired_at timestamptz")
        self.query('CREATE TABLE families(id integer PRIMARY KEY,created_by_user_id integer NOT NULL REFERENCES users(id))')
        self.query('INSERT INTO families VALUES(10,1),(20,3)')
        self.query("CREATE TABLE reservations(id serial PRIMARY KEY,reservation_ref uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),"
                   "user_id integer NOT NULL REFERENCES users(id),vehicle_id integer REFERENCES vehicles(id),"
                   "start_time text NOT NULL,end_time text NOT NULL,status text NOT NULL DEFAULT 'active')")
        source = Path(__file__).resolve().parents[2] / 'supabase/manual_migrations'
        original = (source / '2026101401_vehicle_maintenance.sql').read_text()
        ddl = 'CREATE TABLE public.vehicle_maintenance (' + original.split('CREATE TABLE public.vehicle_maintenance (')[1].split(';')[0] + ';'
        self.query(ddl.replace('public.', self.schema + '.'))
        # Match Supabase role names in this disposable database only.
        self.query("DO $$ BEGIN IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon; END IF;"
                   "IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated; END IF;"
                   "IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='service_role') THEN CREATE ROLE service_role; END IF; END $$")
        migration = (source / '2026101901_native_push_reminders.sql').read_text()
        # Match the established full-suite local role, without altering migration files.
        executor = self.query('SELECT current_user')[0][0]
        self.assertIn(executor, ('postgres', 'gemini_test'))
        self.query(migration.replace('public.', self.schema + '.').replace(
            "current_user<>'postgres'", "current_user<>'" + executor + "'"))
        flag = patch.dict(os.environ, {'NATIVE_PUSH_REMINDERS_ENABLED': 'true'})
        flag.start(); self.addCleanup(flag.stop)
        self.installation = self.activate(1)

    def reservation(self, minutes=30, user=1):
        return self.query("INSERT INTO reservations(user_id,vehicle_id,start_time,end_time) VALUES(%s,1,"
            "((clock_timestamp()+%s*interval '1 minute') AT TIME ZONE 'Asia/Jerusalem')::text,"
            "((clock_timestamp()+interval '2 hours') AT TIME ZONE 'Asia/Jerusalem')::text) RETURNING reservation_ref", (user,minutes))[0][0]

    def schedule(self):
        reminders.schedule(self, CONFIG.project)

    def inbox(self, user=1, installation=None, generation=2):
        with self.connection() as conn:
            return refresh.events(conn,self.users[user],CONFIG,installation or self.installation,generation)['items']

    def test_late_created_and_normal_due_only_once_concurrently(self):
        self.reservation(59); self.reservation(1); self.reservation(61); self.reservation(-1)
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda _: self.schedule(), range(8)))
        self.schedule()
        self.assertEqual(self.query('SELECT count(*) FROM native_push_events'), [(2,)])
        self.assertEqual(self.query('SELECT count(*) FROM native_push_deliveries'), [(2,)])
        items = self.inbox()
        self.assertEqual(len(items),2)
        self.assertEqual({x['type'] for x in items},{'reservation_reminder'})
        self.assertTrue(all('scheduled_for' in x for x in items))

    def test_cancel_reschedule_owner_retire_and_family_rechecked(self):
        for change in ["UPDATE reservations SET status='cancelled'",
                       "UPDATE reservations SET start_time=(start_time::timestamp+interval '1 hour')::text",
                       "UPDATE reservations SET user_id=2", "UPDATE vehicles SET retired_at=clock_timestamp()",
                       "UPDATE users SET family_id=20 WHERE id=1"]:
            with self.subTest(change=change):
                ref = self.reservation()
                self.schedule()
                claim = worker.claim_delivery(self,CONFIG.project)
                self.assertIsNotNone(worker.delivery_payload(self,CONFIG,claim))
                self.query(change)
                self.assertIsNone(worker.delivery_payload(self,CONFIG,claim))
                worker.finish_delivery(self,claim,Result('accepted'))
                self.assertEqual(self.query('SELECT status FROM native_push_deliveries'),[('cancelled',)])
                if 'family_id=20' not in change:
                    self.assertEqual(self.inbox(),[])
                self.query('DELETE FROM native_push_events')
                self.query('DELETE FROM reservations WHERE reservation_ref=%s',(ref,))
                self.query('UPDATE users SET family_id=10 WHERE id=1')
                self.query('UPDATE vehicles SET retired_at=NULL')

    def test_explicit_reschedule_new_occurrence_not_duplicate(self):
        self.reservation(25); self.schedule()
        self.query("UPDATE reservations SET start_time=(start_time::timestamp+interval '5 minutes')::text")
        self.schedule(); self.schedule()
        self.assertEqual(self.query('SELECT count(*) FROM native_push_events'),[(2,)])
        self.assertEqual(len(self.inbox()),1)

    def test_maintenance_calendar_due_dst_and_completion(self):
        # SQL semantics are previous calendar date at 09:00, NOT a fixed 24h subtraction.
        for date, hours in [('2026-03-27',15),('2026-10-25',15),('2026-06-01',15)]:
            diff=self.query("SELECT EXTRACT(epoch FROM ((%s::date::timestamp AT TIME ZONE 'Asia/Jerusalem')-"
                "((%s::date-1+time '09:00') AT TIME ZONE 'Asia/Jerusalem')))/3600",(date,date))[0][0]
            self.assertEqual(diff,hours)
        # Force source eligibility independently of the time of day running this test.
        ref=self.query("INSERT INTO vehicle_maintenance(vehicle_id,description,scheduled_date) "
            "VALUES(1,'Oil',(clock_timestamp() AT TIME ZONE 'Asia/Jerusalem')::date+1) RETURNING maintenance_ref")[0][0]
        self.schedule()
        local_hour=self.query("SELECT EXTRACT(hour FROM clock_timestamp() AT TIME ZONE 'Asia/Jerusalem')")[0][0]
        self.assertEqual(len(self.inbox()),1 if local_hour>=9 else 0)
        self.query('UPDATE vehicle_maintenance SET completed=true')
        self.assertEqual(self.inbox(),[])
        self.schedule()

    def test_maintenance_authorization_and_deletion(self):
        ref=self.query("INSERT INTO vehicle_maintenance(vehicle_id,description,scheduled_date) VALUES(1,'Oil',"
            "(clock_timestamp() AT TIME ZONE 'Asia/Jerusalem')::date+1) RETURNING maintenance_ref")[0][0]
        # Seed a valid pending event to exercise guards at all test execution times.
        self.query("INSERT INTO native_push_events(event_ref,family_id,actor_user_id,vehicle_id,event_type,occurred_at,expires_at,status,maintenance_ref,scheduled_for) "
            "SELECT gen_random_uuid(),10,1,1,'maintenance_reminder',clock_timestamp(),clock_timestamp()+interval '4 minutes','pending',maintenance_ref,"
            "scheduled_date::timestamp AT TIME ZONE 'Asia/Jerusalem' FROM vehicle_maintenance")
        self.query("INSERT INTO native_push_deliveries(delivery_ref,event_ref,installation_ref,recipient_user_id,installation_generation,status,next_attempt_at,created_at,updated_at) "
            "SELECT gen_random_uuid(),event_ref,%s,1,2,'pending',statement_timestamp(),statement_timestamp(),statement_timestamp() FROM native_push_events",(self.installation,))
        self.assertEqual(len(self.inbox()),1)
        self.query('UPDATE families SET created_by_user_id=2 WHERE id=10')
        self.assertEqual(self.inbox(),[])
        claim=worker.claim_delivery(self,CONFIG.project)
        self.assertIsNone(worker.delivery_payload(self,CONFIG,claim))
        self.query('DELETE FROM vehicle_maintenance WHERE maintenance_ref=%s',(ref,))
        self.assertEqual(self.query('SELECT count(*) FROM native_push_events'),[(0,)])
        self.assertEqual(self.query('SELECT count(*) FROM native_push_deliveries'),[(0,)])

    def test_generation_and_opaque_payload(self):
        self.reservation(); self.schedule()
        claim=worker.claim_delivery(self,CONFIG.project)
        self.assertEqual(worker.delivery_payload(self,CONFIG,claim)[1],{'kind':'refresh','version':'1'})
        self.query('UPDATE native_push_installations SET generation=generation+1')
        self.assertIsNone(worker.delivery_payload(self,CONFIG,claim))
        with self.assertRaises(refresh.RefreshError): self.inbox()
        self.assertEqual(self.inbox(generation=3),[])

    def test_source_delete_cascades_and_rollback(self):
        self.reservation(); self.schedule()
        try:
            with self.connection() as conn:
                conn.execute('DELETE FROM reservations')
                raise RuntimeError('rollback')
        except RuntimeError: pass
        self.assertEqual(len(self.inbox()),1)
        self.query('DELETE FROM reservations')
        self.assertEqual(self.query('SELECT count(*) FROM native_push_deliveries'),[(0,)])

    def test_source_and_recipient_deletion_jobs_account_switch_and_expiry(self):
        self.reservation(); self.schedule()
        other = self.activate(2)
        self.assertEqual(self.inbox(user=2,installation=other),[])
        with self.assertRaises(refresh.RefreshError): self.inbox(user=2)
        self.query('INSERT INTO account_deletion_jobs VALUES(%s)',(self.users[1].auth_user_id,))
        claim=worker.claim_delivery(self,CONFIG.project)
        self.assertIsNone(worker.delivery_payload(self,CONFIG,claim))
        self.query('DELETE FROM account_deletion_jobs')
        self.query("UPDATE native_push_events SET occurred_at=statement_timestamp()-interval '6 minutes',"
                   "expires_at=statement_timestamp()-interval '1 minute'")
        self.assertIsNone(worker.delivery_payload(self,CONFIG,claim))
        self.assertEqual(self.inbox(),[])

    def test_scheduler_transaction_failure_leaves_no_partial_outbox(self):
        self.reservation()
        self.query("ALTER TABLE native_push_deliveries ADD CONSTRAINT fixture_reject CHECK(false)")
        with self.assertRaises(psycopg.errors.CheckViolation) as error: self.schedule()
        self.assertEqual(error.exception.diag.constraint_name,'fixture_reject')
        self.assertEqual(self.query('SELECT count(*) FROM native_push_events'),[(0,)])
        self.assertEqual(self.query('SELECT count(*) FROM reservations'),[(1,)])
        self.query('ALTER TABLE native_push_deliveries DROP CONSTRAINT fixture_reject')
        self.schedule()
        self.assertEqual(len(self.inbox()),1)

    def test_new_columns_do_not_grant_client_access(self):
        for role in ('anon','authenticated','service_role'):
            for privilege in ('SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER','MAINTAIN'):
                self.assertFalse(self.query('SELECT has_table_privilege(%s,%s,%s)',
                    (role,self.schema+'.native_push_events',privilege))[0][0])
            for privilege in ('SELECT','INSERT','UPDATE','REFERENCES'):
                self.assertFalse(self.query('SELECT has_any_column_privilege(%s,%s,%s)',
                    (role,self.schema+'.native_push_events',privilege))[0][0])

    def test_existing_vehicle_delivery_with_reminders_enabled(self):
        self.activate(2)
        fixtures.PostgresTests.produce(self)
        claim=worker.claim_delivery(self,CONFIG.project)
        self.assertEqual(worker.delivery_payload(self,CONFIG,claim)[1],{'kind':'refresh','version':'1'})
        worker.finish_delivery(self,claim,Result('accepted'))
        self.assertEqual(self.query('SELECT status FROM native_push_deliveries'),[('accepted',)])

    event = fixtures.PostgresTests.event


@unittest.skipUnless(os.getenv('GEMINI_TEST_DATABASE_URL'), 'Disposable local PostgreSQL required')
class ExactMigrationTests(unittest.TestCase):
    def test_unmodified_migration_acl_rls_and_reexecution_rollback(self):
        dsn=os.environ['GEMINI_TEST_DATABASE_URL']
        parsed=urlsplit(dsn)
        if parsed.hostname not in ('127.0.0.1','localhost','::1') or parsed.path!='/test_gemini':
            raise RuntimeError('Only disposable loopback test_gemini allowed')
        name='test_fca_reminder_'+uuid4().hex
        with psycopg.connect(dsn,autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            try:
                with psycopg.connect(dsn,dbname=name,autocommit=True) as conn:
                    conn.execute('SET ROLE postgres')
                    conn.execute('CREATE TABLE users(id integer PRIMARY KEY)')
                    conn.execute('CREATE TABLE vehicles(id integer PRIMARY KEY)')
                    conn.execute('CREATE TABLE reservations(reservation_ref uuid NOT NULL UNIQUE)')
                    conn.execute('CREATE TABLE vehicle_events(event_id uuid PRIMARY KEY,user_id integer NOT NULL,'
                        'vehicle_id integer NOT NULL,family_id integer NOT NULL,occurred_at timestamptz NOT NULL,'
                        'UNIQUE(event_id,user_id,vehicle_id,family_id))')
                    for role in ('anon','authenticated','service_role'):
                        if not conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(role,)).fetchone():
                            conn.execute(sql.SQL('CREATE ROLE {}').format(sql.Identifier(role)))
                    # Reproduce unwanted defaults, verify migration does not change them.
                    conn.execute('ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public '
                                 'GRANT TRUNCATE,REFERENCES,TRIGGER,MAINTAIN ON TABLES TO anon,authenticated,service_role')
                    root=Path(__file__).resolve().parents[2]/'supabase/manual_migrations'
                    conn.execute((root/'2026101401_vehicle_maintenance.sql').read_text())
                    conn.execute((root/'2026101801_native_push_foundation.sql').read_text())
                    defaults=conn.execute('SELECT defaclacl::text FROM pg_default_acl ORDER BY oid').fetchall()
                    migration=(root/'2026101901_native_push_reminders.sql').read_text()
                    conn.execute(migration)
                    self.assertEqual(conn.execute('SELECT defaclacl::text FROM pg_default_acl ORDER BY oid').fetchall(),defaults)
                    self.assertEqual(conn.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='native_push_events'::regclass").fetchone(),(True,False))
                    self.assertEqual(conn.execute("SELECT count(*) FROM pg_policies WHERE tablename='native_push_events'").fetchone(),(0,))
                    for role in ('anon','authenticated','service_role'):
                        for privilege in ('SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER','MAINTAIN'):
                            self.assertFalse(conn.execute("SELECT has_table_privilege(%s,'native_push_events',%s)",(role,privilege)).fetchone()[0])
                        conn.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(role)))
                        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                            conn.execute('SELECT reservation_ref FROM native_push_events')
                        conn.execute('SET ROLE postgres')
                    conn.execute((root/'2026101901_native_push_reminders_verify.sql').read_text())
                    with self.assertRaises(psycopg.errors.DuplicateColumn): conn.execute(migration)
                    conn.execute('ROLLBACK')
                    self.assertEqual(conn.execute("SELECT count(*) FROM pg_constraint WHERE conrelid='native_push_events'::regclass AND NOT convalidated").fetchone(),(0,))
            finally:
                admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
