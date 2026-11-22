"""No-build checks of the actual SQLite DDL and Backend request contract.

No application/Backend imports, persistent databases or network requests.
Swift behavioral checks live in VehicleSyncChecks.swift and require a test runner.
"""
import ast
from pathlib import Path
import re
import sqlite3
import unittest

ROOT = Path(__file__).resolve().parents[2]
QUEUE = (ROOT / 'ios/Sources/FamilyCarAgent/OfflineEvents/VehicleEventQueue.swift').read_text(encoding='utf-8')


class RecoverySchemaChecks(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('CREATE TABLE events(id TEXT PRIMARY KEY)')
        self.db.execute("INSERT INTO events VALUES('return-1')")
        for ddl in re.findall(r'try execute\("(CREATE [^"\n]*return_recover[^"\n]*)"\)', QUEUE):
            self.db.execute(ddl)
        self.db.commit()

    def add(self, key='attempt-1', state='preparing', event='return-1'):
        self.db.execute('INSERT INTO return_recoveries(id,event,payload,state) VALUES(?,?,?,?)',
                        (key, event, '{"immutable":"original-and-verification"}', state))

    def test_only_one_active_attempt_per_event(self):
        self.add()
        for state in ('preparing', 'registered', 'awaitingAuthentication'):
            with self.assertRaises(sqlite3.IntegrityError):
                self.add('attempt-2', state)

    def test_new_attempt_keeps_rejected_evidence(self):
        self.add()
        self.db.execute("UPDATE return_recoveries SET state='blocked' WHERE id='attempt-1'")
        self.add('attempt-2')
        self.assertEqual(self.db.execute('SELECT count(*) FROM return_recoveries').fetchone(), (2,))

    def test_original_and_verification_payload_cannot_be_rewritten(self):
        self.add()
        for field in ('payload', 'event', 'id'):
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(f'UPDATE return_recoveries SET {field}=?', ('replacement',))

    def test_attempt_requires_original_event(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.add(event='nonexistent')

    def test_interrupted_transaction_does_not_create_partial_attempt(self):
        self.add()
        self.db.rollback()
        self.assertEqual(self.db.execute('SELECT count(*) FROM return_recoveries').fetchone(), (0,))

    def test_schema_reopen_preserves_payload(self):
        self.add()
        self.db.commit()
        for ddl in re.findall(r'try execute\("(CREATE [^"\n]*return_recover[^"\n]*)"\)', QUEUE):
            self.db.execute(ddl)
        self.assertEqual(self.db.execute('SELECT id,payload FROM return_recoveries').fetchone(),
                         ('attempt-1', '{"immutable":"original-and-verification"}'))

    def test_wire_keys_match_actual_backend_contract(self):
        module = ast.parse((ROOT / 'backend/device_api.py').read_text(encoding='utf-8'))
        classes = {node.name: {field.target.id for field in node.body if isinstance(field, ast.AnnAssign)}
                   for node in module.body if isinstance(node, ast.ClassDef)}
        wire = QUEUE.split('enum VehicleEventWire {', 1)[1].split('/// One connection', 1)[0]
        keys = set(re.findall(r'"([a-z_]+)"(?:\s*:|\])', wire))
        self.assertEqual(keys, classes['Take'] | classes['Return'] | classes['ReturnVerification'] | classes['ReturnRecovery'])


if __name__ == '__main__':
    unittest.main()
