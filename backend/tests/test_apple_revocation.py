"""Synthetic provider tests and disposable LOCAL PostgreSQL workflow tests.

No migration is executed and no real Apple or Supabase request is made.
"""
from contextlib import contextmanager
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

import requests

import account_deletion as deletion
import apple_revocation as revocation
from apple_credentials import Store, capture
from tests.test_apple_credentials import configuration
from tests.test_account_deletion import AccountDeletionPostgresTests


class ProviderTests(unittest.TestCase):
    def test_request_and_already_revoked_200(self):
        config = configuration()
        session = MagicMock()
        session.__enter__.return_value = session
        response = session.post.return_value.__enter__.return_value
        for status, expected in ((200, 'apple_revocation_confirmed'),
                                 (400, 'apple_revocation_provider_rejected'),
                                 (500, 'apple_revocation_provider_rejected')):
            response.status_code = status
            self.assertEqual(revocation.revoke(config, 'synthetic-refresh', http=session), expected)
        args, kwargs = session.post.call_args
        self.assertEqual(args, ('https://appleid.apple.com/auth/revoke',))
        self.assertEqual(kwargs['data']['token_type_hint'], 'refresh_token')
        self.assertEqual(kwargs['data']['client_id'], config.client)
        self.assertEqual(kwargs['timeout'], (5, 10))
        self.assertFalse(kwargs['allow_redirects'])
        self.assertTrue(kwargs['stream'])
        self.assertFalse(session.trust_env)
        response.json.assert_not_called()
        response.iter_content.assert_not_called()

    def test_timeout_network_error_never_exposes_exception(self):
        for error, category in ((requests.Timeout('PRIVATE_SENTINEL'), 'apple_revocation_timeout'),
                                (requests.ConnectionError('PRIVATE_SENTINEL'), 'apple_revocation_network_error')):
            session = MagicMock()
            session.__enter__.return_value = session
            session.post.side_effect = error
            self.assertEqual(revocation.revoke(configuration(), 'PRIVATE_TOKEN', http=session), category)

    def test_log_allowlist_and_handler_failure(self):
        ref = uuid4()
        with self.assertLogs(revocation.logger, level='INFO') as logs:
            revocation.emit(ref, 'apple_revoke', 'pending', 'apple_revocation_timeout')
            revocation.emit(ref, 'PRIVATE_OPERATION', 'pending')
            revocation.emit(ref, 'apple_revoke', 'pending', 'PRIVATE_ERROR')
            revocation.emit('PRIVATE_OWNER', 'finalize', 'revoked')
        self.assertEqual(len(logs.output), 1)
        self.assertIn(str(ref), logs.output[0])
        self.assertNotIn('PRIVATE', str(logs.output))
        with patch.object(revocation.logger, 'warning', side_effect=RuntimeError('private')):
            revocation.emit(ref, 'finalize', 'revoked')

    def test_migration_is_additive_private_and_keeps_public_phases(self):
        sql = (Path(__file__).resolve().parents[2] /
               'supabase/manual_migrations/2026111501_apple_revocation.sql').read_text()
        self.assertIn('ALTER TABLE public.account_deletion_jobs', sql)
        self.assertIn('SECURITY INVOKER', sql)
        self.assertIn('FROM PUBLIC, anon, authenticated', sql)
        self.assertIn('failure_category=expected_category', sql)
        self.assertIn('instructions_arranged IS DISTINCT FROM true', sql)
        self.assertNotIn('ALTER COLUMN phase', sql)
        self.assertNotIn('DELETE FROM', sql)
        self.assertNotIn('SECURITY DEFINER', sql)


