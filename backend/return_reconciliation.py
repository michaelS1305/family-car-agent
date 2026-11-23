"""Current-state resolution, never historical acceptance. Caller owns commit."""
from datetime import timedelta
from uuid import uuid4
from psycopg.types.json import Jsonb
import return_recovery as recovery
import vehicle_admission as admission
import vehicle_bindings as bindings
import vehicle_lifecycle as lifecycle
from vehicle_identity import VehicleIdentityError
from vehicle_work import Budget, CORRECTION_HOURS, SESSION_COLUMNS, rolling_checkpoint


def refused(code):
    return recovery.Refusal('RETURN_RECONCILIATION_' + code, 'Return reconciliation could not be completed')


def reconcile_return(conn, user, event, evidence, reconciliation_id, verification, *, allow_new=True):
    with admission._bounded_connection(conn) as conn, lifecycle._scope(conn, user):
        device = bindings._native(conn, user, event.device_ref)
        vehicle = lifecycle._vehicle(conn, user, event.vehicle_ref)
        if device[3] is not None:
            bindings.unavailable()
        candidate = conn.execute('SELECT payload_fingerprint,rejection_code FROM return_recovery_candidates '
            'WHERE event_id=%s AND user_id=%s AND family_id=%s AND device_id=%s AND vehicle_id=%s FOR UPDATE',
            (event.event_id,user.user_id,user.family_id,device[0],vehicle[0])).fetchone()
        if not candidate or candidate[1] not in recovery.HOME_CODES:
            return refused('NOT_ELIGIBLE')
        original = recovery.original(event,evidence)
        if candidate[0] != recovery.fingerprint(original):
            return refused('EVIDENCE_MISMATCH')
        digest = recovery.fingerprint({'original':original,'verification':verification.model_dump()})
        prior = conn.execute('SELECT payload_fingerprint,result FROM return_reconciliation_attempts '
            'WHERE event_id=%s AND reconciliation_id=%s',(event.event_id,reconciliation_id)).fetchone()
        if prior:
            return recovery._restore(prior[1]) if prior[0] == digest else refused('IDEMPOTENCY_CONFLICT')
        if not allow_new:
            return recovery.Refusal('RETURN_RECONCILIATION_DISABLED', 'Return reconciliation unavailable', 503)
        completed = conn.execute('SELECT a.result FROM vehicle_return_reconciliations r '
            'JOIN return_reconciliation_attempts a ON a.event_id=r.original_event_id AND a.reconciliation_id=r.reconciliation_id '
            'WHERE r.original_event_id=%s',(event.event_id,)).fetchone()
        if completed:
            return completed[0]  # Canonical committed identity, not a second operation.
        now = conn.execute('SELECT clock_timestamp()').fetchone()[0]
        result = _resolve(conn,user,event,device,vehicle,verification,reconciliation_id,now)
        stored = {'code':result.code,'message':result.message,'status_code':result.status_code} if isinstance(result,recovery.Refusal) else result
        conn.execute('INSERT INTO return_reconciliation_attempts '
            '(event_id,reconciliation_id,payload_fingerprint,invoked_at,location_at,received_at,result) VALUES(%s,%s,%s,%s,%s,%s,%s)',
            (event.event_id,reconciliation_id,digest,verification.invoked_at,verification.location_at,now,Jsonb(stored)))
        return result


