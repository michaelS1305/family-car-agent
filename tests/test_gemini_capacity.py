"""Unit contracts plus opt-in, independent-connection PostgreSQL race tests.

Race tests require GEMINI_TEST_DATABASE_URL pointing to a LOCAL disposable
database named test_gemini*. Never reads DATABASE_URL or executes migrations.
"""
from contextlib import contextmanager, nullcontext
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
from uuid import uuid4

import gemini_capacity as capacity
from test_chat_service import load_chat_service, Cursor, ConnectionContext
from test_database_atomic_creation import load_database_module_without_real_connection
from identity import CurrentUser


class CapacityUnitTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(capacity, 'require_request')
        guard.start()
        self.addCleanup(guard.stop)

    def test_provider_timeout_retry_latency_and_connection_boundary(self):
        pool = Mock()
        wrapper = capacity.ProviderCalls(pool, 1, 'attempt', 'request', time.monotonic())
        def provider(**kwargs):
            self.assertEqual(kwargs['config']['http_options'],
                             {'timeout': 30000, 'retry_options': {'attempts': 1}})
            self.assertNotIn('max_output_tokens', kwargs['config'])
            pool.connection.assert_not_called()
            return 'answer'
        with patch.object(capacity, 'acquire', return_value=('permit', 75)), \
             patch.object(capacity, 'finish') as finish, self.assertLogs(capacity.logger, level='INFO') as logs:
            self.assertEqual(wrapper(provider, contents='private message'), 'answer')
        finish.assert_called_once_with(pool, 'permit', 'attempt', uncertain=False)
        self.assertIn('latency_ms=', logs.output[0])
        self.assertNotIn('private message', repr(logs.output))

    def test_timeout_shrinks_and_fixed_deadline_never_slides(self):
        wrapper = capacity.ProviderCalls(Mock(), 1, 't', 'r', 100)
        with patch.object(capacity.time, 'monotonic', return_value=160), \
             patch.object(capacity, 'acquire', return_value=('p', 50)), \
             patch.object(capacity, 'finish'):
            provider = Mock()
            wrapper(provider)
            self.assertEqual(provider.call_args.kwargs['config']['http_options']['timeout'], 10000)
        with patch.object(capacity.time, 'monotonic', return_value=171), \
             patch.object(capacity, 'acquire') as acquire:
            with self.assertRaises(capacity.AttemptExpired):
                wrapper(Mock())
            acquire.assert_not_called()
        self.assertEqual(wrapper.deadline, 175)

    def test_ambiguous_failure_retains_owned_permit(self):
        pool = Mock()
        with patch.object(capacity, 'acquire', return_value=('p', 75)), \
             patch.object(capacity, 'finish') as finish:
            with self.assertRaises(TimeoutError):
                capacity.ProviderCalls(pool, 1, 't', 'r', time.monotonic())(
                    Mock(side_effect=TimeoutError('private')))
        finish.assert_called_once_with(pool, 'p', 't', uncertain=True)

    def test_installed_sdk_options_disable_retries(self):
        from google.genai import types
        from google.genai._api_client import retry_args
        from types import SimpleNamespace
        config = types.GenerateContentConfig(http_options={'timeout': 30000, 'retry_options': {'attempts': 1}})
        self.assertEqual(config.http_options.timeout, 30000)
        self.assertTrue(retry_args(config.http_options.retry_options)['stop'](SimpleNamespace(attempt_number=1)))
        self.assertIsNone(config.max_output_tokens)
        self.assertIsNone(config.thinking_config)

    def test_temporary_capacity_preserves_recovery_and_post_mutation_fallback(self):
        for action in (None, {'action_type': 'create_reservation', 'result': {'success': True, 'code': 'RESERVATION_CREATED'}}):
            chat = load_chat_service()
            with patch.object(chat, '_claim_request', return_value={'outcome': 'claimed', 'id': 1}), \
                 patch.object(chat, '_get_completed_action', side_effect=[None, action]), \
                 patch.object(chat, '_load_model_history', return_value=[]), \
                 patch.object(chat, '_renew_lease'), \
                 patch.object(chat, 'generate_agent_response', side_effect=capacity.CapacityUnavailable()), \
                 patch.object(chat, '_finalize_request', side_effect=lambda _id, _token, _user, response: response), \
                 patch.object(chat, '_mark_failed') as failed:
                chat.pool.connection.return_value = ConnectionContext(Mock())
                if action:
                    self.assertEqual(chat.process_chat_message(uuid4(), 'm', CurrentUser(user_id=1, family_id=1, name='A'))['status'], 'completed')
                else:
                    with self.assertRaises(chat.ChatError) as raised:
                        chat.process_chat_message(uuid4(), 'm', CurrentUser(user_id=1, family_id=1, name='A'))
                    self.assertEqual(raised.exception.code, 'GEMINI_CAPACITY_UNAVAILABLE')
                    self.assertEqual(raised.exception.retry_after_seconds, 5)
                failed.assert_not_called()

    def test_release_and_retention_are_ownership_scoped(self):
        conn = Mock()
        pool = Mock()
        pool.connection.return_value = ConnectionContext(conn)
        capacity.finish(pool, 'p', 't')
        sql, args = conn.execute.call_args.args
        self.assertIn('permit_id = %s AND attempt_token = %s', sql)
        self.assertEqual(args, ('p', 't'))
        capacity.finish(pool, 'p', 't', uncertain=True)
        self.assertIn("clock_timestamp() + INTERVAL '45 seconds'", conn.execute.call_args.args[0])

    def test_expired_attempt_cannot_mutate_or_finalize(self):
        chat = load_chat_service()
        conn = Mock()
        conn.execute.return_value = Cursor(None)
        conn.transaction.return_value = nullcontext()
        chat.pool.connection.return_value = ConnectionContext(conn)
        user = CurrentUser(user_id=1, name='A', family_id=1)
        with self.assertRaises(chat.ChatLeaseLostError):
            chat._execute_mutation(1, 't', user, 'cancel_reservation', {'reservation_id': 1})
        with self.assertRaises(chat.ChatLeaseLostError):
            chat._finalize_request(1, 't', user, chat._response('r', 'a'))
        chat._cancel_reservation_on_connection.assert_not_called()

    def test_third_attempt_finalizes_persisted_action_without_processing(self):
        chat = load_chat_service()
        conn = Mock()
        conn.transaction.return_value = nullcontext()
        row = (1, 1, 'm', 'processing', None, None, None, True, 3)
        conn.execute.side_effect = [Cursor(), Cursor(row),
            Cursor(('create_reservation', {'success': True, 'code': 'RESERVATION_CREATED'})),
            Cursor(), Cursor()]
        chat.pool.connection.return_value = ConnectionContext(conn)
        result = chat.process_chat_message(uuid4(), 'm', CurrentUser(user_id=1, family_id=1, name='A'))
        self.assertEqual(result['status'], 'completed')
        chat.generate_agent_response.assert_not_called()
        chat._create_reservation_on_connection.assert_not_called()
        statements = [call.args[0] for call in conn.execute.call_args_list]
        self.assertFalse(any('processing_attempts =' in sql for sql in statements))
        self.assertFalse(any('gemini_call_permits' in sql for sql in statements))
        self.assertEqual(sum('INSERT INTO conversation_messages' in sql for sql in statements), 1)

    def test_missing_or_invalid_completed_action_exhausts_allowance(self):
        for action in (None, ('create_reservation', None), ('create_reservation', {}), ('unknown', {'success': True, 'code': 'x'})):
            with self.subTest(action=action):
                chat = load_chat_service()
                conn = Mock()
                conn.transaction.return_value = nullcontext()
                conn.execute.side_effect = [Cursor(), Cursor((1, 1, 'm', 'processing', None, None, None, True, 3)), Cursor(action), Cursor()]
                chat.pool.connection.return_value = ConnectionContext(conn)
                with self.assertRaises(chat.ChatError) as raised:
                    chat.process_chat_message(uuid4(), 'm', CurrentUser(user_id=1, family_id=1, name='A'))
                self.assertEqual(raised.exception.code, 'CHAT_ATTEMPTS_EXHAUSTED')
                self.assertIn("status = 'completed'", conn.execute.call_args_list[2].args[0])
                chat.generate_agent_response.assert_not_called()

    def test_new_rate_or_concurrency_rejection_inserts_nothing(self):
        for responses, code in (([Cursor(), Cursor(None), Cursor((10,))], 'CHAT_RATE_LIMITED'),
                                ([Cursor(), Cursor(None), Cursor((1,)), Cursor((2,))], 'CHAT_CONCURRENCY_LIMITED')):
            chat = load_chat_service()
            conn = Mock()
            conn.transaction.return_value = nullcontext()
            conn.execute.side_effect = responses
            chat.pool.connection.return_value = ConnectionContext(conn)
            with self.assertRaises(chat.ChatError) as raised:
                chat._claim_request(CurrentUser(user_id=1, family_id=1, name='A'), uuid4(), 'm', uuid4())
            self.assertEqual(raised.exception.code, code)
            self.assertFalse(any('INSERT' in call.args[0] for call in conn.execute.call_args_list))

    def test_bounded_reservations_metadata_and_scope(self):
        database = load_database_module_without_real_connection()
        conn = Mock()
        conn.execute.return_value.fetchall.return_value = [(uuid4(), 'A', 'start', 'end', 'active', None, None) for i in range(21)]
        database.pool.connection.return_value = ConnectionContext(conn)
        result = database.get_ai_reservations(4, 7)
        self.assertEqual(len(result['items']), 20)
        self.assertTrue(result['truncated'])
        sql, args = conn.execute.call_args.args
        self.assertIn('ORDER BY r.start_time, r.id LIMIT 21', sql)
        self.assertEqual(args, (4, 7, 7))
        conn.execute.return_value.fetchall.return_value = []
        self.assertFalse(database.get_ai_reservations(4)['truncated'])

    def test_migration_contract(self):
        sql = (Path(__file__).resolve().parents[1] / 'supabase/manual_migrations/2026091401_gemini_capacity.sql').read_text()
        for text in ['BEGIN;', 'COMMIT;', 'ON DELETE RESTRICT', 'BETWEEN 1 AND 3',
                     'FROM PUBLIC, anon, authenticated', "('gemini-default', 50)",
                     '(capacity_pool, expires_at)', 'isfinite(expires_at)']:
            self.assertIn(text, sql)
        for text in ['ENABLE ROW LEVEL SECURITY', 'CREATE POLICY', 'ALTER DEFAULT PRIVILEGES',
                     '(user_id, created_at)', '2026090602']:
            self.assertNotIn(text, sql)


