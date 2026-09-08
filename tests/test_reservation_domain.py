"""Domain parity with real service/transaction helpers and an in-memory SQL double."""
from datetime import datetime, timedelta
import json
import unittest
from unittest.mock import patch

import reservation_rules as rules
from identity import CurrentUser
from tests.test_database_atomic_creation import database, RecordingContext
from tests.test_chat_service import load_chat_service
from tests.test_reservation_service import load_service


NOW = datetime(2030, 1, 10, 12)


class Cursor:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self, start="2030-01-10T10:00:00", end="2030-01-12T14:00:00"):
        self.row = (1, start, end)
        self.action = None
        self.mutations = []
        self.conflict_args = None
        self.conflict = None
        self.sql = []
        self.lease = True

    def transaction(self):
        return RecordingContext()

    def execute(self, sql, params=()):
        sql = ' '.join(sql.split())
        self.sql.append(sql)
        if 'FROM chat_requests' in sql:
            return Cursor((11,) if self.lease else None)
        if 'SELECT action_type, result' in sql:
            return Cursor(self.action)
        if 'INSERT INTO chat_tool_actions' in sql:
            self.action_type = params[1]
            return Cursor((91,))
        if 'UPDATE chat_tool_actions' in sql:
            self.action = (self.action_type, json.loads(params[0]))
            return Cursor()
        if 'pg_advisory_xact_lock' in sql:
            return Cursor()
        if 'SELECT family_id' in sql:
            return Cursor((42,))
        if 'SELECT r.id, r.user_id, r.start_time, r.end_time' in sql:
            self.conflict_args = params
            _, end, start, *_ = params
            overlaps = self.conflict and self.conflict[0] < end and self.conflict[1] > start
            return Cursor((2, 7, *self.conflict) if overlaps else None)
        if 'SELECT r.id' in sql and 'FROM reservations AS r' in sql:
            if 'r.start_time = %s' in sql:
                user, family, start, end, boundary = params
                ok = self.row and (user, family) == (7, 42) and self.row[1:] == (start, end)
                ok = ok and self.row[2] > boundary
            else:
                ok = self.row and params == (1, 7, 42)
            return Cursor(self.row if ok else None)
        if 'INSERT INTO reservations' in sql:
            self.mutations.append(('create', params))
            return Cursor((2,))
        if 'UPDATE reservations AS r' in sql:
            self.mutations.append(('update' if 'SET start_time' in sql else 'cancel', params))
            return Cursor((1,))
        raise AssertionError(sql)


class CanonicalRulesTests(unittest.TestCase):
    def test_invalid_create_values(self):
        for start, end in [(None, None), (123, 456), ({}, []), ('bad', 'worse'),
                           ('2030-01-11T11:00:00', '2030-01-11T10:00:00'),
                           ('2030-01-11T10:00:00', '2030-01-11T10:00:00'),
                           ('2030-01-11T10:00:00.1', '2030-01-11T10:00:00.9'),
                           ('2020-01-01T10:00:00', '2030-01-12T10:00:00')]:
            with self.subTest(start=start, end=end), self.assertRaises(rules.ReservationValidationError):
                rules.validate_create(start, end, NOW)

    def test_multiday_offset_canonicalization(self):
        self.assertEqual(rules.validate_create('2030-01-11T16:00:00Z', '2030-01-13T12:00:00Z', NOW),
                         ('2030-01-11T18:00:00', '2030-01-13T14:00:00'))

    def test_ongoing_retained_start_shortened_or_extended(self):
        for end in ('2030-01-10T13:00:00', '2030-01-13T14:00:00'):
            self.assertEqual(rules.validate_update('2030-01-10T08:00:00Z', end,
                                                  '2030-01-10T10:00:00', '2030-01-12T14:00:00', NOW),
                             ('2030-01-10T10:00:00', end))

    def test_ongoing_cannot_backdate_or_end_now(self):
        for start, end in [('2030-01-10T09:00:00', '2030-01-12T14:00:00'),
                           ('2030-01-10T10:00:00', '2030-01-10T12:00:00')]:
            with self.assertRaises(rules.ReservationValidationError):
                rules.validate_update(start, end, '2030-01-10T10:00:00', '2030-01-12T14:00:00', NOW)