def _resolve(conn,user,event,device,vehicle,verification,rid,now):
    if admission._envelope(event) is None:
        return refused('NOT_ELIGIBLE')
    if conn.execute('SELECT 1 FROM vehicle_events WHERE event_id=%s OR (device_id=%s AND device_sequence=%s)',
                    (event.event_id,device[0],event.device_sequence)).fetchone():
        return refused('SEQUENCE_CONFLICT')
    last = conn.execute('SELECT last_processed_sequence FROM registered_devices WHERE id=%s FOR UPDATE',(device[0],)).fetchone()[0]
    if event.device_sequence != last+1:
        return refused('SEQUENCE_CONFLICT')
    last_time = conn.execute("SELECT occurred_at FROM vehicle_events WHERE device_id=%s AND admission_outcome='accepted' ORDER BY device_sequence DESC LIMIT 1",(device[0],)).fetchone()
    if last_time and event.occurred_at < last_time[0]:
        return refused('INVALID_CHRONOLOGY')
    if not recovery.cause_exists(conn,user,event,vehicle[0]):
        return refused('NOT_ELIGIBLE')
    if vehicle[3] is not None or not conn.execute('SELECT 1 FROM registered_device_vehicle_bindings WHERE device_id=%s AND vehicle_id=%s',(device[0],vehicle[0])).fetchone():
        return refused('NOT_ELIGIBLE')
    generation,boundary = conn.execute('SELECT vehicle_reconciliation_generation,vehicle_finalized_through FROM families WHERE id=%s',(user.family_id,)).fetchone()
    cutoff = now-timedelta(hours=CORRECTION_HOURS)
    target = max(boundary,cutoff) if boundary else cutoff
    by_checkpoint = boundary is not None and event.occurred_at <= boundary
    by_window = event.occurred_at <= cutoff
    if not (by_checkpoint or by_window):
        return refused('NOT_FINALIZED')
    if now <= target:
        return refused('STATE_CHANGED')
    if not (0 <= (verification.invoked_at-verification.location_at).total_seconds() <= 30 and
            0 <= (now-verification.invoked_at).total_seconds() <= 120 and verification.invoked_at >= event.occurred_at):
        return refused('VERIFICATION_EXPIRED')
    try:
        bindings.verify_home(conn,user,verification)
    except VehicleIdentityError as error:
        if error.code not in recovery.HOME_CODES:
            raise
        return recovery.Refusal(error.code,error.message,error.status_code)
    cause = conn.execute("SELECT projection_take_event_id FROM vehicle_events WHERE event_id=%s",(event.take_event_id,)).fetchone()
    anchor = cause[0] if cause else None
    row = conn.execute(f'SELECT {SESSION_COLUMNS} FROM vehicle_driver_sessions WHERE start_event_id=%s AND user_id=%s AND vehicle_id=%s AND family_id=%s FOR UPDATE',
        (anchor,user.user_id,vehicle[0],user.family_id)).fetchone()
    if not row or row[6] is not None or row[4] > event.occurred_at:
        return refused('NOT_ELIGIBLE')
    budget=Budget()
    # Failure rolls back the whole caller transaction, including checkpoint work.
    generation,new_boundary=rolling_checkpoint(conn,user.family_id,generation,boundary,target,budget)
    marked=conn.execute('SELECT checkpoint_generation FROM vehicle_driver_sessions WHERE id=%s',(row[0],)).fetchone()
    if not marked or marked[0] != generation:
        raise admission.ReconciliationError('Resolution anchor not checkpointed')
    operation=uuid4()
    conn.execute('INSERT INTO vehicle_return_reconciliations '
        '(operation_id,original_event_id,reconciliation_id,family_id,user_id,device_id,vehicle_id,take_event_id,anchor,session_ref,effective_at,observed_boundary,effective_boundary,checkpoint_generation,blocked_by_checkpoint,blocked_by_window) '
        'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        (operation,event.event_id,rid,user.family_id,user.user_id,device[0],vehicle[0],event.take_event_id,anchor,row[1],now,boundary,target,generation,by_checkpoint,by_window))
    conn.execute("UPDATE vehicle_driver_sessions SET ended_at=%s,end_reason='current_state_reconciliation',end_event_id=NULL,end_reconciliation_id=%s WHERE id=%s AND ended_at IS NULL",(now,operation,row[0]))
    stored=(event.event_id,user.family_id,vehicle[0],user.user_id,device[0],'native','return',event.occurred_at,event.device_sequence,event.take_event_id)
    if not admission._receipt(conn,stored,'before_finalized_boundary',None):
        raise admission.ReconciliationError('Resolution receipt conflict')
    conn.execute('UPDATE registered_devices SET last_processed_sequence=%s WHERE id=%s',(event.device_sequence,device[0]))
    return {'kind':'resolved_current_state','event_id':str(event.event_id),'device_sequence':event.device_sequence,
        'historical_receipt':{'kind':'terminal','admission_outcome':'before_finalized_boundary'},
        'reconciliation_id':str(rid),'operation_id':str(operation),'effective_at':recovery.canonical(now),
        'session_effect':'closed_linked_session','last_processed_sequence':event.device_sequence}