@unittest.skipUnless(os.environ.get('GEMINI_TEST_DATABASE_URL'), 'No isolated local PostgreSQL test database configured')
class PostgresConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql
        cls.psycopg, cls.sql = psycopg, sql
        cls.dsn = os.environ['GEMINI_TEST_DATABASE_URL']
        url = urlsplit(cls.dsn)
        if url.hostname not in {'localhost', '127.0.0.1', '::1'} or not url.path.startswith('/test_gemini'):
            raise RuntimeError('Only explicitly named local test_gemini databases are permitted')

    def setUp(self):
        guard = patch.object(capacity, 'require_request')
        guard.start()
        self.addCleanup(guard.stop)
        self.schema = 'gemini_test_' + uuid4().hex
        with self.psycopg.connect(self.dsn) as conn:
            conn.execute(self.sql.SQL('CREATE SCHEMA {}').format(self.sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        self.pool = Mock()
        self.pool.connection = self.connection
        self.chat = load_chat_service()
        self.chat.pool = self.pool
        self.user = CurrentUser(user_id=1, family_id=1, name='A')
        with self.connection() as conn:
            conn.execute('''CREATE TABLE chat_requests (
                id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, request_id uuid NOT NULL,
                user_id integer NOT NULL, family_id integer NOT NULL, status text NOT NULL,
                original_message text NOT NULL, lease_token uuid NOT NULL, lease_expires_at timestamptz NOT NULL,
                created_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_at timestamptz,
                completed_at timestamptz, final_response jsonb, error_http_status smallint, error_payload jsonb,
                processing_attempts smallint NOT NULL DEFAULT 1 CHECK(processing_attempts BETWEEN 1 AND 3),
                UNIQUE(user_id, request_id))''')
            conn.execute('''CREATE TABLE chat_tool_actions (
                chat_request_id bigint PRIMARY KEY REFERENCES chat_requests(id), action_type text,
                status text, result jsonb)''')
            conn.execute('''CREATE TABLE conversation_messages (
                user_id integer, role text, content text, created_at text, chat_request_id bigint)''')
            conn.execute('''CREATE TABLE gemini_capacity_policies (capacity_pool text PRIMARY KEY, max_concurrency integer)''')
            conn.execute("INSERT INTO gemini_capacity_policies VALUES ('gemini-default',50)")
            conn.execute('''CREATE TABLE gemini_call_permits (
                permit_id uuid PRIMARY KEY, chat_request_id bigint UNIQUE REFERENCES chat_requests(id),
                attempt_token uuid, capacity_pool text, acquired_at timestamptz, expires_at timestamptz)''')

    @contextmanager
    def connection(self):
        with self.psycopg.connect(self.dsn) as conn:
            conn.execute(self.sql.SQL('SET search_path TO {}').format(self.sql.Identifier(self.schema)))
            conn.commit()
            yield conn

    def drop_schema(self):
        with self.psycopg.connect(self.dsn) as conn:
            conn.execute(self.sql.SQL('DROP SCHEMA {} CASCADE').format(self.sql.Identifier(self.schema)))

    def claim(self, request=None):
        return self.chat._claim_request(self.user, request or uuid4(), 'm', uuid4())

    def test_concurrent_admission_rate_no_rejected_rows(self):
        def worker(_):
            try:
                claim = self.claim()
                with self.connection() as conn:
                    conn.execute("UPDATE chat_requests SET status='completed' WHERE id=%s", (claim['id'],))
                return True
            except self.chat.ChatError:
                return False
        # Independent connections and real advisory locks, not sequential mocks.
        with ThreadPoolExecutor(max_workers=16) as executor:
            results = list(executor.map(worker, range(80)))
        with self.connection() as conn:
            count = conn.execute('SELECT count(*) FROM chat_requests').fetchone()[0]
        self.assertEqual(count, sum(results))
        self.assertLessEqual(count, 10)

    def test_concurrent_max_two_attempts_and_same_id_replay(self):
        def worker(_):
            try:
                return self.claim()['outcome']
            except self.chat.ChatError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(worker, range(30)))
        self.assertEqual(results.count('claimed'), 2)
        with self.connection() as conn:
            request = conn.execute('SELECT request_id FROM chat_requests LIMIT 1').fetchone()[0]
        self.assertEqual(self.claim(request)['outcome'], 'processing')
        with self.connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM chat_requests').fetchone()[0], 2)

    def test_concurrent_finalization_only_after_third_mutation(self):
        request = uuid4()
        claim = self.claim(request)
        with self.connection() as conn:
            conn.execute("UPDATE chat_requests SET processing_attempts=3, lease_expires_at=clock_timestamp()-INTERVAL '1 second'")
            conn.execute("INSERT INTO chat_tool_actions VALUES (%s,'create_reservation','completed',%s::jsonb)",
                         (claim['id'], '{"success":true,"code":"RESERVATION_CREATED"}'))
        with patch.object(capacity, 'acquire') as acquire:
            with ThreadPoolExecutor(max_workers=12) as executor:
                responses = list(executor.map(lambda _: self.chat.process_chat_message(request, 'm', self.user), range(20)))
        self.assertTrue(all(response == responses[0] for response in responses))
        acquire.assert_not_called()
        self.chat.generate_agent_response.assert_not_called()
        self.chat._create_reservation_on_connection.assert_not_called()
        with self.connection() as conn:
            self.assertEqual(conn.execute('SELECT processing_attempts FROM chat_requests').fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT count(*) FROM conversation_messages WHERE role='assistant'").fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM chat_tool_actions').fetchone()[0], 1)

    def test_no_completed_action_cannot_start_fourth_attempt(self):
        for action_status in (None, 'processing', 'failed'):
            with self.subTest(status=action_status):
                request = uuid4()
                claim = self.claim(request)
                with self.connection() as conn:
                    conn.execute("UPDATE chat_requests SET processing_attempts=3, lease_expires_at=clock_timestamp()-INTERVAL '1 second' WHERE id=%s", (claim['id'],))
                    if action_status:
                        conn.execute("INSERT INTO chat_tool_actions VALUES (%s,'create_reservation',%s,%s::jsonb)",
                                     (claim['id'], action_status, '{"success":true,"code":"RESERVATION_CREATED"}'))
                self.assertEqual(self.claim(request)['error']['detail']['code'], 'CHAT_ATTEMPTS_EXHAUSTED')

    def test_concurrent_permits_expiry_ownership_and_uncertainty(self):
        with self.connection() as conn:
            for i in range(80):
                conn.execute("""INSERT INTO chat_requests (request_id,user_id,family_id,status,original_message,lease_token,lease_expires_at)
                    VALUES (%s,%s,1,'processing','m',%s,clock_timestamp()+INTERVAL '120 seconds')""", (uuid4(), i + 10, uuid4()))
            requests = conn.execute('SELECT id,lease_token FROM chat_requests ORDER BY id').fetchall()
        def worker(row):
            try:
                return capacity.acquire(self.pool, *row)[0]
            except capacity.CapacityUnavailable:
                return None
        with ThreadPoolExecutor(max_workers=24) as executor:
            permits = list(executor.map(worker, requests))
        self.assertEqual(sum(p is not None for p in permits), 50)
        index = next(i for i, p in enumerate(permits) if p)
        permit, (request, token) = permits[index], requests[index]
        capacity.finish(self.pool, permit, uuid4())
        with self.connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM gemini_call_permits').fetchone()[0], 50)
        capacity.finish(self.pool, permit, token, uncertain=True)
        with self.assertRaises(capacity.CapacityUnavailable):
            capacity.acquire(self.pool, request, token)
        capacity.finish(self.pool, permit, token)
        capacity.finish(self.pool, permit, token)
        capacity.acquire(self.pool, request, token)
        with self.connection() as conn:
            conn.execute("UPDATE gemini_call_permits SET expires_at=clock_timestamp()-INTERVAL '1 second'")
        capacity.acquire(self.pool, request, token)

    def test_cleanup_rechecks_expiry_after_concurrent_uncertain_retention(self):
        from queue import Queue

        original_id = uuid4()
        original = self.claim(original_id)['id']
        other = self.claim()['id']
        with self.connection() as conn:
            tokens = dict(conn.execute('SELECT id, lease_token FROM chat_requests').fetchall())
        permit, _ = capacity.acquire(self.pool, original, tokens[original])
        with self.connection() as conn:
            conn.execute("UPDATE gemini_call_permits SET expires_at=clock_timestamp()-INTERVAL '1 second'")
            conn.execute("UPDATE chat_requests SET lease_expires_at=clock_timestamp()-INTERVAL '1 second' WHERE id=%s", (original,))

        cleanup_pid = Queue()

        @contextmanager
        def cleanup_connection():
            with self.connection() as conn:
                cleanup_pid.put(conn.info.backend_pid)
                yield conn

        cleanup_pool = Mock()
        cleanup_pool.connection = cleanup_connection
        with ThreadPoolExecutor(max_workers=1) as executor:
            # Retention writes the extension but holds its transaction open.
            # Cleanup sees the previous expired version, then blocks on DELETE.
            with self.connection() as retaining:
                @contextmanager
                def retention_connection():
                    yield retaining

                retention_pool = Mock()
                retention_pool.connection = retention_connection
                capacity.finish(retention_pool, permit, tokens[original], uncertain=True)
                future = executor.submit(capacity.acquire, cleanup_pool, other, tokens[other])
                pid = cleanup_pid.get(timeout=5)
                with self.connection() as observer:
                    deadline = time.monotonic() + 5
                    blocked = False
                    while time.monotonic() < deadline:
                        blockers = observer.execute('SELECT pg_blocking_pids(%s)', (pid,)).fetchone()[0]
                        if retaining.info.backend_pid in blockers:
                            blocked = True
                            break
                        time.sleep(0.01)
                    self.assertTrue(blocked, 'Cleanup must compete with the retention row lock')
                # Commit before cleanup obtains the row: DELETE must recheck expiry.
            future.result(timeout=5)

        with self.connection() as conn:
            self.assertTrue(conn.execute(
                'SELECT expires_at > clock_timestamp() FROM gemini_call_permits WHERE permit_id=%s',
                (permit,),
            ).fetchone()[0])
            self.assertEqual(conn.execute(
                'SELECT count(*) FROM gemini_call_permits WHERE expires_at > clock_timestamp()'
            ).fetchone()[0], 2)
        with self.assertRaises(self.chat.ChatError) as raised:
            self.claim(original_id)
        self.assertEqual(raised.exception.code, 'GEMINI_CAPACITY_UNAVAILABLE')
