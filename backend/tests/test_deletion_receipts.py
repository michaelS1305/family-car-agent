import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
import unittest
from unittest.mock import patch
from uuid import uuid4
import deletion_receipts as receipts
import apple_revocation
from tests.test_account_deletion import AccountDeletionPostgresTests
from tests.test_account_deletion_api import DeletionApiTests


def secret():
    return base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')


class ReceiptUnitTests(unittest.TestCase):
    def test_validation_is_strict_and_private(self):
        for value in ['', 'private', '='*43, 'a'*44, None, 17]:
            with self.assertRaises(receipts.Rejected) as error:
                receipts.credential(str(uuid4()),value)
            self.assertEqual(str(error.exception),'')
        op=str(uuid4()); value=secret()
        self.assertEqual(receipts.credential(op,value),receipts.credential(op,value))
        self.assertNotEqual(receipts.credential(op,value)[1],receipts.credential(str(uuid4()),value)[1])

    def test_bounded_limiter(self):
        now=[0.]
        limiter=receipts.Limiter(lambda:now[0])
        self.assertTrue(all(limiter.allow() for _ in range(30)))
        self.assertFalse(limiter.allow())
        now[0]=1
        self.assertTrue(all(limiter.allow() for _ in range(5)))
        self.assertFalse(limiter.allow())


class ReceiptApiTests(DeletionApiTests):
    def test_no_store_for_all_error_paths_and_unrelated_routes_unchanged(self):
        self.app.get('/unrelated')(lambda: {'ok': True})
        self.assertNotIn('cache-control',self.client.get('/unrelated').headers)
        responses=[self.client.post('/api/account/deletion/request',content=b'{invalid'),
                   self.client.delete('/api/account/deletion/status'),
                   self.client.get('/api/account/deletion/unknown')]
        self.app.dependency_overrides.clear()
        responses.append(self.client.post('/api/account/deletion/request',json={}))
        responses.append(self.client.post('/api/account/deletion/status',headers={'Authorization':'DeletionStatus malformed'}))
        with patch.object(receipts.limiter,'allow',return_value=False):
            responses.append(self.client.post('/api/account/deletion/status'))
        with patch.object(receipts,'lookup',side_effect=RuntimeError('PRIVATE_SENTINEL')):
            responses.append(self.client.post('/api/account/deletion/status',headers={'Authorization':f'DeletionStatus {uuid4()}.{secret()}'}))
        with patch.object(receipts,'enabled',side_effect=RuntimeError('PRIVATE_SENTINEL')):
            responses.append(self.client.get('/api/account/deletion/capabilities'))
        self.assertEqual([r.status_code for r in responses],[422,405,404,401,401,429,500,500])
        for response in responses:
            self.assertEqual(response.headers['cache-control'],'no-store')
            self.assertNotIn('PRIVATE_SENTINEL',response.text)

    def test_new_protocol_rejects_missing_credential_and_never_echoes_secret(self):
        for body in ({'confirmation':'DELETE_MY_ACCOUNT'}, {'confirmation':'DELETE_MY_ACCOUNT','status_credential':{'secret':'PRIVATE_SENTINEL'}}):
            reply=self.client.post('/api/account/deletion/request',json=body)
            self.assertEqual(reply.status_code,422)
            self.assertNotIn('PRIVATE_SENTINEL',reply.text)
            self.assertEqual(reply.headers['cache-control'],'no-store')

    def test_status_credential_never_authorizes_legacy_deletion(self):
        self.app.dependency_overrides.clear()
        response=self.client.post('/api/account/deletion',json={'confirmation':'DELETE_MY_ACCOUNT'},headers={'Authorization':f'DeletionStatus {uuid4()}.{secret()}'})
        self.assertEqual(response.status_code,401)

    def test_capability_flag_and_read_only_status_without_jwt(self):
        with patch.dict(os.environ,{'DELETION_RECEIPTS_ENABLED':'false'}):
            self.assertEqual(self.client.get('/api/account/deletion/capabilities').status_code,503)
        self.app.dependency_overrides.clear()
        value=secret(); op=str(uuid4())
        with patch.object(receipts,'lookup',return_value={'operation_id':op,'status':'completed'}) as lookup:
            reply=self.client.post('/api/account/deletion/status',headers={'Authorization':f'DeletionStatus {op}.{value}'})
            self.assertEqual(reply.status_code,200)
            lookup.assert_called_once_with(self.api.pool,op,value)
        for header in ('Bearer expired','DeletionStatus invalid',''):
            self.assertEqual(self.client.post('/api/account/deletion/status',headers={'Authorization':header}).status_code,401)