class ReservationParityTests(unittest.TestCase):
    def setUp(self):
        self.conn = Connection()
        self.user = CurrentUser(user_id=7, name='Test', family_id=42)
        self.chat = load_chat_service()
        self.service = load_service()
        self.chat.pool.connection.return_value = RecordingContext(self.conn)
        for name in ('_create_reservation_on_connection', '_update_reservation_on_connection',
                     '_cancel_reservation_on_connection'):
            setattr(self.chat, name, getattr(database, name))
        for name in ('create_current_user_reservation', 'update_current_user_reservation',
                     'cancel_current_user_reservation'):
            setattr(self.service, name, getattr(database, name))
        for target, attr, value in [(database, 'reservation_now', NOW), (self.service, '_local_now', NOW)]:
            p = patch.object(target, attr, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(database, 'pool')
        pool = p.start()
        pool.connection.return_value = RecordingContext(self.conn)
        self.addCleanup(p.stop)

    def action(self, name, args):
        return self.chat._execute_mutation(11, 'lease', self.user, name, args)['result']

    def test_chat_invalid_shapes_are_persisted_and_do_not_mutate(self):
        for args in (None, [], {}, {'start_time': 42, 'end_time': []},
                     {'start_time': 'bad', 'end_time': 'bad'},
                     {'start_time': '\u0000', 'end_time': '\ud800'}):
            with self.subTest(args=args):
                self.conn.action = None
                result = self.action('create_reservation', args)
                self.assertFalse(result['success'])
                self.assertEqual(self.conn.action[1], result)
                self.assertEqual(self.conn.mutations, [])

    def test_invalid_reservation_id_is_business_failure(self):
        for value in (None, True, '1', -1):
            self.conn.action = None
            result = self.action('cancel_reservation', {'reservation_id': value})
            self.assertEqual(result['code'], 'RESERVATION_NOT_FOUND_OR_UNAVAILABLE')
        self.assertEqual(self.conn.mutations, [])

    def test_create_parity_multiday(self):
        start, end = '2030-01-11T16:00:00Z', '2030-01-13T12:00:00Z'
        direct = self.service.create_reservation_for_current_user(self.user, start, end)
        chat = self.action('create_reservation', {'start_time': start, 'end_time': end})
        self.assertTrue(chat['success'])
        self.assertEqual((direct['start_time'], direct['end_time']), (chat['start_time'], chat['end_time']))

    def test_invalid_intervals_rejected_by_both_paths(self):
        for start, end in [('bad', 'bad'), ('2020-01-01T10:00:00', '2020-01-01T11:00:00'),
                           ('2030-01-11T11:00:00', '2030-01-11T10:00:00'),
                           ('2030-01-11T10:00:00.1', '2030-01-11T10:00:00.9')]:
            self.conn.action = None
            with self.assertRaises(self.service.ReservationCenterError) as raised:
                self.service.create_reservation_for_current_user(self.user, start, end)
            result = self.action('create_reservation', {'start_time': start, 'end_time': end})
            self.assertEqual(result['code'], raised.exception.code)
        self.assertEqual(self.conn.mutations, [])

    def test_multiday_equivalent_offset_conflict(self):
        self.conn.conflict = ('2030-01-11T23:00:00', '2030-01-13T10:00:00')
        args = {'start_time': '2030-01-12T00:00:00Z', 'end_time': '2030-01-12T01:00:00Z'}
        result = self.action('create_reservation', args)
        self.assertEqual(result['code'], 'RESERVATION_CONFLICT')
        self.assertEqual(self.conn.conflict_args[:3], (42, '2030-01-12T03:00:00', '2030-01-12T02:00:00'))
        self.assertEqual(self.conn.mutations, [])

    def test_ongoing_update_both_paths(self):
        for end in ('2030-01-10T13:00:00', '2030-01-13T14:00:00'):
            self.conn.action = None
            direct = self.service.update_reservation_for_current_user(
                self.user, *self.conn.row[1:], '2030-01-10T08:00:00Z', end)
            chat = self.action('update_reservation', {'reservation_id': 1,
                'start_time': '2030-01-10T08:00:00Z', 'end_time': end})
            self.assertTrue(chat['success'])
            self.assertEqual(direct['start_time'], '2030-01-10T10:00:00')

    def test_expired_and_boundary_targets_both_paths(self):
        for end in ('2030-01-10T11:00:00', '2030-01-10T12:00:00'):
            self.conn.row = (1, '2030-01-10T10:00:00', end)
            for action in ('update_reservation', 'cancel_reservation'):
                self.conn.action = None
                result = self.action(action, {'reservation_id': 1,
                    'start_time': '2030-01-11T10:00:00', 'end_time': '2030-01-12T10:00:00'})
                self.assertEqual(result['code'], 'RESERVATION_NOT_FOUND_OR_UNAVAILABLE')
                with self.assertRaises(self.service.ReservationCenterError) as raised:
                    if action == 'update_reservation':
                        self.service.update_reservation_for_current_user(self.user, *self.conn.row[1:],
                            '2030-01-11T10:00:00', '2030-01-12T10:00:00')
                    else:
                        self.service.cancel_reservation_for_current_user(self.user, *self.conn.row[1:])
                self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(self.conn.mutations, [])

    def test_ongoing_cancel_both_paths(self):
        self.assertEqual(self.service.cancel_reservation_for_current_user(self.user, *self.conn.row[1:]),
                         {'cancelled': True})
        self.assertTrue(self.action('cancel_reservation', {'reservation_id': 1})['success'])

    def test_replay_after_time_advances_does_not_validate(self):
        result = self.action('create_reservation', {'start_time': 'bad', 'end_time': 'bad'})
        with patch.object(database, 'reservation_now', side_effect=AssertionError('revalidated')):
            self.assertEqual(self.action('create_reservation', {}), result)
        self.assertEqual(self.conn.mutations, [])
        self.assertIn('התאריך', self.chat._fallback_for_action({'action_type': 'create_reservation', 'result': result}))

    def test_success_replay_after_expiration_does_not_mutate_again(self):
        result = self.action('create_reservation', {'start_time': '2030-01-11T10:00:00', 'end_time': '2030-01-12T10:00:00'})
        with patch.object(database, 'reservation_now', return_value=NOW + timedelta(days=99)):
            self.assertEqual(self.action('create_reservation', {}), result)
        self.assertEqual(len(self.conn.mutations), 1)

    def test_stale_worker_fenced_even_for_invalid_action(self):
        self.conn.lease = False
        with self.assertRaises(self.chat.ChatLeaseLostError):
            self.action('create_reservation', {})
        self.assertIsNone(self.conn.action)
        self.assertEqual(self.conn.mutations, [])

    def test_ongoing_invalid_replacements_both_paths(self):
        for start, end in [('2030-01-10T09:00:00', '2030-01-12T14:00:00'),
                           ('2030-01-10T10:00:00', '2030-01-10T12:00:00'),
                           ('bad', 'bad')]:
            self.conn.action = None
            with self.assertRaises(self.service.ReservationCenterError) as raised:
                self.service.update_reservation_for_current_user(self.user, *self.conn.row[1:], start, end)
            result = self.action('update_reservation', {'reservation_id': 1, 'start_time': start, 'end_time': end})
            self.assertEqual(result['code'], raised.exception.code)
        self.assertEqual(self.conn.mutations, [])

    def test_upcoming_update_and_cancel(self):
        self.conn.row = (1, '2030-01-11T10:00:00', '2030-01-12T14:00:00')
        updated = self.action('update_reservation', {'reservation_id': 1,
            'start_time': '2030-01-11T12:00:00', 'end_time': '2030-01-13T14:00:00'})
        self.assertTrue(updated['success'])
        self.conn.action = None
        self.assertTrue(self.action('cancel_reservation', {'reservation_id': 1})['success'])

    def test_update_offset_conflict_uses_canonical_values(self):
        self.conn.conflict = ('2030-01-11T23:00:00', '2030-01-13T10:00:00')
        result = self.action('update_reservation', {'reservation_id': 1,
            'start_time': '2030-01-12T00:00:00Z', 'end_time': '2030-01-12T01:00:00Z'})
        self.assertEqual(result['code'], 'RESERVATION_CONFLICT')
        self.assertEqual(self.conn.conflict_args, (42, '2030-01-12T03:00:00', '2030-01-12T02:00:00', 1))
        self.assertEqual(self.conn.mutations, [])

    def test_gemini_failure_after_validation_result_uses_persisted_fallback(self):
        from uuid import uuid4
        def generate(_message, _user, _history, dispatch, **_kwargs):
            dispatch('create_reservation', {})
            raise RuntimeError('synthetic failure after action commit')
        def completed(_id):
            if self.conn.action:
                return {'action_type': self.conn.action[0], 'result': self.conn.action[1]}
            return None
        with patch.object(self.chat, '_claim_request', return_value={'outcome': 'claimed', 'id': 11}), \
             patch.object(self.chat, '_renew_lease'), \
             patch.object(self.chat, '_load_model_history', return_value=[]), \
             patch.object(self.chat, '_get_completed_action', side_effect=completed), \
             patch.object(self.chat, 'generate_agent_response', side_effect=generate), \
             patch.object(self.chat, '_finalize_request', side_effect=lambda _id, _lease, _user, response: response):
            response = self.chat.process_chat_message(uuid4(), 'test', self.user)
        self.assertEqual(response['status'], 'completed')
        self.assertIn('התאריך', response['assistant_message']['content'])
        self.assertFalse(self.conn.action[1]['success'])
        self.assertEqual(self.conn.mutations, [])
