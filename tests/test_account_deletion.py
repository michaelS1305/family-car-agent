"""Deletion tests use mocks or per-test schemas on LOCAL test_gemini only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
from uuid import uuid4

import account_deletion as deletion
import deletion_gate as gate
from tests.test_database_atomic_creation import load_database_module_without_real_connection


class DeletionUnitTests(unittest.TestCase):
    def test_admin_hard_delete_no_redirect_no_proxy_no_secret_logging(self):
        session = Mock()
        session.delete.return_value.status_code = 200
        context = Mock(__enter__=Mock(return_value=session), __exit__=Mock(return_value=False))
        with patch.dict(os.environ, {'SUPABASE_URL': 'https://example.supabase.co', 'SUPABASE_SERVICE_ROLE_KEY': 'private'}), \
             patch.object(deletion.requests, 'Session', return_value=context):
            deletion.delete_auth_identity(uuid4())
        self.assertFalse(session.trust_env)
        args = session.delete.call_args.kwargs
        self.assertFalse(args['allow_redirects'])
        self.assertEqual(args['json'], {'should_soft_delete': False})
        self.assertEqual(args['timeout'], (5, 10))

    def test_admin_configuration_and_transport_failures_are_private(self):
        with patch.dict(os.environ, {'SUPABASE_URL': 'http://unsafe.test', 'SUPABASE_SERVICE_ROLE_KEY': 'secret'}), \
             patch.object(deletion.requests, 'Session') as session, self.assertLogs(deletion.logger) as logs:
            deletion.delete_auth_identity(uuid4())
            session.assert_not_called()
        self.assertNotIn('secret', str(logs.output))
        self.assertNotIn('unsafe', str(logs.output))

    def test_gate_fails_for_missing_auth_and_pending_job(self):
        for state in ((False, False), (True, True)):
            conn = Mock()
            conn.execute.return_value.fetchone.return_value = state
            with self.assertRaises(gate.IdentityUnavailable):
                gate.require_auth(conn, uuid4())


@unittest.skipUnless(os.environ.get('GEMINI_TEST_DATABASE_URL'), 'Local PostgreSQL not configured')
class AccountDeletionPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        self.psycopg, self.sql = psycopg, sql
        self.dsn = os.environ['GEMINI_TEST_DATABASE_URL']
        url = urlsplit(self.dsn)
        if url.hostname not in {'127.0.0.1', 'localhost', '::1'} or url.path != '/test_gemini':
            raise RuntimeError('Only disposable local test_gemini permitted')
        self.schema = 'deletion_test_' + uuid4().hex
        with psycopg.connect(self.dsn, connect_timeout=3) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        self.pool = Mock(connection=self.connection)
        self.database = load_database_module_without_real_connection()
        self.database.pool = self.pool
        self.database.require_auth = gate.require_auth
        self.database.require_user = gate.require_user
        self.database.UniqueViolation = psycopg.errors.UniqueViolation
        patcher = patch.dict(sys.modules, {'database': self.database})
        patcher.start()
        self.addCleanup(patcher.stop)
        # Explicit disposable fixture, NOT a production migration.
        self.query('''
          CREATE TABLE auth_users(id uuid PRIMARY KEY);
          CREATE TABLE families(id serial PRIMARY KEY,name text,family_code text UNIQUE,
            created_by_user_id integer NOT NULL,home_address text,home_latitude float8,home_longitude float8,created_at text);
          CREATE TABLE users(id serial PRIMARY KEY,auth_user_id uuid UNIQUE REFERENCES auth_users ON DELETE SET NULL,
            family_id integer REFERENCES families,name text,shortcut_token text,carplay_setup_status text,
            family_role text, member_public_id uuid DEFAULT gen_random_uuid());
          ALTER TABLE families ADD FOREIGN KEY(created_by_user_id) REFERENCES users ON DELETE RESTRICT;
          CREATE TABLE account_deletion_jobs(auth_user_id uuid PRIMARY KEY,
            phase text NOT NULL DEFAULT 'draining' CHECK(phase IN ('draining','auth_pending')),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(created_at)),
            next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(next_attempt_at)),
            CHECK(next_attempt_at>=created_at));
          CREATE TABLE family_code_history(code text PRIMARY KEY);
          CREATE TABLE gemini_capacity_policies(capacity_pool text PRIMARY KEY,max_concurrency int);
          CREATE TABLE geocoding_capacity_policies(capacity_pool text PRIMARY KEY,max_concurrency int);
          INSERT INTO gemini_capacity_policies VALUES('gemini-default',50);
          INSERT INTO geocoding_capacity_policies VALUES('google-geocoding',20);
          CREATE TABLE chat_requests(id serial PRIMARY KEY,user_id int REFERENCES users ON DELETE RESTRICT,
            family_id int REFERENCES families ON DELETE RESTRICT,status text,lease_token uuid,
            lease_expires_at timestamptz);
          CREATE TABLE chat_tool_actions(chat_request_id int REFERENCES chat_requests ON DELETE RESTRICT);
          CREATE TABLE conversation_messages(user_id int REFERENCES users,
            chat_request_id int REFERENCES chat_requests ON DELETE RESTRICT);
          CREATE TABLE gemini_call_permits(permit_id uuid PRIMARY KEY,
            chat_request_id int REFERENCES chat_requests ON DELETE RESTRICT, attempt_token uuid,
            capacity_pool text REFERENCES gemini_capacity_policies ON DELETE RESTRICT,
            acquired_at timestamptz,expires_at timestamptz);
          CREATE TABLE geocoding_attempts(attempt_id uuid PRIMARY KEY,
            auth_user_id uuid REFERENCES auth_users ON DELETE CASCADE,
            capacity_pool text REFERENCES geocoding_capacity_policies ON DELETE RESTRICT,
            admitted_at timestamptz,permit_expires_at timestamptz);
          CREATE TABLE reservations(user_id int REFERENCES users);
          CREATE TABLE car_events(id serial PRIMARY KEY,user_id int REFERENCES users,
            family_id int REFERENCES families,driver_name text NOT NULL,status text NOT NULL,event_time text NOT NULL);
          CREATE TABLE push_subscriptions(user_id int REFERENCES users ON DELETE CASCADE);
          CREATE TABLE pwa_join_sessions(auth_user_id uuid PRIMARY KEY REFERENCES auth_users ON DELETE CASCADE,
            family_id int REFERENCES families ON DELETE SET NULL,step text DEFAULT 'family_name',
            family_name text,normalized_address text,resolved_address text,
            family_name_attempts smallint DEFAULT 0,address_attempts smallint DEFAULT 0,
            family_code_attempts smallint DEFAULT 0,locked_until timestamptz,
            created_at timestamptz DEFAULT NOW(),updated_at timestamptz DEFAULT NOW());
          CREATE TABLE family_address_confirmations(auth_user_id uuid REFERENCES auth_users ON DELETE CASCADE,
            user_id int REFERENCES users ON DELETE CASCADE,family_id int REFERENCES families ON DELETE CASCADE,
            token_digest bytea PRIMARY KEY,purpose text,normalized_address text,display_address text,
            latitude float8,longitude float8,expires_at timestamptz DEFAULT(clock_timestamp()+INTERVAL '15 minutes'));
          CREATE TABLE carplay_transition_admissions(user_id int REFERENCES users ON DELETE CASCADE,
            family_id int REFERENCES families ON DELETE CASCADE);
        ''')
        source = (Path(__file__).resolve().parents[1] / 'supabase/manual_migrations/2026092001_vehicle_identity_foundation.sql').read_text()
        ddl = source.split('ALTER TABLE public.users ADD CONSTRAINT', 1)[1].split('-- Nullable-first UUID backfill', 1)[0]
        self.query(('ALTER TABLE public.users ADD CONSTRAINT' + ddl).replace('public.', self.schema + '.'))
        self.creator = self.person()
        self.family = self.query("INSERT INTO families(name,family_code,created_by_user_id) VALUES('family','abc123',%s) RETURNING id", (self.creator[1],))[0][0]
        self.query('UPDATE users SET family_id=%s WHERE id=%s', (self.family, self.creator[1]))
        self.query("INSERT INTO family_code_history VALUES('abc123')")

    @contextmanager
    def connection(self):
        with self.psycopg.connect(self.dsn, connect_timeout=3) as conn:
            conn.execute(self.sql.SQL('SET search_path TO {}').format(self.sql.Identifier(self.schema)))
            conn.execute("SET statement_timeout='8s'")
            conn.commit()
            class Isolated:
                def execute(self, query, params=None):
                    return conn.execute(query.replace('auth.users', 'auth_users'), params)
                def transaction(self):
                    return conn.transaction()
            yield Isolated()

    def drop_schema(self):
        with self.psycopg.connect(self.dsn, connect_timeout=3) as conn:
            conn.execute(self.sql.SQL('DROP SCHEMA {} CASCADE').format(self.sql.Identifier(self.schema)))

    def query(self, query, params=None):
        with self.connection() as conn:
            cursor = conn.execute(query, params)
            return cursor.fetchall() if cursor.description else []

    def person(self, family=None):
        auth = str(uuid4())
        self.query('INSERT INTO auth_users VALUES(%s)', (auth,))
        uid = self.query("INSERT INTO users(auth_user_id,family_id,name,shortcut_token) VALUES(%s,%s,'same name',%s) RETURNING id", (auth, family, str(uuid4())))[0][0]
        return auth, uid

    def event(self, uid, status='connected'):
        self.query("INSERT INTO car_events(user_id,family_id,driver_name,status,event_time) VALUES(%s,%s,'same name',%s,'2026-09-17T10:00:00+00:00')", (uid, self.family, status))

    def request(self, uid):
        return self.query("INSERT INTO chat_requests(user_id,family_id,status,lease_token,lease_expires_at) VALUES(%s,%s,'processing',%s,clock_timestamp()+INTERVAL '120 seconds') RETURNING id", (uid, self.family, uuid4()))[0][0]

    def delete(self, person):
        deletion.confirm(self.pool, person[0])
        return deletion.cleanup(self.pool, person[0])

    def test_ordinary_fk_safe_cleanup_and_preservation(self):
        person = self.person(self.family)
        rid = self.request(person[1])
        self.query('INSERT INTO chat_tool_actions VALUES(%s)', (rid,))
        self.query('INSERT INTO conversation_messages VALUES(%s,%s)', (person[1], rid))
        for table in ('reservations', 'push_subscriptions'):
            self.query(f'INSERT INTO {table} VALUES(%s)', (person[1],))
        self.query('INSERT INTO pwa_join_sessions(auth_user_id,family_id) VALUES(%s,%s)', (person[0],self.family))
        self.query("INSERT INTO family_address_confirmations(auth_user_id,user_id,family_id,token_digest) VALUES(%s,%s,%s,%s)", (person[0],person[1],self.family,b'x'*32))
        self.query('INSERT INTO carplay_transition_admissions VALUES(%s,%s)', (person[1],self.family))
        self.event(person[1])
        self.assertTrue(self.delete(person))
        for table in ('reservations','push_subscriptions','chat_requests','chat_tool_actions','conversation_messages','pwa_join_sessions','family_address_confirmations','carplay_transition_admissions'):
            self.assertEqual(self.query(f'SELECT count(*) FROM {table}'), [(0,)])
        self.assertEqual(self.query('SELECT id FROM users'), [(self.creator[1],)])
        self.assertEqual(deletion.status(self.pool, person[0]), {'status':'auth_pending'})
        for table in ('families','family_code_history','gemini_capacity_policies','geocoding_capacity_policies'):
            self.assertEqual(self.query(f'SELECT count(*) FROM {table}'), [(1,)])

    def test_successor_is_min_remaining_id(self):
        first = self.person(self.family)
        self.person(self.family)
        self.assertTrue(self.delete(self.creator))
        self.assertEqual(self.query('SELECT created_by_user_id FROM families'), [(first[1],)])

    def test_last_member_deletes_family_and_pending_other_join_state(self):
        stranger = self.person()
        self.query('INSERT INTO pwa_join_sessions(auth_user_id,family_id) VALUES(%s,%s)', (stranger[0],self.family))
        self.event(None)
        self.assertTrue(self.delete(self.creator))
        self.assertEqual(self.query('SELECT count(*) FROM families'), [(0,)])
        self.assertEqual(self.query('SELECT count(*) FROM pwa_join_sessions'), [(0,)])
        self.assertEqual(self.query('SELECT id FROM users'), [(stranger[1],)])
        self.assertEqual(self.query('SELECT count(*) FROM family_code_history'), [(1,)])

    def test_active_deletion_barrier_preserves_legacy_and_other_member_events(self):
        member = self.person(self.family)
        self.event(None)
        self.event(member[1])  # malformed older unmatched connect
        self.event(self.creator[1])
        self.delete(self.creator)
        self.assertIsNone(self.database.get_active_driver(self.family))
        self.assertIsNone(self.database.get_latest_event(self.family))
        self.assertEqual(self.database.get_car_usage_history(self.family), [])
        self.assertEqual(self.query("SELECT count(*) FROM car_events WHERE user_id IS NULL AND status='connected'"), [(1,)])
        self.assertEqual(self.query("SELECT driver_name,user_id FROM car_events WHERE status='state_reset'"), [('',None)])
        self.assertEqual(self.query("SELECT count(*) FROM car_events WHERE status='disconnected'"), [(0,)])
        self.database.connect_car_atomically(member[1], 'member', self.family)
        self.assertEqual(self.database.get_active_driver(self.family)[1], member[1])

    def test_nonactive_deletion_keeps_current_driver(self):
        member = self.person(self.family)
        self.event(self.creator[1])
        self.event(self.creator[1], 'disconnected')
        self.event(member[1])
        self.delete(self.creator)
        self.assertEqual(self.database.get_active_driver(self.family)[1], member[1])

    def test_completed_history_does_not_pair_across_logical_reset(self):
        member = self.person(self.family)
        self.event(member[1])
        self.event(self.creator[1])
        self.delete(self.creator)
        self.event(member[1], 'disconnected')
        self.assertEqual(self.database.get_car_usage_history(self.family), [])

    def test_gemini_retention_blocks_all_cleanup(self):
        rid = self.request(self.creator[1])
        self.query("INSERT INTO gemini_call_permits VALUES(%s,%s,%s,'gemini-default',clock_timestamp(),clock_timestamp()+INTERVAL '120 seconds')", (uuid4(),rid,uuid4()))
        self.assertFalse(self.delete(self.creator))
        self.assertEqual(self.query('SELECT count(*) FROM users'), [(1,)])
        self.query("UPDATE gemini_call_permits SET expires_at=clock_timestamp()-INTERVAL '1 second'")
        self.assertTrue(deletion.cleanup(self.pool,self.creator[0]))

    def test_geocoding_retention_blocks_unmapped_deletion(self):
        auth = str(uuid4())
        self.query('INSERT INTO auth_users VALUES(%s)', (auth,))
        attempt = uuid4()
        self.query("INSERT INTO geocoding_attempts VALUES(%s,%s,'google-geocoding',clock_timestamp(),clock_timestamp()+INTERVAL '60 seconds')", (attempt,auth))
        deletion.confirm(self.pool, auth)
        self.assertFalse(deletion.cleanup(self.pool,auth))
        self.query('UPDATE geocoding_attempts SET permit_expires_at=NULL')
        self.assertTrue(deletion.cleanup(self.pool,auth))

    def test_rollback_keeps_creator_user_and_draining_job(self):
        self.person(self.family)
        deletion.confirm(self.pool,self.creator[0])
        self.query("CREATE TABLE rollback_blocker(user_id int REFERENCES users)")
        self.query('INSERT INTO rollback_blocker VALUES(%s)', (self.creator[1],))
        with self.assertRaises(self.psycopg.errors.ForeignKeyViolation):
            deletion.cleanup(self.pool,self.creator[0])
        self.assertEqual(self.query('SELECT created_by_user_id FROM families'), [(self.creator[1],)])
        self.assertEqual(deletion.status(self.pool,self.creator[0]), {'status':'draining'})

    def test_duplicate_confirmation_and_concurrent_workers(self):
        self.person(self.family)
        with ThreadPoolExecutor(2) as workers:
            list(workers.map(lambda _: deletion.confirm(self.pool,self.creator[0]), range(2)))
            self.assertEqual(self.query('SELECT count(*) FROM account_deletion_jobs'), [(1,)])
            self.assertEqual(list(workers.map(lambda _: deletion.cleanup(self.pool,self.creator[0]), range(2))), [True,True])
        self.assertEqual(deletion.confirm(self.pool,self.creator[0]), {'status':'auth_pending'})

    def test_concurrent_creator_and_successor_deletion(self):
        member = self.person(self.family)
        deletion.confirm(self.pool,self.creator[0]); deletion.confirm(self.pool,member[0])
        with ThreadPoolExecutor(2) as workers:
            list(workers.map(lambda p: deletion.cleanup(self.pool,p[0]), [self.creator,member]))
        self.assertEqual(self.query('SELECT count(*) FROM families'), [(0,)])

    def test_confirmation_waits_for_inflight_mutation_then_fences_continuation(self):
        entered, release = threading.Event(), threading.Event()
        def mutation():
            with self.connection() as conn:
                gate.require_user(conn,self.creator[1])
                entered.set()
                self.assertTrue(release.wait(3))
                conn.execute('INSERT INTO reservations VALUES(%s)', (self.creator[1],))
        with ThreadPoolExecutor(2) as workers:
            write = workers.submit(mutation)
            self.assertTrue(entered.wait(3))
            confirm = workers.submit(deletion.confirm,self.pool,self.creator[0])
            self.assertFalse(confirm.done())
            release.set(); write.result(); confirm.result()
        with self.connection() as conn:
            with self.assertRaises(gate.IdentityUnavailable):
                gate.require_user(conn,self.creator[1])

    def test_shortcut_and_auth_only_paths_gated(self):
        token = self.query('SELECT shortcut_token FROM users WHERE id=%s', (self.creator[1],))[0][0]
        deletion.confirm(self.pool,self.creator[0])
        with self.assertRaises(gate.IdentityUnavailable):
            self.database.get_user_by_token(token)
        with self.assertRaises(gate.IdentityUnavailable):
            self.database.start_pwa_join_session(self.creator[0])
        with self.assertRaises(gate.IdentityUnavailable):
            self.database.create_family_with_first_user('x','x','x',auth_user_id=self.creator[0])
        with self.assertRaises(gate.IdentityUnavailable):
            self.database.regenerate_family_code(self.creator[1],self.family)

    def test_auth_failure_retry_restart_and_absence_not_proxy_response(self):
        deletion.confirm(self.pool,self.creator[0])
        with patch.object(deletion, 'delete_auth_identity') as admin:
            deletion.run_due(self.pool)
            admin.assert_called_once()
            self.assertEqual(deletion.status(self.pool,self.creator[0]), {'status':'auth_pending'})
            deletion.run_due(self.pool)
            admin.assert_called_once()  # durable schedule prevents immediate retry
        self.query('DELETE FROM auth_users WHERE id=%s', (self.creator[0],))
        with patch.object(deletion,'delete_auth_identity') as admin:
            deletion.recover_one(self.pool,self.creator[0])
            admin.assert_not_called()
        self.assertEqual(deletion.status(self.pool,self.creator[0]), {'status':'completed'})
        with self.connection() as conn:
            with self.assertRaises(gate.IdentityUnavailable):
                gate.require_auth(conn,self.creator[0])
        self.assertEqual(deletion.confirm(self.pool,self.creator[0]), {'status':'completed'})

    def test_preview_consequences_are_server_derived(self):
        self.assertEqual(deletion.preview(self.pool,self.creator[0]), {'consequence':'family_deleted'})
        member = self.person(self.family)
        self.assertEqual(deletion.preview(self.pool,self.creator[0]), {'consequence':'management_transferred'})
        self.assertEqual(deletion.preview(self.pool,member[0]), {'consequence':'personal'})

    def test_join_completion_races_last_member_cleanup_without_orphans(self):
        joiner = str(uuid4())
        self.query('INSERT INTO auth_users VALUES(%s)', (joiner,))
        self.query("INSERT INTO pwa_join_sessions(auth_user_id,family_id,step) VALUES(%s,%s,'user_name')", (joiner,self.family))
        deletion.confirm(self.pool,self.creator[0])
        barrier = threading.Barrier(2)
        def join():
            barrier.wait()
            try:
                return self.database.complete_pwa_join(joiner,'new member')['created']
            except self.database.InvalidJoinStepError:
                return False
        def cleanup():
            barrier.wait()
            return deletion.cleanup(self.pool,self.creator[0])
        with ThreadPoolExecutor(2) as workers:
            joining, deleting = workers.submit(join), workers.submit(cleanup)
            joined = joining.result(10)
            self.assertTrue(deleting.result(10))
        if joined:
            survivor = self.query('SELECT id FROM users WHERE auth_user_id=%s',(joiner,))[0][0]
            self.assertEqual(self.query('SELECT created_by_user_id FROM families'),[(survivor,)])
        else:
            self.assertEqual(self.query('SELECT count(*) FROM families'),[(0,)])
        self.assertEqual(self.query('SELECT count(*) FROM pwa_join_sessions'),[(0,)])

    def test_creator_operations_race_confirmation_with_consistent_lock_order(self):
        member = self.person(self.family)
        member_ref = self.query('SELECT member_public_id FROM users WHERE id=%s',(member[1],))[0][0]
        token = self.database.issue_family_address_confirmation(self.creator[0],'address','display',1,1,
                    user_id=self.creator[1],family_id=self.family)
        operations = [
            lambda: self.database.regenerate_family_code(self.creator[1],self.family),
            lambda: self.database.update_family_address(self.creator[1],self.family,self.creator[0],token),
            lambda: self.database.update_family_member_role(self.creator[1],self.family,member_ref,'parent'),
        ]
        barrier = threading.Barrier(4)
        def run(operation):
            barrier.wait()
            try:
                operation()
                return 'committed'
            except gate.IdentityUnavailable:
                return 'gated'
        with ThreadPoolExecutor(4) as workers:
            futures = [workers.submit(run,op) for op in operations]
            confirming = workers.submit(run,lambda: deletion.confirm(self.pool,self.creator[0]))
            self.assertEqual(confirming.result(10),'committed')
            for future in futures:
                self.assertIn(future.result(10),('committed','gated'))
        self.assertTrue(deletion.cleanup(self.pool,self.creator[0]))
        self.assertEqual(self.query('SELECT created_by_user_id FROM families'),[(member[1],)])

    def test_carplay_inflight_write_finishes_before_confirmation_then_is_erased(self):
        self.person(self.family)
        entered, release = threading.Event(), threading.Event()
        original = self.database._insert_car_event_on_connection
        def held_insert(*args):
            entered.set()
            self.assertTrue(release.wait(3))
            return original(*args)
        with patch.object(self.database,'_insert_car_event_on_connection',side_effect=held_insert), ThreadPoolExecutor(2) as workers:
            connecting = workers.submit(self.database.connect_car_atomically,self.creator[1],'creator',self.family)
            self.assertTrue(entered.wait(3))
            confirming = workers.submit(deletion.confirm,self.pool,self.creator[0])
            release.set()
            self.assertEqual(connecting.result(10)['transition'],'connected')
            confirming.result(10)
        self.assertTrue(deletion.cleanup(self.pool,self.creator[0]))
        self.assertIsNone(self.database.get_active_driver(self.family))
        with self.assertRaises(gate.IdentityUnavailable):
            self.database.connect_car_atomically(self.creator[1],'creator',self.family)

    def test_uncertain_extension_wins_over_cleanup_expiry_observation(self):
        # Independent connections: cleanup waits on the retained row and then
        # observes the newly committed expiry, not an earlier expired snapshot.
        attempt = uuid4()
        self.query("INSERT INTO geocoding_attempts VALUES(%s,%s,'google-geocoding',clock_timestamp(),clock_timestamp()-INTERVAL '1 second')", (attempt,self.creator[0]))
        deletion.confirm(self.pool,self.creator[0])
        entered = threading.Event()
        original = deletion._drained
        def entering(*args):
            entered.set()
            return original(*args)
        with patch.object(deletion,'_drained',side_effect=entering), ThreadPoolExecutor(1) as workers:
            with self.connection() as holder:
                holder.execute("UPDATE geocoding_attempts SET permit_expires_at=clock_timestamp()+INTERVAL '60 seconds' WHERE attempt_id=%s", (attempt,))
                future = workers.submit(deletion.cleanup,self.pool,self.creator[0])
                self.assertTrue(entered.wait(3))
            self.assertFalse(future.result(10))
        self.assertEqual(self.query('SELECT count(*) FROM users'),[(1,)])
        self.assertEqual(self.query('SELECT count(*) FROM geocoding_attempts WHERE permit_expires_at>clock_timestamp()'),[(1,)])

    def test_gemini_finish_can_release_while_gated_and_no_new_admission(self):
        import gemini_capacity
        rid = self.request(self.creator[1])
        token = self.query('SELECT lease_token FROM chat_requests WHERE id=%s',(rid,))[0][0]
        permit, _ = gemini_capacity.acquire(self.pool,rid,token)
        deletion.confirm(self.pool,self.creator[0])
        self.assertFalse(deletion.cleanup(self.pool,self.creator[0]))
        with self.assertRaises(gate.IdentityUnavailable):
            gemini_capacity.acquire(self.pool,rid,token)
        gemini_capacity.finish(self.pool,permit,token)
        self.assertTrue(deletion.cleanup(self.pool,self.creator[0]))

    def test_post_provider_chat_mutation_and_finalization_are_fenced(self):
        from tests.test_chat_service import load_chat_service
        from identity import CurrentUser
        chat = load_chat_service()
        chat.pool = self.pool
        chat.require_user, chat.require_request = gate.require_user, gate.require_request
        rid = self.request(self.creator[1])
        token = self.query('SELECT lease_token FROM chat_requests WHERE id=%s',(rid,))[0][0]
        user = CurrentUser(user_id=self.creator[1],family_id=self.family,name='creator',auth_user_id=self.creator[0])
        deletion.confirm(self.pool,self.creator[0])
        for operation in (
            lambda: chat._renew_lease(rid,token),
            lambda: chat._execute_mutation(rid,token,user,'create_reservation',{}),
            lambda: chat._finalize_request(rid,token,user,{'assistant_message':{}}),
            lambda: chat._claim_request(user,uuid4(),'message',uuid4()),
        ):
            with self.assertRaises(gate.IdentityUnavailable):
                operation()
        self.assertEqual(self.query('SELECT count(*) FROM reservations'),[(0,)])
        self.assertEqual(self.query('SELECT count(*) FROM conversation_messages'),[(0,)])

    def test_auth_http_is_outside_transaction_and_lost_response_is_recoverable(self):
        deletion.confirm(self.pool,self.creator[0])
        def admin(auth):
            self.assertEqual(deletion.status(self.pool,auth),{'status':'auth_pending'})
            # A distinct DB transaction can acquire the identity exclusively.
            with self.connection() as conn:
                conn.execute("SET LOCAL lock_timeout='500ms'")
                gate.lock_identity(conn,auth,exclusive=True)
                conn.execute('DELETE FROM auth.users WHERE id=%s',(auth,))
            raise TimeoutError('response lost')
        with patch.object(deletion,'delete_auth_identity',side_effect=admin):
            with self.assertRaises(TimeoutError):
                deletion.recover_one(self.pool,self.creator[0])
        self.assertEqual(deletion.status(self.pool,self.creator[0]),{'status':'auth_pending'})
        deletion.recover_one(self.pool,self.creator[0])
        self.assertEqual(deletion.status(self.pool,self.creator[0]),{'status':'completed'})

    def test_unmapped_stale_auth_is_gated_after_job_removed(self):
        self.delete(self.creator)
        self.query('DELETE FROM auth_users WHERE id=%s',(self.creator[0],))
        deletion.recover_one(self.pool,self.creator[0])
        for operation in (
            lambda: self.database.start_pwa_join_session(self.creator[0]),
            lambda: self.database.issue_family_address_confirmation(self.creator[0],'x','x',1,1),
            lambda: self.database.create_family_with_first_user('x','x','x',auth_user_id=self.creator[0]),
        ):
            with self.assertRaises(gate.IdentityUnavailable):
                operation()
        self.assertEqual(self.query('SELECT count(*) FROM account_deletion_jobs'),[(0,)])