@unittest.skipUnless(os.environ.get('GEMINI_TEST_DATABASE_URL'), 'Local PostgreSQL not configured')
class WorkflowTests(unittest.TestCase):
    production = False
    def setUp(self):
        self.fixture = AccountDeletionPostgresTests(methodName='runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.pool = self.fixture.pool
        self.query = self.fixture.query
        # Compile ONLY the function definition inside the disposable fixture
        # schema, like the existing deletion fixture's vehicle DDL. Never apply
        # the migration or create/alter an object in public/auth.
        migration = (Path(__file__).resolve().parents[2] /
                     'supabase/manual_migrations/2026111501_apple_revocation.sql').read_text()
        function = 'CREATE FUNCTION ' + migration.split('CREATE FUNCTION ', 1)[1].split('REVOKE ALL', 1)[0]
        function = function.replace('public.', self.fixture.schema + '.').replace(
            'pg_catalog, public', 'pg_catalog, ' + self.fixture.schema)
        self.query(function)
        self.owner = self.fixture.creator[0]
        self.config = configuration()
        if self.production:
            self.config = replace(self.config, environment='prod', client='com.familycaragent.app', team='GT43M39TLK')
        environment_patch = patch.dict(os.environ, {'SUPABASE_URL':'https://xrgijytfigcuxmdktvmd.supabase.co' if self.production else 'https://jouhqvbxhsvkluwkqmdg.supabase.co'})
        environment_patch.start()
        self.addCleanup(environment_patch.stop)
        self.subject = 'synthetic-apple-sub'
        self.query("INSERT INTO auth_identities VALUES(%s,'apple',%s,%s)",
                   (self.owner, self.subject, json.dumps({'sub': self.subject})))
        config_patch = patch.object(revocation.Config, 'load', return_value=self.config)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        # Tests fail rather than accidentally contacting either provider.
        apple_patch = patch.object(revocation, 'revoke', return_value='apple_revocation_confirmed')
        self.apple = apple_patch.start()
        self.addCleanup(apple_patch.stop)
        auth_patch = patch.object(deletion, 'delete_auth_identity', side_effect=self.delete_auth)
        self.auth = auth_patch.start()
        self.addCleanup(auth_patch.stop)
        self.store()

    def store(self, code='synthetic-code'):
        self.assertEqual(capture(Store(self.pool), self.owner, code, 'synthetic-nonce', config=self.config,
                                 exchanger=lambda *args: 'synthetic-refresh'), {'status': 'stored'})

    def delete_auth(self, owner):
        # Separate connection proves no identity lock is held across HTTP.
        with self.fixture.connection() as conn:
            conn.execute("SET LOCAL lock_timeout='500ms'")
            deletion.lock_identity(conn, owner, exclusive=True)
            conn.execute('DELETE FROM auth.users WHERE id=%s', (owner,))

    def start(self):
        deletion.confirm(self.pool, self.owner)

    def job(self):
        return self.query('''SELECT phase,apple_state,failure_category,operator_attention,
            last_operation,attempt_count,apple_capture_uncertain FROM account_deletion_jobs WHERE auth_user_id=%s''',
            (self.owner,))[0]

    def test_complete_cleans_credentials_attempts_and_job(self):
        self.start()
        deletion.recover_one(self.pool, self.owner)
        self.assertEqual(deletion.status(self.pool, self.owner), {'status': 'completed'})
        for table in ('account_deletion_jobs', 'apple_credentials', 'apple_credential_attempts'):
            self.assertEqual(self.query(f'SELECT count(*) FROM {table} WHERE auth_user_id=%s', (self.owner,)), [(0,)])
        self.apple.assert_called_once()
        self.auth.assert_called_once()

    def test_transient_and_provider_failures_retry_without_auth_delete(self):
        self.start()
        for category in ('apple_revocation_timeout', 'apple_revocation_network_error', 'apple_revocation_provider_rejected'):
            self.apple.return_value = category
            deletion.recover_one(self.pool, self.owner)
            self.assertEqual(self.job()[1:3], ('pending', category))
            self.assertEqual(self.job()[3], category == 'apple_revocation_provider_rejected')
            self.auth.assert_not_called()
            self.assertEqual(self.query('SELECT count(*) FROM apple_credentials'), [(1,)])
        self.apple.return_value = 'apple_revocation_confirmed'
        deletion.recover_one(self.pool, self.owner)
        self.assertEqual(deletion.status(self.pool, self.owner), {'status': 'completed'})

    def test_invalid_config_and_decryption_recover(self):
        self.start()
        with patch.object(revocation.Config, 'load', side_effect=RuntimeError('PRIVATE_KEY')):
            deletion.recover_one(self.pool, self.owner)
        self.assertEqual(self.job()[2], 'apple_client_configuration_invalid')
        old = self.query('SELECT refresh_ciphertext FROM apple_credentials')[0][0]
        self.query("UPDATE apple_credentials SET refresh_ciphertext=%s", (b'corrupt',))
        deletion.recover_one(self.pool, self.owner)
        self.assertEqual(self.job()[2], 'apple_decryption_failed')
        self.apple.assert_not_called()
        self.auth.assert_not_called()
        self.query('UPDATE apple_credentials SET refresh_ciphertext=%s', (old,))
        deletion.recover_one(self.pool, self.owner)
        self.assertEqual(deletion.status(self.pool, self.owner), {'status': 'completed'})

    def test_missing_credential_manual_not_revoked(self):
        self.query('DELETE FROM apple_credentials')
        self.start()
        self.auth.side_effect = None
        deletion.recover_one(self.pool, self.owner)
        self.assertEqual(self.job()[1], 'manual_required')
        self.assertEqual(self.query('SELECT apple_resolution_reason FROM account_deletion_jobs'),
                         [('apple_credential_missing',)])
        self.apple.assert_not_called()
        self.assertEqual(self.query('SELECT apple_confirmed_at FROM account_deletion_jobs'), [(None,)])
        self.auth.side_effect = self.delete_auth
        deletion.recover_one(self.pool, self.owner)
        self.assertEqual(deletion.status(self.pool, self.owner), {'status': 'completed'})

    def test_generation_change_fails_closed(self):
        self.start()
        attempt = revocation.begin(self.pool, self.owner)
        revocation.prepare(self.pool, attempt)
        generation = self.query("INSERT INTO apple_credential_attempts(auth_user_id,code_digest,status) "
                                "VALUES(%s,%s,'stored') RETURNING generation", (self.owner, b'other'))[0][0]
        self.query('UPDATE apple_credentials SET generation=%s', (generation,))
        self.assertFalse(revocation.advance(self.pool, attempt))
        self.assertEqual(self.job()[2], 'apple_credential_mismatch')
        self.apple.assert_not_called()

    def test_manual_operator_resolution_requires_exact_observed_failure_and_confirmation(self):
        self.start()
        self.apple.return_value = 'apple_revocation_timeout'
        deletion.recover_one(self.pool, self.owner)
        ref = self.query('SELECT job_ref FROM account_deletion_jobs')[0][0]
        for category, arranged in (('apple_revocation_timeout', False),
                                   ('apple_decryption_failed', True), ('arbitrary', True)):
            self.assertEqual(self.query('SELECT resolve_apple_deletion_manually(%s,%s,%s)',
                                        (ref, category, arranged)), [(False,)])
        self.assertEqual(self.query('SELECT resolve_apple_deletion_manually(%s,%s,true)',
                                    (ref, 'apple_revocation_timeout')), [(True,)])
        self.assertEqual(self.job()[1:3], ('manual_required', 'apple_manual_operator_resolution'))
        deletion.recover_one(self.pool, self.owner)
        self.apple.assert_called_once()
        self.assertEqual(deletion.status(self.pool, self.owner), {'status': 'completed'})

    def test_manual_resolution_during_http_cannot_be_overwritten(self):
        self.start()
        self.apple.return_value = 'apple_revocation_timeout'
        deletion.recover_one(self.pool, self.owner)
        attempt = revocation.begin(self.pool, self.owner)
        ref = attempt.job

        def provider(*args):
            self.assertEqual(self.query('SELECT resolve_apple_deletion_manually(%s,%s,true)',
                                        (ref, 'apple_revocation_timeout')), [(True,)])
            return 'apple_revocation_provider_rejected'

        self.apple.side_effect = provider
        self.assertFalse(revocation.advance(self.pool, attempt))
        self.assertEqual(self.job()[1:3], ('manual_required', 'apple_manual_operator_resolution'))

    def test_confirmed_generation_cannot_change_before_auth_delete(self):
        self.start()
        attempt = revocation.begin(self.pool, self.owner)
        revocation.prepare(self.pool, attempt)
        self.assertTrue(revocation.advance(self.pool, attempt))
        generation = self.query("INSERT INTO apple_credential_attempts(auth_user_id,code_digest,status) "
                                "VALUES(%s,%s,'stored') RETURNING generation", (self.owner, b'other'))[0][0]
        self.query('UPDATE apple_credentials SET generation=%s', (generation,))
        deletion.recover_one(self.pool, self.owner)
        self.assertEqual(self.job()[2], 'apple_credential_mismatch')
        self.auth.assert_not_called()

    def test_identity_mismatch_never_contacts_apple(self):
        self.query("UPDATE auth_identities SET provider_id='different'")
        self.start()
        deletion.recover_one(self.pool, self.owner)
        self.assertEqual(self.job()[2], 'apple_credential_mismatch')
        self.apple.assert_not_called()
        self.auth.assert_not_called()

    def test_identity_mismatch_rechecked_until_corrected_then_retries_successfully(self):
        self.query("UPDATE auth_identities SET provider_id='different'")
        self.start()
        for _ in range(2):
            deletion.recover_one(self.pool, self.owner)
            self.assertEqual(self.job()[2], 'apple_credential_mismatch')
            self.apple.assert_not_called()
            self.auth.assert_not_called()
        self.query('UPDATE auth_identities SET provider_id=%s', (self.subject,))
        deletion.recover_one(self.pool, self.owner)
        self.apple.assert_called_once()
        self.assertEqual(deletion.status(self.pool, self.owner), {'status': 'completed'})

    def test_generation_correction_does_not_rebind_or_remain_stuck(self):
        self.start()
        attempt = revocation.begin(self.pool, self.owner)
        revocation.prepare(self.pool, attempt)
        original = self.query('SELECT generation FROM apple_credentials')[0][0]
        changed = self.query("INSERT INTO apple_credential_attempts(auth_user_id,code_digest,status) "
                             "VALUES(%s,%s,'stored') RETURNING generation", (self.owner, b'other'))[0][0]
        self.query('UPDATE apple_credentials SET generation=%s', (changed,))
        self.assertFalse(revocation.advance(self.pool, attempt))
        self.assertEqual(self.query('SELECT apple_generation FROM account_deletion_jobs'), [(original,)])
        self.apple.assert_not_called()
        self.query('UPDATE apple_credentials SET generation=%s', (original,))
        deletion.recover_one(self.pool, self.owner)
        self.assertEqual(deletion.status(self.pool, self.owner), {'status': 'completed'})

    def test_historical_mismatch_does_not_bypass_new_identity_mismatch(self):
        self.start()
        attempt = revocation.begin(self.pool, self.owner)
        revocation.prepare(self.pool, attempt)
        self.query("UPDATE auth_identities SET identity_data='{}'")
        self.assertFalse(revocation.advance(self.pool, attempt))
        self.apple.assert_not_called()
        self.assertEqual(self.job()[2], 'apple_credential_mismatch')
        self.query('UPDATE auth_identities SET identity_data=%s', (json.dumps({'sub': self.subject}),))
        self.assertTrue(revocation.advance(self.pool, attempt))

    def test_progress_notes_preserve_failure_and_attention_until_a_result(self):
        self.start()
        attempt = revocation.begin(self.pool, self.owner)
        revocation.prepare(self.pool, attempt)
        revocation.note(self.pool, attempt, 'apple_revoke', 'apple_decryption_failed')
        revocation.note(self.pool, attempt, 'application_cleanup')
        self.assertEqual(self.job()[2:4], ('apple_decryption_failed', True))
        self.assertTrue(revocation.advance(self.pool, attempt))
        self.assertEqual(self.job()[2:4], ('apple_revocation_confirmed', False))

    def test_overlapping_successes_revoke_same_token_without_regressing_terminal_state(self):
        self.start()
        first = revocation.begin(self.pool, self.owner)
        revocation.prepare(self.pool, first)
        entered, release = threading.Event(), threading.Event()

        def provider(*args):
            if threading.current_thread().name.startswith('older'):
                entered.set()
                self.assertTrue(release.wait(5))
            return 'apple_revocation_confirmed'

        self.apple.side_effect = provider
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='older') as executor:
            pending = executor.submit(revocation.advance, self.pool, first)
            try:
                self.assertTrue(entered.wait(5))
                second = revocation.begin(self.pool, self.owner)
                self.assertTrue(revocation.advance(self.pool, second))
            finally:
                release.set()
            self.assertFalse(pending.result())  # stale result must not write
        self.assertEqual(self.apple.call_count, 2)
        self.assertEqual(self.apple.call_args_list[0].args, self.apple.call_args_list[1].args)
        self.assertEqual(self.job()[1:3], ('revoked', 'apple_revocation_confirmed'))
        deletion.recover_one(self.pool, self.owner)
        self.assertEqual(self.apple.call_count, 2)
        self.assertEqual(deletion.status(self.pool, self.owner), {'status': 'completed'})

    def test_missing_auth_does_not_finalize_unresolved_apple(self):
        self.start()
        self.apple.return_value = 'apple_revocation_timeout'
        deletion.recover_one(self.pool, self.owner)
        self.query('DELETE FROM auth_users WHERE id=%s', (self.owner,))
        attempt = revocation.begin(self.pool, self.owner)
        self.assertFalse(revocation.finalize(self.pool, attempt))
        self.assertEqual(deletion.status(self.pool, self.owner), {'status': 'auth_pending'})
        self.assertEqual(self.query('SELECT count(*) FROM apple_credentials'), [(1,)])
        self.apple.return_value = 'apple_revocation_confirmed'
        deletion.recover_one(self.pool, self.owner)
        self.assertEqual(deletion.status(self.pool, self.owner), {'status': 'completed'})

    def test_restart_after_claim_and_lost_response(self):
        self.start()
        self.apple.return_value = 'apple_revocation_timeout'
        deletion.run_due(self.pool)
        self.assertEqual(self.job()[1], 'pending')
        deletion.run_due(self.pool)
        self.apple.assert_called_once()
        self.query("UPDATE account_deletion_jobs SET next_attempt_at=created_at")
        self.apple.return_value = 'apple_revocation_confirmed'  # already-revoked token returns 200
        deletion.run_due(self.pool)
        self.assertEqual(deletion.status(self.pool, self.owner), {'status': 'completed'})

    def test_crash_before_http_and_after_success_before_commit(self):
        self.start()
        attempt = revocation.begin(self.pool, self.owner)
        revocation.prepare(self.pool, attempt)  # process can disappear here
        self.apple.assert_not_called()
        original = revocation.transaction

        @contextmanager
        def failing_result(pool, owner):
            with original(pool, owner) as conn:
                yield conn
                if self.apple.call_count:
                    raise RuntimeError('synthetic crash before commit')

        with patch.object(revocation, 'transaction', failing_result):
            with self.assertRaises(RuntimeError):
                revocation.advance(self.pool, attempt)
        self.assertEqual(self.job()[1], 'pending')
        deletion.recover_one(self.pool, self.owner)
        self.assertEqual(self.apple.call_count, 2)
        self.assertEqual(deletion.status(self.pool, self.owner), {'status': 'completed'})

    def test_two_workers_stale_failure_cannot_regress_success(self):
        self.start()
        first = revocation.begin(self.pool, self.owner)
        revocation.prepare(self.pool, first)
        entered, release = threading.Event(), threading.Event()

        def provider(*args):
            if threading.current_thread().name.startswith('older'):
                entered.set()
                self.assertTrue(release.wait(5))
                return 'apple_revocation_timeout'
            return 'apple_revocation_confirmed'

        self.apple.side_effect = provider
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='older') as executor:
            pending = executor.submit(revocation.advance, self.pool, first)
            self.assertTrue(entered.wait(5))
            second = revocation.begin(self.pool, self.owner)
            self.assertTrue(revocation.advance(self.pool, second))
            release.set()
            self.assertFalse(pending.result())
        self.assertEqual(self.job()[1:3], ('revoked', 'apple_revocation_confirmed'))

    def test_capture_in_flight_is_explicit_manual_uncertainty(self):
        entered, release = threading.Event(), threading.Event()

        def exchange(*args):
            entered.set()
            self.assertTrue(release.wait(5))
            return 'issued-but-not-persisted'

        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(capture, Store(self.pool), self.owner, 'second-code', 'nonce',
                                      config=self.config, exchanger=exchange)
            self.assertTrue(entered.wait(5))
            self.start()
            self.auth.side_effect = None  # retain job to inspect the resolution
            deletion.recover_one(self.pool, self.owner)
            self.assertEqual(self.job()[1], 'manual_required')
            self.assertTrue(self.job()[6])
            self.assertIsNotNone(self.query('SELECT apple_confirmed_at FROM account_deletion_jobs')[0][0])
            release.set()
            self.assertEqual(pending.result(), {'status': 'unavailable'})

    def test_auth_failure_does_not_repeat_confirmed_apple_step(self):
        self.start()
        self.auth.side_effect = None
        deletion.recover_one(self.pool, self.owner)
        self.assertEqual(self.job()[1:3], ('revoked', 'supabase_auth_deletion_failed'))
        self.auth.side_effect = self.delete_auth
        deletion.recover_one(self.pool, self.owner)
        self.apple.assert_called_once()
        self.assertEqual(deletion.status(self.pool, self.owner), {'status': 'completed'})

    def test_auth_already_absent_still_revokes(self):
        self.start()
        self.query('DELETE FROM auth_users WHERE id=%s', (self.owner,))
        deletion.recover_one(self.pool, self.owner)
        self.apple.assert_called_once()
        self.auth.assert_not_called()
        self.assertEqual(deletion.status(self.pool, self.owner), {'status': 'completed'})

    def test_auth_verification_failure_retains_safe_diagnostic(self):
        self.start()
        original = revocation.transaction
        apple = self.apple

        @contextmanager
        def failure(pool, owner):
            with original(pool, owner) as conn:
                class Proxy:
                    def execute(self, sql, args=None):
                        if apple.call_count and sql == 'SELECT 1 FROM auth.users WHERE id=%s':
                            raise RuntimeError('PRIVATE_DATABASE_ERROR')
                        return conn.execute(sql, args)
                yield Proxy()

        with patch.object(revocation, 'transaction', failure):
            with self.assertRaises(RuntimeError):
                deletion.recover_one(self.pool, self.owner)
        self.assertEqual(self.job()[2], 'supabase_auth_verification_failed')
        self.auth.assert_not_called()
        deletion.recover_one(self.pool, self.owner)
        self.apple.assert_called_once()

    def test_capture_cannot_finish_after_final_cleanup(self):
        store = Store(self.pool)
        generation, subject, _ = store.begin(self.owner, b'additional-code-digest')
        self.start()
        deletion.recover_one(self.pool, self.owner)
        from deletion_gate import IdentityUnavailable
        with self.assertRaises(IdentityUnavailable):
            store.finish(self.owner, generation, subject, self.config,
                         self.config.seal('late-token', self.owner, subject, generation))
        self.assertEqual(self.query('SELECT count(*) FROM apple_credentials'), [(0,)])

    def test_finalization_rollback_retains_all_recovery_material(self):
        self.start()
        original = revocation.transaction

        @contextmanager
        def failing_final(pool, owner):
            with original(pool, owner) as conn:
                class Proxy:
                    def execute(self, sql, args=None):
                        if sql.startswith('DELETE FROM apple_credential_attempts'):
                            raise RuntimeError('synthetic cleanup failure')
                        return conn.execute(sql, args)
                yield Proxy()

        with patch.object(revocation, 'transaction', failing_final):
            with self.assertRaises(RuntimeError):
                deletion.recover_one(self.pool, self.owner)
        self.assertEqual(self.job()[2], 'deletion_finalization_failed')
        self.assertEqual(self.query('SELECT count(*) FROM apple_credentials'), [(1,)])
        self.assertEqual(self.query('SELECT count(*) FROM apple_credential_attempts'), [(1,)])
        deletion.recover_one(self.pool, self.owner)
        self.apple.assert_called_once()

    def test_stuck_job_does_not_block_another_user(self):
        other = self.fixture.person()
        self.start()
        deletion.confirm(self.pool, other[0])
        self.apple.return_value = 'apple_revocation_timeout'
        deletion.run_due(self.pool)
        self.assertEqual(deletion.status(self.pool, self.owner), {'status': 'auth_pending'})
        self.assertEqual(deletion.status(self.pool, other[0]), {'status': 'completed'})

    def test_exception_isolated_and_diagnostic_is_safe(self):
        other = self.fixture.person()
        self.start()
        deletion.confirm(self.pool, other[0])
        self.apple.side_effect = RuntimeError('PRIVATE_PROVIDER_BODY')
        with self.assertLogs(level='INFO') as logs:
            deletion.run_due(self.pool)
        self.assertNotIn('PRIVATE_PROVIDER_BODY', str(logs.output))
        self.assertNotIn(self.owner, str(logs.output))
        self.assertNotIn('synthetic-refresh', str(logs.output))
        self.assertEqual(deletion.status(self.pool, other[0]), {'status': 'completed'})


if __name__ == '__main__':
    unittest.main()


class ProductionWorkflowTests(WorkflowTests):
    production = True
