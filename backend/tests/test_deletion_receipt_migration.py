"""Execute the UNMODIFIED deployment SQL in a fresh localhost PostgreSQL database."""
import os
import unittest
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4
from datetime import timedelta
import psycopg
from psycopg import sql
import deletion_receipts as receipts
import apple_revocation
from tests.test_deletion_receipts import secret

@unittest.skipUnless(os.environ.get('GEMINI_TEST_DATABASE_URL'), 'Disposable local PostgreSQL required')
class ActualReceiptMigrationTests(unittest.TestCase):
    def setUp(self):
        dsn=os.environ['GEMINI_TEST_DATABASE_URL']
        url=urlsplit(dsn)
        if url.hostname not in {'localhost','127.0.0.1','::1'} or url.path!='/test_gemini':
            raise RuntimeError('Only disposable localhost test_gemini allowed')
        self.admin=dsn
        self.name='receipt_migration_'+uuid4().hex
        with psycopg.connect(dsn,autocommit=True) as conn:
            self.assertEqual(int(conn.execute('SHOW server_version_num').fetchone()[0])//10000,17)
            conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(self.name)))
        self.addCleanup(self.drop)
        self.dsn=psycopg.conninfo.make_conninfo(dsn,dbname=self.name)
        self.pool=SimpleNamespace(connection=self.connection)
        self.query("""CREATE SCHEMA auth;
          CREATE TABLE auth.users(id uuid PRIMARY KEY);
          CREATE TABLE public.users(id integer PRIMARY KEY,auth_user_id uuid,family_id integer);
          CREATE TABLE public.families(id integer PRIMARY KEY,created_by_user_id integer NOT NULL);
          CREATE TABLE apple_credentials(auth_user_id uuid,environment text,client_id text,apple_subject text,generation bigint,key_id text,refresh_ciphertext bytea);
          CREATE TABLE apple_credential_attempts(auth_user_id uuid,generation bigint,status text);""")
        root=Path(__file__).resolve().parents[2]/'supabase/manual_migrations'
        self.execute_file(root/'2026091603_account_deletion_jobs.sql')
        self.execute_file(root/'2026111501_apple_revocation.sql')
        self.legacy=uuid4()
        self.query('INSERT INTO account_deletion_jobs(auth_user_id) VALUES(%s)',(self.legacy,))
        self.execute_file(root/'2026112701_account_deletion_receipts.sql')
        self.owner=uuid4(); self.op=str(uuid4()); self.secret=secret()
        self.query('INSERT INTO auth.users VALUES(%s)',(self.owner,))
        flag=patch.dict(os.environ,{'DELETION_RECEIPTS_ENABLED':'true'}); flag.start(); self.addCleanup(flag.stop)

    def drop(self):
        with psycopg.connect(self.admin,autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(self.name)))
    def execute_file(self,path):
        with psycopg.connect(self.dsn,autocommit=True) as conn:
            conn.execute(path.read_text(encoding='utf-8')) # Exact bytes/content; no schema replacement.
    @contextmanager
    def connection(self):
        with psycopg.connect(self.dsn) as conn: yield conn
    def query(self,statement,values=()):
        with self.connection() as conn:
            result=conn.execute(statement,values)
            return result.fetchall() if result.description else []
    def start(self): return receipts.initiate(self.pool,self.owner,self.op,self.secret)
    def complete(self):
        job=self.query('SELECT job_ref FROM account_deletion_jobs WHERE auth_user_id=%s',(self.owner,))[0][0]
        self.query("UPDATE account_deletion_jobs SET phase='auth_pending',apple_state='not_applicable' WHERE job_ref=%s",(job,))
        self.query('DELETE FROM auth.users WHERE id=%s',(self.owner,))
        return apple_revocation.finalize(self.pool,apple_revocation.Attempt(self.owner,job,0))

    def test_actual_migration_legacy_jobs_roles_and_constraints(self):
        self.assertEqual(self.query('SELECT count(*) FROM account_deletion_jobs WHERE auth_user_id=%s',(self.legacy,)),[(1,)])
        self.query('DELETE FROM account_deletion_jobs WHERE auth_user_id=%s',(self.legacy,))
        self.start()
        self.assertEqual(self.query("SELECT relrowsecurity FROM pg_class WHERE oid='public.account_deletion_receipts'::regclass"),[(True,)])
        for role in ['anon','authenticated']:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with self.connection() as conn:
                    conn.execute('SET LOCAL ROLE '+role); conn.execute('SELECT * FROM account_deletion_receipts')
        with self.connection() as conn:
            conn.execute('SET LOCAL ROLE service_role')
            self.assertEqual(conn.execute('SELECT count(*) FROM account_deletion_receipts').fetchone(),(1,))
            for privilege in ['SELECT','INSERT','UPDATE','DELETE']:
                self.assertTrue(conn.execute("SELECT has_table_privilege(current_user,'account_deletion_receipts',%s)",(privilege,)).fetchone()[0])
        for update in ["state='completed'","job_ref=NULL","credential_digest=decode('00','hex')","expires_at=clock_timestamp()"]:
            with self.assertRaises(psycopg.errors.CheckViolation): self.query('UPDATE account_deletion_receipts SET '+update)
        self.assertTrue(self.query("SELECT indexdef FROM pg_indexes WHERE indexname='account_deletion_receipts_expiry_idx'")[0][0].endswith("WHERE (state = 'completed'::text)"))

    def test_atomic_finalization_and_deferred_failure(self):
        self.start()
        self.query("CREATE FUNCTION fail_commit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected'; END $$; CREATE CONSTRAINT TRIGGER fail_commit AFTER DELETE ON account_deletion_jobs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fail_commit()")
        with self.assertRaises(psycopg.Error): self.complete()
        self.assertEqual(receipts.lookup(self.pool,self.op,self.secret)['status'],'pending')
        self.assertEqual(self.query('SELECT count(*) FROM account_deletion_jobs WHERE auth_user_id=%s',(self.owner,)),[(1,)])
        self.query('DROP TRIGGER fail_commit ON account_deletion_jobs')
        self.assertTrue(self.complete())
        first=receipts.lookup(self.pool,self.op,self.secret)
        self.assertEqual(first,receipts.lookup(self.pool,self.op,self.secret))
        self.assertEqual(self.query('SELECT expires_at-completed_at FROM account_deletion_receipts'),[(timedelta(days=180),)])

    def test_disabled_flag_preserves_pending_status_and_finalization(self):
        self.start()
        with patch.dict(os.environ,{'DELETION_RECEIPTS_ENABLED':'false'}):
            with self.assertRaises(receipts.Unavailable): receipts.initiate(self.pool,self.owner,str(uuid4()),secret())
            self.assertEqual(receipts.lookup(self.pool,self.op,self.secret)['status'],'pending')
            self.assertTrue(self.complete())
            self.assertEqual(receipts.lookup(self.pool,self.op,self.secret)['status'],'completed')

    def test_legacy_worker_guard_and_creation_rollback(self):
        self.query("CREATE FUNCTION reject_receipt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected'; END $$; CREATE TRIGGER reject_receipt BEFORE INSERT ON account_deletion_receipts FOR EACH ROW EXECUTE FUNCTION reject_receipt()")
        with self.assertRaises(psycopg.Error): self.start()
        self.assertEqual(self.query('SELECT count(*) FROM account_deletion_jobs WHERE auth_user_id=%s',(self.owner,)),[(0,)])
        self.query('DROP TRIGGER reject_receipt ON account_deletion_receipts'); self.start()
        with self.assertRaises(psycopg.Error): self.query('DELETE FROM account_deletion_jobs WHERE auth_user_id=%s',(self.owner,))
        self.assertEqual(receipts.lookup(self.pool,self.op,self.secret)['status'],'pending')

    def test_concurrent_initiation_status_and_completion(self):
        with ThreadPoolExecutor(4) as workers:
            values=list(workers.map(lambda _:self.start(),range(8)))
        self.assertTrue(all(v==values[0] for v in values))
        with ThreadPoolExecutor(4) as workers:
            finished=workers.submit(self.complete)
            snapshots=list(workers.map(lambda _:receipts.lookup(self.pool,self.op,self.secret),range(20)))
            self.assertTrue(finished.result())
        self.assertTrue(all(v['status'] in {'pending','completed'} for v in snapshots))
        self.assertEqual(self.query('SELECT count(*) FROM account_deletion_receipts'),[(1,)])
        self.assertEqual(receipts.lookup(self.pool,self.op,self.secret)['status'],'completed')

    def test_exact_expiry_and_bounded_cleanup(self):
        self.start(); receipts.expire(self.pool)
        self.assertEqual(receipts.lookup(self.pool,self.op,self.secret)['status'],'pending')
        self.complete()
        self.query("UPDATE account_deletion_receipts SET created_at=statement_timestamp()-interval '181 days',completed_at=statement_timestamp()-interval '180 days',expires_at=statement_timestamp()")
        with self.assertRaises(receipts.Rejected): receipts.lookup(self.pool,self.op,self.secret)
        self.query("INSERT INTO account_deletion_receipts SELECT gen_random_uuid(),decode(repeat('00',32),'hex'),NULL,'completed',statement_timestamp()-interval '181 days',statement_timestamp()-interval '180 days',statement_timestamp() FROM generate_series(1,104)")
        receipts.expire(self.pool)
        self.assertEqual(self.query('SELECT count(*) FROM account_deletion_receipts'),[(5,)])
