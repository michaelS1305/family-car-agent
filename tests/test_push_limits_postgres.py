"""Real locking tests using the existing isolated, local-only fixture."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor

from tests import test_account_deletion as fixture
from push_security import PushSubscriptionLimitError


@unittest.skipUnless(os.getenv('GEMINI_TEST_DATABASE_URL'), 'local PostgreSQL not configured')
class PushLimitsPostgresTests(unittest.TestCase):
    connection = fixture.AccountDeletionPostgresTests.connection
    drop_schema = fixture.AccountDeletionPostgresTests.drop_schema
    query = fixture.AccountDeletionPostgresTests.query
    person = fixture.AccountDeletionPostgresTests.person

    def setUp(self):
        fixture.AccountDeletionPostgresTests.setUp(self)
        self.query('''ALTER TABLE push_subscriptions
          ADD COLUMN id serial PRIMARY KEY,
          ADD COLUMN endpoint text UNIQUE,
          ADD COLUMN p256dh text,
          ADD COLUMN auth text,
          ADD COLUMN expiration_time timestamptz,
          ADD COLUMN updated_at timestamptz DEFAULT NOW()''')

    def register(self, uid, number):
        return self.database.upsert_push_subscription(uid, f'https://fcm.googleapis.com/wp/{uid}-{number}', 'p', 'a')

    def test_concurrent_cap_updates_and_independent_users(self):
        uid = self.creator[1]
        def attempt(number):
            try:
                self.register(uid, number)
                return True
            except PushSubscriptionLimitError:
                return False
        with ThreadPoolExecutor(max_workers=8) as executor:
            self.assertEqual(sum(executor.map(attempt, range(8))), 5)
        self.assertEqual(self.query('SELECT count(*) FROM push_subscriptions'), [(5,)])
        endpoint = self.query('SELECT endpoint FROM push_subscriptions LIMIT 1')[0][0]
        self.database.upsert_push_subscription(uid, endpoint, 'updated', 'a')
        other = self.person(self.family)[1]
        for number in range(5):
            self.register(other, number)
        self.assertEqual(self.query('SELECT count(*) FROM push_subscriptions'), [(10,)])

    def test_legacy_excess_is_bounded_and_each_member_gets_first_device(self):
        members = [self.person(self.family)[1] for _ in range(12)]
        outsider = self.person()[1]
        for uid in [*members, outsider, self.creator[1]]:
            for number in range(8):
                self.query('INSERT INTO push_subscriptions(user_id,endpoint,p256dh,auth) VALUES(%s,%s,\'p\',\'a\')',
                           (uid, f'https://fcm.googleapis.com/wp/{uid}-{number}'))
        rows = self.database.get_family_push_subscriptions(self.family, self.creator[1], 123)
        self.assertEqual(len(rows), 50)
        owners = [int(row['endpoint'].rsplit('/', 1)[1].split('-')[0]) for row in rows]
        self.assertEqual(set(owners[:12]), set(members))
        self.assertTrue(all(owners.count(uid) <= 5 for uid in members))
        self.assertNotIn(outsider, owners)
        self.assertNotIn(self.creator[1], owners)
        self.assertEqual(self.query('SELECT count(*) FROM push_subscriptions'), [(112,)])

    def test_delayed_cleanup_cannot_remove_rekeyed_same_endpoint(self):
        import hashlib
        uid = self.creator[1]
        self.register(uid, 0)
        endpoint = f'https://fcm.googleapis.com/wp/{uid}-0'
        old_generation = hashlib.sha256(f'{endpoint}\np\na'.encode()).hexdigest()
        self.database.upsert_push_subscription(uid, endpoint, 'new-key', 'new-auth')
        self.database.remove_push_subscription(uid, endpoint, old_generation)
        self.assertEqual(self.query('SELECT count(*) FROM push_subscriptions'), [(1,)])
        generation = hashlib.sha256(f'{endpoint}\nnew-key\nnew-auth'.encode()).hexdigest()
        self.database.remove_push_subscription(uid, endpoint, generation)
        self.assertEqual(self.query('SELECT count(*) FROM push_subscriptions'), [(0,)])