@unittest.skipUnless(os.environ.get('GEMINI_TEST_DATABASE_URL'),'Local PostgreSQL not configured')
class ReceiptPostgresTests(unittest.TestCase):
    def setUp(self):
        self.fixture=AccountDeletionPostgresTests(methodName='runTest')
        self.addCleanup(self.fixture.doCleanups); self.fixture.setUp()
        self.pool=self.fixture.pool; self.query=self.fixture.query; self.owner=self.fixture.creator[0]
        self.op=str(uuid4()); self.secret=secret()
        enabled=patch.dict(os.environ,{'DELETION_RECEIPTS_ENABLED':'true'}); enabled.start(); self.addCleanup(enabled.stop)

    def start(self):
        return receipts.initiate(self.pool,self.owner,self.op,self.secret)

    def test_lost_initiation_concurrent_retry_and_credentials(self):
        with ThreadPoolExecutor(4) as executor:
            results=list(executor.map(lambda _:self.start(),range(4)))
        self.assertTrue(all(x==results[0] for x in results))
        self.assertEqual(self.query('SELECT count(*) FROM account_deletion_receipts'),[(1,)])
        self.assertEqual(receipts.lookup(self.pool,self.op,self.secret)['status'],'pending')
        with self.assertRaises(receipts.Rejected): receipts.lookup(self.pool,self.op,secret())
        with self.assertRaises(receipts.Rejected): receipts.initiate(self.pool,self.owner,self.op,secret())
        stranger=self.fixture.person()[0]
        with self.assertRaises(receipts.Rejected): receipts.initiate(self.pool,stranger,self.op,self.secret)

    def test_job_receipt_atomic_rollback(self):
        self.query("CREATE FUNCTION reject_receipt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected'; END $$; CREATE TRIGGER reject_receipt BEFORE INSERT ON account_deletion_receipts FOR EACH ROW EXECUTE FUNCTION reject_receipt()")
        with self.assertRaises(Exception): self.start()
        self.assertEqual(self.query('SELECT count(*) FROM account_deletion_jobs'),[(0,)])
        self.assertEqual(self.query('SELECT count(*) FROM account_deletion_receipts'),[(0,)])

    def test_finalization_rollback_then_lost_response_retry(self):
        self.start()
        job=self.query('SELECT job_ref FROM account_deletion_jobs')[0][0]
        # Exercise real finalizer with the existing worker preconditions satisfied.
        self.query("UPDATE account_deletion_jobs SET phase='auth_pending',apple_state='not_applicable'")
        self.query('UPDATE users SET auth_user_id=NULL WHERE auth_user_id=%s',(self.owner,))
        self.query('DELETE FROM auth_users WHERE id=%s',(self.owner,))
        self.query("CREATE FUNCTION fail_delete() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected'; END $$; CREATE TRIGGER fail_delete BEFORE DELETE ON account_deletion_jobs FOR EACH ROW EXECUTE FUNCTION fail_delete()")
        attempt=apple_revocation.Attempt(self.owner,job,0)
        with self.assertRaises(Exception): apple_revocation.finalize(self.pool,attempt)
        self.assertEqual(receipts.lookup(self.pool,self.op,self.secret)['status'],'pending')
        self.query('DROP TRIGGER fail_delete ON account_deletion_jobs')
        self.assertTrue(apple_revocation.finalize(self.pool,attempt))
        first=receipts.lookup(self.pool,self.op,self.secret)
        self.assertEqual(first['status'],'completed')
        self.assertEqual(receipts.lookup(self.pool,self.op,self.secret),first)
        self.assertEqual(self.query('SELECT expires_at-completed_at FROM account_deletion_receipts'),[(timedelta(days=180),)])
        self.assertEqual(self.query('SELECT count(*) FROM account_deletion_jobs'),[(0,)])

    def test_old_worker_cannot_delete_pending_receipt_job(self):
        self.query("CREATE FUNCTION guard_receipt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF EXISTS(SELECT 1 FROM account_deletion_receipts WHERE job_ref=OLD.job_ref AND state='pending') THEN RAISE EXCEPTION 'receipt required'; END IF; RETURN OLD; END $$; CREATE TRIGGER receipt_guard BEFORE DELETE ON account_deletion_jobs FOR EACH ROW EXECUTE FUNCTION guard_receipt()")
        self.start()
        with self.assertRaises(Exception): self.query('DELETE FROM account_deletion_jobs')
        self.assertEqual(receipts.lookup(self.pool,self.op,self.secret)['status'],'pending')
        with self.pool.connection() as conn:
            job=conn.execute('SELECT job_ref FROM account_deletion_jobs').fetchone()[0]
            receipts.finalize(conn,job)
            conn.execute('DELETE FROM account_deletion_jobs')
        self.assertEqual(receipts.lookup(self.pool,self.op,self.secret)['status'],'completed')

    def test_deferred_commit_failure_rolls_back_receipt_and_job(self):
        self.start()
        self.query("CREATE FUNCTION fail_commit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'deferred'; END $$; CREATE CONSTRAINT TRIGGER fail_commit AFTER DELETE ON account_deletion_jobs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fail_commit()")
        with self.assertRaises(Exception):
            with self.pool.connection() as conn:
                job=conn.execute('SELECT job_ref FROM account_deletion_jobs').fetchone()[0]
                receipts.finalize(conn,job)
                conn.execute('DELETE FROM account_deletion_jobs')
        self.assertEqual(receipts.lookup(self.pool,self.op,self.secret)['status'],'pending')
        self.assertEqual(self.query('SELECT count(*) FROM account_deletion_jobs'),[(1,)])

    def test_retention_expiry_does_not_extend_and_pending_survives(self):
        self.start()
        for _ in range(3): receipts.lookup(self.pool,self.op,self.secret)
        self.assertEqual(self.query('SELECT expires_at FROM account_deletion_receipts'),[(None,)])
        receipts.expire(self.pool)
        self.assertEqual(self.query('SELECT count(*) FROM account_deletion_receipts'),[(1,)])
        self.query("UPDATE account_deletion_receipts SET created_at=statement_timestamp()-interval '182 days',state='completed',job_ref=NULL,completed_at=statement_timestamp()-interval '181 days',expires_at=statement_timestamp()-interval '1 day'")
        with self.assertRaises(receipts.Rejected): receipts.lookup(self.pool,self.op,self.secret)
        receipts.expire(self.pool)
        self.assertEqual(self.query('SELECT count(*) FROM account_deletion_receipts'),[(0,)])

    def test_constraints_and_direct_client_access(self):
        self.start()
        for update in ("state='completed'", "expires_at=clock_timestamp()", "job_ref=NULL", "credential_digest=decode('00','hex')"):
            with self.assertRaises(Exception): self.query('UPDATE account_deletion_receipts SET '+update)
        self.query('ALTER TABLE account_deletion_receipts ENABLE ROW LEVEL SECURITY; REVOKE ALL ON account_deletion_receipts FROM PUBLIC,anon,authenticated')
        for role in ('anon','authenticated'):
            with self.assertRaises(Exception):
                with self.pool.connection() as conn:
                    conn.execute('SET LOCAL ROLE '+role)
                    conn.execute('SELECT * FROM account_deletion_receipts')
        self.assertEqual(receipts.lookup(self.pool,self.op,self.secret)['status'],'pending')

    def test_absence_and_legacy_job_are_not_completion(self):
        with self.assertRaises(receipts.Rejected): receipts.initiate(self.pool,str(uuid4()),self.op,self.secret)
        self.query('INSERT INTO account_deletion_jobs(auth_user_id) VALUES(%s)',(self.owner,))
        with self.assertRaises(receipts.Rejected): self.start()
