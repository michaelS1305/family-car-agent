"""Real PostgreSQL integration, restricted to disposable loopback test_gemini."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from uuid import UUID,uuid4
import os
import unittest
from unittest.mock import patch
from tests import test_vehicle_admission as fixture_module
import vehicle_admission as admission

# No app startup/production DB: the test runner sets DATABASE_URL to the guarded local DB.
from device_api import ReturnVerification
import return_recovery
import return_reconciliation as resolution
from vehicle_identity import VehicleIdentityError
from account_deletion import _checkpoint_vehicle_identity


@unittest.skipUnless(os.getenv('GEMINI_TEST_DATABASE_URL'),'Requires local PostgreSQL')
class ResolutionPostgresTests(unittest.TestCase):
    connection=fixture_module.VehicleAdmissionPostgresTests.connection
    drop_schema=fixture_module.VehicleAdmissionPostgresTests.drop_schema
    query=fixture_module.VehicleAdmissionPostgresTests.query
    sequence=fixture_module.VehicleAdmissionPostgresTests.sequence
    sessions=fixture_module.VehicleAdmissionPostgresTests.sessions
    admit=fixture_module.VehicleAdmissionPostgresTests.admit

    def setUp(self):
        fixture_module.VehicleAdmissionPostgresTests.setUp(self)
        from pathlib import Path
        binding=(Path(__file__).resolve().parents[2]/'supabase/manual_migrations/2026092701_registered_device_vehicle_bindings.sql').read_text()
        ddl='CREATE TABLE public.registered_device_vehicle_bindings ('+binding.split('CREATE TABLE public.registered_device_vehicle_bindings (',1)[1].split(';',1)[0]+';'
        self.query(ddl.replace('public.',self.schema+'.'))
        self.query('ALTER TABLE families ADD COLUMN home_latitude double precision DEFAULT 0, ADD COLUMN home_longitude double precision DEFAULT 0')
        self.query('INSERT INTO registered_device_vehicle_bindings(device_id,vehicle_id) SELECT d.id,v.id FROM registered_devices d JOIN users u ON u.id=d.user_id JOIN vehicles v ON v.family_id=u.family_id')
        self.now=datetime.now(timezone.utc)
        self.taken=admission.NativeEvent(UUID('37765bae-39c3-4cea-bd53-10e30f2c7913'),self.devices[1],self.vehicles[0],'take',self.now-timedelta(minutes=30),13)
        self.query('UPDATE registered_devices SET last_processed_sequence=12 WHERE device_ref=%s',(self.devices[1],))
        self.assertEqual(self.admit(self.taken).kind,'accepted')
        self.original=replace(self.taken,event_id=UUID('07e91a49-bc53-4a33-8c41-f9c2b310fd28'),event_type='return',device_sequence=14,take_event_id=self.taken.event_id,occurred_at=self.now-timedelta(minutes=20))
        self.evidence=SimpleNamespace(latitude=1.,longitude=1.,accuracy_m=10.,location_at=self.original.occurred_at)
        self.verification=ReturnVerification(invoked_at=self.now,location_at=self.now,latitude=0.,longitude=0.,accuracy_m=10.)
        self.device_id=self.query('SELECT id FROM registered_devices WHERE device_ref=%s',(self.devices[1],))[0][0]
        self.vehicle_id=self.query('SELECT id FROM vehicles WHERE vehicle_ref=%s',(self.vehicles[0],))[0][0]
        with self.connection() as c:
            return_recovery.record_rejection(c,self.users[1],self.original,self.evidence,(self.device_id,), (self.vehicle_id,),VehicleIdentityError('RETURN_OUTSIDE_HOME','Home verification failed',409))

    def finalize(self):
        # Exactly the production checkpoint writer, deleting a DIFFERENT member's vehicle identity.
        with self.connection() as c:
            _checkpoint_vehicle_identity(c,2,10)

    def resolve(self,rid=None,verification=None,user=1,event=None,allow_new=True):
        with self.connection() as c:
            return resolution.reconcile_return(c,self.users[user],event or self.original,self.evidence,rid or uuid4(),verification or self.verification,allow_new=allow_new)

    def test_production_14_receipt_and_retry_lost_response(self):
        self.finalize(); rid=uuid4()
        first=self.resolve(rid)
        self.assertEqual(first['kind'],'resolved_current_state')
        self.assertEqual(self.sequence(),14)
        self.assertEqual(self.query('SELECT admission_outcome,occurred_at FROM vehicle_events WHERE event_id=%s',(self.original.event_id,))[0],('before_finalized_boundary',self.original.occurred_at))
        self.assertEqual(self.resolve(rid),first)
        self.assertEqual(self.resolve(),first)
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_return_reconciliations')[0][0],1)
        changed=self.verification.model_copy(update={'accuracy_m':20.})
        self.assertEqual(self.resolve(rid,changed).code,'RETURN_RECONCILIATION_IDEMPOTENCY_CONFLICT')

    def test_window_only_and_combined(self):
        # Server time advances four days; immutable original timestamps are untouched.
        future=self.now+timedelta(days=4)
        fresh=self.verification.model_copy(update={'invoked_at':future,'location_at':future})
        class Clock:
            def __init__(self,c): self.c=c
            def transaction(self): return self.c.transaction()
            def execute(self,sql,params=None):
                if sql=='SELECT clock_timestamp()': return SimpleNamespace(fetchone=lambda:(future,))
                return self.c.execute(sql,params)
        with self.connection() as c:
            result=resolution.reconcile_return(Clock(c),self.users[1],self.original,self.evidence,uuid4(),fresh)
        self.assertEqual(result['kind'],'resolved_current_state')
        self.assertEqual(self.query('SELECT blocked_by_checkpoint,blocked_by_window FROM vehicle_return_reconciliations')[0],(False,True))
        self.assertEqual(self.sessions()[0][4],future)

    def test_unrelated_and_invalid_checks(self):
        self.assertEqual(self.resolve().code,'RETURN_RECONCILIATION_NOT_FINALIZED')
        self.finalize()
        self.query('UPDATE registered_devices SET last_processed_sequence=12 WHERE id=%s',(self.device_id,))
        self.assertEqual(self.resolve().code,'RETURN_RECONCILIATION_SEQUENCE_CONFLICT')
        self.query('UPDATE registered_devices SET last_processed_sequence=13 WHERE id=%s',(self.device_id,))
        bad=self.verification.model_copy(update={'latitude':1.})
        self.assertEqual(self.resolve(verification=bad).code,'RETURN_OUTSIDE_HOME')
        expired=self.verification.model_copy(update={'invoked_at':self.now-timedelta(minutes=5)})
        self.assertEqual(self.resolve(verification=expired).code,'RETURN_RECONCILIATION_VERIFICATION_EXPIRED')
        with self.assertRaises(VehicleIdentityError): self.resolve(user=3)
        self.assertEqual(self.sequence(),13)

    def test_concurrent_duplicate_and_rollback(self):
        self.finalize(); rid=uuid4()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.resolve(rid),range(2)))
        self.assertEqual(results[0],results[1])
        self.assertEqual(self.query('SELECT count(*) FROM return_reconciliation_attempts')[0][0],1)

    def test_failure_after_checkpoint_rolls_back(self):
        self.finalize()
        with patch.object(admission,'_receipt',side_effect=RuntimeError('test rollback')):
            with self.assertRaises(RuntimeError): self.resolve()
        self.assertEqual(self.sequence(),13)
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_return_reconciliations')[0][0],0)
        self.assertIsNone(self.sessions()[0][4])

    def test_late_take_return_pairs_replay_and_checkpoint(self):
        # Boundary before later offline events, unlike account deletion's now checkpoint.
        boundary=self.original.occurred_at+timedelta(seconds=1)
        self.query('UPDATE families SET vehicle_finalized_through=%s,vehicle_reconciliation_generation=vehicle_reconciliation_generation+1 WHERE id=10',(boundary,))
        self.query('UPDATE vehicle_driver_sessions SET checkpoint_generation=(SELECT vehicle_reconciliation_generation FROM families WHERE id=10) WHERE family_id=10')
        outcome=self.resolve(); self.assertEqual(outcome['kind'],'resolved_current_state')
        anchor=self.sessions()[0][0]
        t=replace(self.taken,event_id=uuid4(),device_sequence=15,occurred_at=self.now-timedelta(minutes=10))
        self.assertEqual(self.admit(t).kind,'accepted')
        self.assertEqual(self.sessions()[0][0],anchor)
        r=replace(t,event_id=uuid4(),device_sequence=16,event_type='return',take_event_id=t.event_id,occurred_at=self.now-timedelta(minutes=9))
        self.assertEqual(self.admit(r).kind,'accepted')
        self.assertEqual(self.sessions()[0][4],r.occurred_at)
        t2=replace(t,event_id=uuid4(),device_sequence=17,occurred_at=self.now-timedelta(minutes=8))
        self.assertEqual(self.admit(t2).kind,'accepted')
        self.assertIsNone(self.sessions()[-1][4]) # Never close a new logical session.
        # A later family checkpoint absorbs both the no-op resolution and current state.
        self.finalize()
        t3=replace(t2,event_id=uuid4(),device_sequence=18,occurred_at=datetime.now(timezone.utc)+timedelta(seconds=1))
        self.assertEqual(self.admit(t3).kind,'accepted')
        self.assertIsNone(self.sessions()[-1][4])

    def test_account_cleanup_cascades(self):
        self.finalize(); self.resolve()
        with self.connection() as c: _checkpoint_vehicle_identity(c,1,10)
        for table in ('return_recovery_candidates','return_reconciliation_attempts','vehicle_return_reconciliations'):
            self.assertEqual(self.query('SELECT count(*) FROM '+table)[0][0],0)

    def test_checkpoint_equality_and_combined_reason(self):
        self.query('UPDATE families SET vehicle_finalized_through=%s,vehicle_reconciliation_generation=vehicle_reconciliation_generation+1 WHERE id=10',(self.original.occurred_at,))
        self.query('UPDATE vehicle_driver_sessions SET checkpoint_generation=(SELECT vehicle_reconciliation_generation FROM families WHERE id=10) WHERE family_id=10')
        result=self.resolve()
        self.assertEqual(result['kind'],'resolved_current_state')
        self.assertEqual(self.query('SELECT blocked_by_checkpoint,blocked_by_window FROM vehicle_return_reconciliations')[0],(True,False))

    def test_rolling_equality_and_both_blockers(self):
        self.finalize()
        future=self.original.occurred_at+timedelta(hours=72)
        fresh=self.verification.model_copy(update={'invoked_at':future,'location_at':future})
        class Clock:
            def __init__(self,c): self.c=c
            def transaction(self): return self.c.transaction()
            def execute(self,sql,params=None):
                if sql=='SELECT clock_timestamp()': return SimpleNamespace(fetchone=lambda:(future,))
                return self.c.execute(sql,params)
        with self.connection() as c:
            result=resolution.reconcile_return(Clock(c),self.users[1],self.original,self.evidence,uuid4(),fresh)
        self.assertEqual(result['kind'],'resolved_current_state')
        self.assertEqual(self.query('SELECT blocked_by_checkpoint,blocked_by_window FROM vehicle_return_reconciliations')[0],(True,True))

    def test_independent_chronology_and_causality(self):
        self.finalize()
        # Even though a cutoff rejection would hide chronology in normal admission,
        # reconciliation must independently reject it. A separate accepted signal
        # supplies the latest device time without changing the candidate.
        with self.connection() as c:
            c.execute("INSERT INTO vehicle_events(event_id,family_id,vehicle_id,user_id,device_id,source,event_type,occurred_at,device_sequence,admission_outcome) VALUES(%s,10,%s,1,%s,'native','take',%s,12,'accepted')",
                (uuid4(),self.vehicle_id,self.device_id,self.now))
            # Latest is sequence13; test through the real independent checker with
            # a later sequence13 original time represented by the SQL read wrapper.
            class Latest:
                def execute(inner,sql,params=None):
                    if sql.startswith('SELECT occurred_at FROM vehicle_events WHERE device_id='):
                        return SimpleNamespace(fetchone=lambda:(self.now,))
                    return c.execute(sql,params)
                def transaction(inner): return c.transaction()
            result=resolution.reconcile_return(Latest(),self.users[1],self.original,self.evidence,uuid4(),self.verification)
            self.assertEqual(result.code,'RETURN_RECONCILIATION_INVALID_CHRONOLOGY')
        self.assertEqual(self.sequence(),13)
        # Missing/mismatched immutable evidence never reaches sequence consumption.
        altered=replace(self.original,take_event_id=uuid4())
        self.assertEqual(self.resolve(event=altered).code,'RETURN_RECONCILIATION_EVIDENCE_MISMATCH')

    def test_concurrent_checkpoint_serialization(self):
        self.finalize()
        def checkpoint():
            import vehicle_lifecycle
            with self.connection() as c, vehicle_lifecycle._scope(c,self.users[1]):
                _checkpoint_vehicle_identity(c,2,10)
        with ThreadPoolExecutor(max_workers=2) as pool:
            one=pool.submit(self.resolve)
            two=pool.submit(checkpoint)
            self.assertEqual(one.result()['kind'],'resolved_current_state')
            two.result()
        self.assertEqual(self.sequence(),14)
        self.assertIsNotNone(self.sessions()[0][4])

    def test_concurrent_owner_cleanup_never_resurrects(self):
        self.finalize()
        def cleanup():
            import account_deletion
            with self.connection() as c:
                account_deletion.lock_identity(c,self.users[1].auth_user_id,exclusive=True)
                c.execute('SELECT pg_advisory_xact_lock(%s,%s)',(admission.CAR_TRANSITION_LOCK_NAMESPACE,10))
                c.execute('SELECT id FROM families WHERE id=10 FOR UPDATE')
                _checkpoint_vehicle_identity(c,1,10)
        def recover():
            try: return self.resolve()
            except VehicleIdentityError: return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            one=pool.submit(recover); two=pool.submit(cleanup)
            one.result(); two.result()
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_return_reconciliations')[0][0],0)
        self.assertEqual(self.query('SELECT count(*) FROM registered_devices WHERE user_id=1')[0][0],0)

    def test_other_driver_late_handover_survives_resolution_replay(self):
        boundary=self.original.occurred_at
        self.query('UPDATE families SET vehicle_finalized_through=%s,vehicle_reconciliation_generation=vehicle_reconciliation_generation+1 WHERE id=10',(boundary,))
        self.query('UPDATE vehicle_driver_sessions SET checkpoint_generation=(SELECT vehicle_reconciliation_generation FROM families WHERE id=10) WHERE family_id=10')
        self.resolve()
        other=replace(self.taken,event_id=uuid4(),device_ref=self.devices[2],device_sequence=1,occurred_at=self.now-timedelta(minutes=5))
        self.assertEqual(self.admit(other,user=2).kind,'accepted')
        active=[s for s in self.sessions() if s[4] is None]
        self.assertEqual(len(active),1)
        self.assertEqual(active[0][1],2)
        # A subsequent device1 RETURN never targets driver2's session.
        r=replace(self.original,event_id=uuid4(),device_sequence=15,occurred_at=self.now+timedelta(seconds=2))
        self.assertEqual(self.admit(r).kind,'accepted')
        self.assertEqual([s[1] for s in self.sessions() if s[4] is None],[2])

    def test_original_and_attempt_immutability(self):
        self.finalize(); self.resolve()
        for table,column in [('return_recovery_candidates','occurred_at'),('return_reconciliation_attempts','received_at'),('vehicle_return_reconciliations','effective_at')]:
            with self.assertRaises(Exception): self.query('UPDATE '+table+' SET '+column+'=clock_timestamp()')
        self.assertEqual(self.sequence(),14)

    def test_post_resolution_pairs_and_equal_time_order(self):
        self.finalize()
        result=self.resolve()
        effective=datetime.fromisoformat(result['effective_at'])
        # Equal-time TAKE is ordered before the operation and remains redundant.
        equal=replace(self.taken,event_id=uuid4(),device_sequence=15,occurred_at=effective)
        self.assertEqual(self.admit(equal).kind,'accepted')
        self.assertFalse(any(row[4] is None for row in self.sessions()))
        after=replace(equal,event_id=uuid4(),device_sequence=16,occurred_at=effective+timedelta(seconds=1))
        self.assertEqual(self.admit(after).kind,'accepted')
        self.assertIsNone(self.sessions()[-1][4])
        returned=replace(after,event_id=uuid4(),device_sequence=17,event_type='return',take_event_id=after.event_id,occurred_at=effective+timedelta(seconds=2))
        self.assertEqual(self.admit(returned).kind,'accepted')
        self.assertFalse(any(row[4] is None for row in self.sessions()))
        again=replace(after,event_id=uuid4(),device_sequence=18,occurred_at=effective+timedelta(seconds=3))
        self.assertEqual(self.admit(again).kind,'accepted')
        self.assertIsNone(self.sessions()[-1][4])

    def test_expired_retry_returns_committed_receipt(self):
        self.finalize(); rid=uuid4(); result=self.resolve(rid)
        # No home check, timestamp read or mutation on a committed identical retry.
        with patch.object(resolution.bindings,'verify_home',side_effect=AssertionError('must not reverify')):
            self.assertEqual(self.resolve(rid),result)

    def test_closed_session_and_unbound_vehicle_fail_without_receipt(self):
        # Another driver's accepted takeover closes the linked session.
        other=replace(self.taken,event_id=uuid4(),device_ref=self.devices[2],device_sequence=1,occurred_at=self.now-timedelta(minutes=1))
        self.assertEqual(self.admit(other,user=2).kind,'accepted')
        self.finalize()
        self.assertEqual(self.resolve().code,'RETURN_RECONCILIATION_NOT_ELIGIBLE')
        self.assertEqual(self.sequence(),13)
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_events WHERE event_id=%s',(self.original.event_id,))[0][0],0)

    def test_budget_exhaustion_leaves_no_partial_resolution(self):
        from vehicle_work import Budget,WorkLimits,PolicyExceeded
        self.finalize()
        before=self.query('SELECT vehicle_reconciliation_generation,vehicle_finalized_through FROM families WHERE id=10')
        # Require a later rolling checkpoint; this fails its bounded row scan.
        future=self.now+timedelta(days=4)
        fresh=self.verification.model_copy(update={'invoked_at':future,'location_at':future})
        class Clock:
            def __init__(self,c): self.c=c
            def transaction(self): return self.c.transaction()
            def execute(self,sql,params=None):
                if sql=='SELECT clock_timestamp()': return SimpleNamespace(fetchone=lambda:(future,))
                return self.c.execute(sql,params)
        with patch.object(resolution,'Budget',return_value=Budget(WorkLimits(checkpoint=0))):
            with self.assertRaises(PolicyExceeded),self.connection() as c:
                resolution.reconcile_return(Clock(c),self.users[1],self.original,self.evidence,uuid4(),fresh)
        self.assertEqual(self.query('SELECT vehicle_reconciliation_generation,vehicle_finalized_through FROM families WHERE id=10'),before)
        self.assertEqual(self.sequence(),13)
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_return_reconciliations')[0][0],0)

    def test_additive_schema_is_backend_only(self):
        for table in ('return_reconciliation_attempts','vehicle_return_reconciliations'):
            self.assertTrue(self.query('SELECT relrowsecurity FROM pg_class WHERE oid=%s::regclass',(table,))[0][0])
            for role in ('anon','authenticated'):
                self.assertFalse(self.query("SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE')",(role,table))[0][0])
        self.assertEqual(self.query("SELECT count(*) FROM vehicle_events WHERE admission_outcome='accepted'")[0][0],1)

    def resolution_snapshot(self):
        tables=('families','registered_devices','vehicle_events','vehicle_driver_sessions',
                'return_recovery_candidates','return_recovery_attempts',
                'return_reconciliation_attempts','vehicle_return_reconciliations')
        return {t:self.query('SELECT to_jsonb(t) FROM '+t+' t ORDER BY to_jsonb(t)::text') for t in tables}

    def test_disabled_exact_retry_preserves_committed_result_without_writes(self):
        self.finalize(); rid=uuid4(); result=self.resolve(rid)
        before=self.resolution_snapshot()
        with patch.object(resolution,'_resolve',side_effect=AssertionError('disabled must not resolve')):
            self.assertEqual(self.resolve(rid,allow_new=False),result)
            with self.assertRaises(VehicleIdentityError): self.resolve(rid,user=3,allow_new=False)
            self.assertEqual(self.resolve(allow_new=False).code,'RETURN_RECONCILIATION_DISABLED')
            changed=self.verification.model_copy(update={'accuracy_m':20.})
            self.assertEqual(self.resolve(rid,verification=changed,allow_new=False).code,'RETURN_RECONCILIATION_IDEMPOTENCY_CONFLICT')
        self.assertEqual(self.resolution_snapshot(),before)

    def test_disabled_new_request_and_unauthorized_cannot_write(self):
        self.finalize(); before=self.resolution_snapshot()
        self.assertEqual(self.resolve(allow_new=False).code,'RETURN_RECONCILIATION_DISABLED')
        with self.assertRaises(VehicleIdentityError): self.resolve(user=3,allow_new=False)
        self.assertEqual(self.resolution_snapshot(),before)

    def test_failure_after_attempt_insert_rolls_back_every_write(self):
        self.finalize(); before=self.resolution_snapshot()
        with self.assertRaisesRegex(RuntimeError,'after final write'), self.connection() as c:
            class Interrupted:
                def transaction(inner): return c.transaction()
                def execute(inner,sql,params=None):
                    result=c.execute(sql,params)
                    if sql.startswith('INSERT INTO return_reconciliation_attempts '):
                        raise RuntimeError('after final write')
                    return result
            resolution.reconcile_return(Interrupted(),self.users[1],self.original,self.evidence,uuid4(),self.verification)
        self.assertEqual(self.resolution_snapshot(),before)

    def test_deferred_fk_commit_failure_rolls_back_every_write(self):
        self.finalize(); before=self.resolution_snapshot(); returned=False
        from psycopg.errors import ForeignKeyViolation
        with self.assertRaises(ForeignKeyViolation), self.connection() as c:
            c.execute('SELECT 1')  # Explicit caller-owned outer transaction.
            class BrokenAttemptIdentity:
                def transaction(inner): return c.transaction()
                def execute(inner,sql,params=None):
                    if sql.startswith('INSERT INTO return_reconciliation_attempts '):
                        # Inject wrong attempt identity; the real unchanged deferred
                        # FK must reject the OUTER commit, not the service savepoint.
                        params=(params[0],uuid4(),*params[2:])
                    return c.execute(sql,params)
            result=resolution.reconcile_return(BrokenAttemptIdentity(),self.users[1],self.original,self.evidence,uuid4(),self.verification)
            self.assertEqual(result['kind'],'resolved_current_state')
            returned=True
        self.assertTrue(returned)
        self.assertEqual(self.resolution_snapshot(),before)

    def test_over_512_operations_fast_admission_and_bounded_replay(self):
        # Synthetic ledger volume exercises actual SQL, constraints and admission.
        # Do not invoke 513 real home-resolution flows or weaken any schema guard.
        self.finalize(); first=self.resolve()
        from psycopg.types.json import Jsonb
        with self.connection() as c:
            for index in range(513):
                event,rid,operation=uuid4(),uuid4(),uuid4()
                c.execute('INSERT INTO return_recovery_candidates '
                    '(event_id,family_id,user_id,device_id,vehicle_id,device_sequence,take_event_id,occurred_at,rejection_code,payload_fingerprint,original_evidence) '
                    'SELECT %s,family_id,user_id,device_id,vehicle_id,%s,take_event_id,occurred_at,rejection_code,payload_fingerprint,original_evidence '
                    'FROM return_recovery_candidates WHERE event_id=%s',(event,1000+index,self.original.event_id))
                c.execute('INSERT INTO return_reconciliation_attempts '
                    '(event_id,reconciliation_id,payload_fingerprint,invoked_at,location_at,received_at,result) '
                    'SELECT %s,%s,payload_fingerprint,invoked_at,location_at,received_at,%s FROM return_reconciliation_attempts WHERE event_id=%s',
                    (event,rid,Jsonb({'fixture':True}),self.original.event_id))
                c.execute('INSERT INTO vehicle_return_reconciliations '
                    '(operation_id,original_event_id,reconciliation_id,family_id,user_id,device_id,vehicle_id,take_event_id,anchor,session_ref,effective_at,observed_boundary,effective_boundary,checkpoint_generation,blocked_by_checkpoint,blocked_by_window) '
                    'SELECT %s,%s,%s,family_id,user_id,device_id,vehicle_id,take_event_id,anchor,session_ref,effective_at,observed_boundary,effective_boundary,checkpoint_generation,blocked_by_checkpoint,blocked_by_window '
                    'FROM vehicle_return_reconciliations WHERE original_event_id=%s',(operation,event,rid,self.original.event_id))
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_return_reconciliations')[0][0],514)
        effective=datetime.fromisoformat(first['effective_at'])
        fast=replace(self.taken,event_id=uuid4(),device_sequence=15,occurred_at=effective+timedelta(seconds=1))
        with patch.object(admission,'_resolutions',side_effect=AssertionError('fast path must not load replay')):
            self.assertEqual(self.admit(fast).kind,'accepted')
        self.assertEqual(self.sequence(),15)
        self.assertEqual(self.query('SELECT admission_outcome FROM vehicle_events WHERE event_id=%s',(fast.event_id,)),[('accepted',)])
        # Another device's event at the operation instant genuinely needs replay.
        device=self.query("INSERT INTO registered_devices(user_id,platform) VALUES(1,'ios') RETURNING device_ref")[0][0]
        replay=replace(fast,event_id=uuid4(),device_ref=device,device_sequence=1,occurred_at=effective)
        sessions_before=self.sessions()
        result=self.admit(replay)
        self.assertEqual(self.sessions(),sessions_before)
        self.assertEqual((result.kind,result.admission_outcome),('terminal','reconciliation_policy_exceeded'))
        self.assertEqual(self.sequence(),15)
        # Preserve existing terminal semantics: only the replay device consumes its
        # explicit terminal receipt; it must not be accepted or mutate sessions.
        self.assertEqual(self.query('SELECT last_processed_sequence FROM registered_devices WHERE device_ref=%s',(device,))[0][0],1)
        self.assertEqual(self.query('SELECT admission_outcome FROM vehicle_events WHERE event_id=%s',(replay.event_id,)),[('reconciliation_policy_exceeded',)])
