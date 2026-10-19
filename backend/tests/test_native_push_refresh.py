"""Offline NP-01 contract tests; no credentials, network or database required."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from deletion_gate import IdentityUnavailable
from identity import CurrentUser
from native_push_fcm import Fcm
from native_push_security import token_context
import native_push_worker as worker
import vehicle_lifecycle
from vehicle_identity import VehicleIdentityError
from tests.test_native_push import CONFIG


class RefreshTests(unittest.TestCase):
    def pool(self, row):
        conn = Mock()
        conn.execute.return_value.fetchone.return_value = row
        @contextmanager
        def connection():
            yield conn
        pool = Mock()
        pool.connection = connection
        return pool, conn

    def payload(self):
        installation = uuid4()
        expiry = datetime.now(timezone.utc) + timedelta(minutes=2)
        row = (CONFIG.seal('test-routing-token', token_context(2, installation)),
               CONFIG.key_id, 'android', 2, installation, expiry)
        pool, conn = self.pool(row)
        return worker.delivery_payload(pool, CONFIG, (uuid4(), uuid4())), conn

    def test_exact_wire_data_has_no_event_or_authorization_fields(self):
        payload, _ = self.payload()
        transport = Mock()
        transport.post.return_value.status_code = 200
        provider = Fcm(CONFIG, transport=transport)
        provider._token, provider._until = 'mock-access', float('inf')
        provider.send(payload[0], payload[1], expires_at=payload[2], platform=payload[3])
        message = transport.post.call_args.kwargs['json']['message']
        self.assertEqual(message['data'], {'kind': 'refresh', 'version': '1'})
        self.assertNotIn('notification', message)
        self.assertGreater(int(message['android']['ttl'][:-1]), 0)

    def test_rejected_authorization_never_decrypts_or_prepares_payload(self):
        pool, conn = self.pool(None)
        config = Mock(project=CONFIG.project)
        self.assertIsNone(worker.delivery_payload(pool, config, (uuid4(), uuid4())))
        config.open.assert_not_called()
        query = conn.execute.call_args.args[0]
        for guard in ('i.generation=d.installation_generation', "i.status='active'",
                      'u.family_id=e.family_id', 'actor.family_id=e.family_id',
                      'account_deletion_jobs', 'd.lease_until>clock_timestamp()',
                      'e.expires_at>clock_timestamp()'):
            self.assertIn(guard, query)

    def test_revocation_after_read_cannot_change_hint_into_event_metadata(self):
        payload, _ = self.payload()
        pool, _ = self.pool(None)
        provider = Mock()
        revoked = []
        def read_then_revoke(*args):
            revoked.append(True)  # Boundary after authorized read, before send.
            return payload
        def send(token, data, **kwargs):
            self.assertEqual(revoked, [True])
            self.assertEqual(data, {'kind': 'refresh', 'version': '1'})
            return worker.Result('accepted')
        provider.send.side_effect = send
        with patch.object(worker, 'challenge_pass'), patch.object(worker, 'claim_delivery', return_value=(uuid4(), uuid4())), \
                patch.object(worker, 'delivery_payload', side_effect=read_then_revoke), patch.object(worker, 'finish_delivery'):
            worker.run_once(pool, CONFIG, provider)
        provider.send.assert_called_once()

    def test_stale_installation_is_not_sent(self):
        pool, _ = self.pool(None)
        provider = Mock()
        with patch.object(worker, 'challenge_pass'), patch.object(worker, 'claim_delivery', return_value=(uuid4(), uuid4())), \
                patch.object(worker, 'finish_delivery') as finish:
            worker.run_once(pool, CONFIG, provider)
        provider.send.assert_not_called()
        self.assertEqual(finish.call_args.args[2].code, 'identity_unavailable')

    def test_current_vehicle_read_rejects_changed_family_or_account(self):
        # Exercise the actual shared scope used by GET /api/vehicles, with a
        # database double rejecting the old identity tuple. No fake loaded data.
        user = CurrentUser(2, 'Test', 10, auth_user_id=str(uuid4()))
        for reason in ('family changed', 'account switched'):
            with self.subTest(reason=reason):
                conn = Mock()
                @contextmanager
                def transaction():
                    yield
                conn.transaction = transaction
                conn.execute.side_effect = [Mock(), Mock(fetchone=lambda: (10,)), Mock(fetchone=lambda: None)]
                with patch.object(vehicle_lifecycle, 'require_auth'), self.assertRaises(VehicleIdentityError):
                    with vehicle_lifecycle._scope(conn, user):
                        self.fail('Stale identity must not reach vehicle data reads')
                self.assertEqual(conn.execute.call_args.args[1], (2, 10, user.auth_user_id))

    def test_deleted_identity_cannot_enter_vehicle_read_scope(self):
        conn = Mock()
        @contextmanager
        def transaction():
            yield
        conn.transaction = transaction
        with patch.object(vehicle_lifecycle, 'require_auth', side_effect=IdentityUnavailable), self.assertRaises(IdentityUnavailable):
            with vehicle_lifecycle._scope(conn, CurrentUser(2, 'Test', 10, auth_user_id=str(uuid4()))):
                self.fail('Deleted identity must not reach vehicle data reads')
        conn.execute.assert_not_called()
