"""One bounded worker per process; PostgreSQL leases coordinate all processes.

Provider calls occur between transactions. A send can race revocation/deletion
after the last read; business pushes contain only a non-authorizing refresh hint.
Lost leases/ambiguous sends are NOT replayed as visible notifications.
"""
from contextlib import asynccontextmanager
from datetime import timedelta
import asyncio
import logging
from uuid import uuid4

from native_push_fcm import Result
from native_push_outbox import enabled, wakeup
from native_push_registration import ERASE
from native_push_security import Config, ConfigurationError, token_context, nonce_context
import native_push_reminders as reminders

log = logging.getLogger(__name__)


def _transaction(pool):
    return pool.connection()


def _limits(conn):
    conn.execute("SET LOCAL lock_timeout='1s'")
    conn.execute("SET LOCAL statement_timeout='3s'")


def claim_delivery(pool, project):
    with _transaction(pool) as conn:
        _limits(conn)
        # A crashed sender may have reached FCM: do not replay ambiguous work.
        conn.execute("WITH due AS (SELECT delivery_ref FROM native_push_deliveries WHERE status='leased' "
            "AND lease_until<=clock_timestamp() ORDER BY lease_until LIMIT 100 FOR UPDATE SKIP LOCKED) "
            "UPDATE native_push_deliveries SET status='failed',lease_token=NULL,lease_until=NULL,"
            "last_error_code='transport_uncertain',updated_at=clock_timestamp() "
            "WHERE delivery_ref IN (SELECT delivery_ref FROM due)")
        conn.execute("WITH due AS (SELECT d.delivery_ref FROM native_push_deliveries d JOIN native_push_events e USING(event_ref) "
            "WHERE d.status IN ('pending','retry_wait') AND e.expires_at<=clock_timestamp() "
            "ORDER BY e.expires_at LIMIT 100 FOR UPDATE OF d SKIP LOCKED) "
            "UPDATE native_push_deliveries SET status='expired',next_attempt_at=NULL,"
            "last_error_code='expired',updated_at=clock_timestamp() WHERE delivery_ref IN (SELECT delivery_ref FROM due)")
        row = conn.execute("SELECT d.delivery_ref FROM native_push_deliveries d "
            "JOIN native_push_installations i USING(installation_ref) "
            "WHERE d.status IN ('pending','retry_wait') AND d.next_attempt_at<=clock_timestamp() "
            "AND i.provider_project=%s ORDER BY d.next_attempt_at,d.delivery_ref "
            "LIMIT 1 FOR UPDATE OF d SKIP LOCKED", (project,)).fetchone()
        if not row:
            return None
        lease = uuid4()
        conn.execute("UPDATE native_push_deliveries SET status='leased',next_attempt_at=NULL,lease_token=%s,"
            "lease_until=clock_timestamp()+interval '30 seconds',attempt_count=attempt_count+1,"
            "updated_at=clock_timestamp() WHERE delivery_ref=%s", (lease,row[0]))
        return row[0],lease


def delivery_payload(pool, config, claim):
    with _transaction(pool) as conn:
        _limits(conn)
        row = conn.execute("SELECT i.token_ciphertext,i.encryption_key_id,i.platform,i.user_id,i.installation_ref,"
            "e.expires_at FROM native_push_deliveries d "
            "JOIN native_push_events e USING(event_ref) JOIN native_push_installations i USING(installation_ref) "
            "JOIN users u ON u.id=d.recipient_user_id JOIN users actor ON actor.id=e.actor_user_id "
            "JOIN vehicles v ON v.id=e.vehicle_id AND v.family_id=e.family_id "
            "JOIN auth.users a ON a.id=u.auth_user_id JOIN auth.users aa ON aa.id=actor.auth_user_id "
            "WHERE d.delivery_ref=%s AND d.lease_token=%s AND d.status='leased' "
            "AND d.lease_until>clock_timestamp() AND e.status='pending' AND e.expires_at>clock_timestamp() "
            "AND i.status='active' AND i.generation=d.installation_generation AND i.user_id=d.recipient_user_id "
            "AND i.provider_project=%s AND u.family_id=e.family_id AND actor.family_id=e.family_id "
            "AND " + reminders.eligibility() + " AND NOT EXISTS (SELECT 1 FROM account_deletion_jobs j "
            "WHERE j.auth_user_id IN (u.auth_user_id,actor.auth_user_id))", (*claim,config.project)).fetchone()
        if not row:
            return None
    token = config.open(row[0],row[1],token_context(row[3],row[4]))
    # Never derive application data from the event. An in-flight signal is not
    # authority to display details: clients must perform a new authorized read.
    return token,{'kind': 'refresh', 'version': '1'},row[5],row[2]


def finish_delivery(pool, claim, result):
    with _transaction(pool) as conn:
        _limits(conn)
        row = conn.execute("SELECT d.installation_ref,d.installation_generation,d.attempt_count,e.expires_at,"
            "i.generation,i.status,u.family_id,e.family_id,u.id,e.actor_user_id,"
            + reminders.eligibility() + ",EXISTS(SELECT 1 FROM users actor JOIN auth.users a ON a.id=actor.auth_user_id "
            "JOIN auth.users recipient ON recipient.id=u.auth_user_id "
            "WHERE actor.id=e.actor_user_id AND actor.family_id=e.family_id AND NOT EXISTS "
            "(SELECT 1 FROM account_deletion_jobs j WHERE j.auth_user_id IN (u.auth_user_id,actor.auth_user_id))) "
            "FROM native_push_deliveries d JOIN native_push_events e USING(event_ref) "
            "JOIN native_push_installations i USING(installation_ref) JOIN users u ON u.id=d.recipient_user_id "
            "WHERE d.delivery_ref=%s AND d.lease_token=%s AND d.status='leased' AND d.lease_until>clock_timestamp() "
            "FOR UPDATE OF i,d", claim).fetchone()
        if not row:
            return
        now = conn.execute('SELECT clock_timestamp()').fetchone()[0]
        code = result.code
        if row[1] != row[4] or row[5] != 'active':
            code = 'generation_changed'
        elif row[6] != row[7] or not row[10] or not row[11]:
            code = 'identity_unavailable'
        elif row[3] <= now:
            code = 'expired'
        status, next_at = 'failed', None
        if code == 'accepted':
            status = 'accepted'
        elif code in ('generation_changed','identity_unavailable'):
            status = 'cancelled'
        elif code == 'expired':
            status = 'expired'
        elif code in ('rate_limited','provider_unavailable') and row[2] < 4:
            delay = max(result.retry_after, (60 if code == 'rate_limited' else 5) * 2 ** (row[2]-1))
            next_at = now + timedelta(seconds=delay)
            if next_at < row[3]:
                status = 'retry_wait'
            else:
                status,next_at = 'expired',None
        if code == 'unregistered':
            conn.execute("UPDATE native_push_installations SET status='invalid',generation=generation+1,"
                "token_ciphertext=NULL,token_fingerprint=NULL,encryption_key_id=NULL,updated_at=%s "
                "WHERE installation_ref=%s AND generation=%s AND status='active'", (now,row[0],row[1]))
        conn.execute('UPDATE native_push_deliveries SET status=%s,next_attempt_at=%s,lease_token=NULL,lease_until=NULL,'
            'accepted_at=%s,last_error_code=%s,updated_at=%s WHERE delivery_ref=%s AND lease_token=%s',
            (status,next_at,now if status=='accepted' else None,None if code=='accepted' else code,now,*claim))


def challenge_pass(pool, config, provider):
    with _transaction(pool) as conn:
        _limits(conn)
        conn.execute("WITH due AS (SELECT challenge_ref FROM native_push_registration_challenges "
            "WHERE status='pending' AND expires_at<=clock_timestamp() ORDER BY expires_at LIMIT 100 FOR UPDATE SKIP LOCKED) "
            "UPDATE native_push_registration_challenges SET status='expired'," + ERASE +
            " WHERE challenge_ref IN (SELECT challenge_ref FROM due)")
        # A killed pass may have submitted this challenge. Keep it confirmable,
        # but do not resend an uncertain attempt after its lease expires.
        conn.execute("WITH due AS (SELECT challenge_ref FROM native_push_registration_challenges "
            "WHERE status='pending' AND lease_until<=clock_timestamp() "
            "ORDER BY lease_until LIMIT 100 FOR UPDATE SKIP LOCKED) "
            "UPDATE native_push_registration_challenges SET lease_token=NULL,lease_until=NULL,"
            "send_attempts=3,next_attempt_at=expires_at-interval '1 microsecond' "
            "WHERE challenge_ref IN (SELECT challenge_ref FROM due)")
        row = conn.execute("SELECT c.challenge_ref,c.installation_ref,c.user_id,c.candidate_token_ciphertext,"
            "c.encryption_key_id,c.nonce_ciphertext,c.expires_at,i.platform,c.expected_generation "
            "FROM native_push_registration_challenges c JOIN native_push_installations i USING(installation_ref) "
            "JOIN users u ON u.id=c.user_id JOIN auth.users a ON a.id=u.auth_user_id "
            "WHERE c.status='pending' AND c.expires_at>clock_timestamp()+interval '1 second' "
            "AND c.next_attempt_at<=clock_timestamp() AND (c.lease_until IS NULL OR c.lease_until<=clock_timestamp()) "
            "AND c.send_attempts<3 AND i.generation=c.expected_generation AND i.provider_project=%s "
            "AND u.family_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM account_deletion_jobs j WHERE j.auth_user_id=u.auth_user_id) "
            "ORDER BY c.next_attempt_at,c.challenge_ref LIMIT 1 FOR UPDATE OF c SKIP LOCKED", (config.project,)).fetchone()
        if not row:
            return False
        lease = uuid4()
        conn.execute("UPDATE native_push_registration_challenges SET lease_token=%s,"
            "lease_until=LEAST(expires_at,clock_timestamp()+interval '30 seconds'),send_attempts=send_attempts+1 "
            "WHERE challenge_ref=%s", (lease,row[0]))
    try:
        provider.prepare()
        token = config.open(row[3],row[4],token_context(row[2],row[1]))
        nonce = config.open(row[5],row[4],nonce_context(row[2],row[0]))
        with _transaction(pool) as conn:
            _limits(conn)
            valid = conn.execute("SELECT 1 FROM native_push_registration_challenges c "
                "JOIN native_push_installations i USING(installation_ref) JOIN users u ON u.id=c.user_id "
                "JOIN auth.users a ON a.id=u.auth_user_id WHERE c.challenge_ref=%s AND c.lease_token=%s "
                "AND c.status='pending' AND c.expires_at>clock_timestamp() AND c.lease_until>clock_timestamp() "
                "AND i.generation=c.expected_generation AND i.user_id=c.user_id AND i.provider_project=%s "
                "AND u.family_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM account_deletion_jobs j WHERE j.auth_user_id=u.auth_user_id)",
                (row[0],lease,config.project)).fetchone()
        result = provider.send(token, {'kind':'registration_challenge','challenge_ref':str(row[0]),
            'installation_ref':str(row[1]),'nonce':nonce,'generation':str(row[8])},
            expires_at=row[6],platform=row[7]) if valid else Result('identity_unavailable')
    except ConfigurationError:
        result = Result('configuration')
    with _transaction(pool) as conn:
        _limits(conn)
        if result.code in ('accepted','transport_uncertain'):
            # Keep it confirmable, but never resend after ambiguous acceptance.
            conn.execute("UPDATE native_push_registration_challenges SET lease_token=NULL,lease_until=NULL,"
                "send_attempts=3,next_attempt_at=expires_at-interval '1 microsecond' "
                "WHERE challenge_ref=%s AND lease_token=%s AND status='pending'", (row[0],lease))
        elif result.code in ('rate_limited','provider_unavailable'):
            conn.execute("UPDATE native_push_registration_challenges SET lease_token=NULL,lease_until=NULL,"
                "next_attempt_at=LEAST(expires_at-interval '1 microsecond',clock_timestamp()+(%s * interval '1 second')) "
                "WHERE challenge_ref=%s AND lease_token=%s AND status='pending'", (max(60,result.retry_after),row[0],lease))
        else:
            conn.execute("UPDATE native_push_registration_challenges SET status='cancelled'," + ERASE +
                         " WHERE challenge_ref=%s AND lease_token=%s AND status='pending'", (row[0],lease))
    return True


def run_once(pool, config, provider):
    try:
        reminders.schedule(pool, config.project)
    except Exception:
        # Independent transaction: no business write or existing vehicle outbox
        # is rolled back. Next durable poll can retry; never log source contents.
        log.error('native_push_reminder_schedule_failed')
    challenge_pass(pool,config,provider)
    claim = claim_delivery(pool,config.project)
    if claim:
        try:
            provider.prepare()
            payload = delivery_payload(pool,config,claim)
            result = provider.send(payload[0],payload[1],expires_at=payload[2],platform=payload[3]) if payload else Result('identity_unavailable')
        except ConfigurationError:
            result = Result('configuration')
        finish_delivery(pool,claim,result)
    with _transaction(pool) as conn:
        _limits(conn)
        conn.execute("WITH done AS (SELECT e.event_ref FROM native_push_events e WHERE status='pending' "
            "AND NOT EXISTS (SELECT 1 FROM native_push_deliveries d WHERE d.event_ref=e.event_ref "
            "AND d.status IN ('pending','leased','retry_wait')) LIMIT 100 FOR UPDATE OF e SKIP LOCKED) "
            "UPDATE native_push_events SET status=CASE WHEN expires_at<=clock_timestamp() THEN 'expired' ELSE 'complete' END "
            "WHERE event_ref IN (SELECT event_ref FROM done)")


async def _loop(supervisor, stop):
    while not stop.is_set():
        wakeup.clear()
        try:
            outcome = await supervisor.run(stop)
            if outcome in ('failed', 'uncertain'):
                log.error('native_push_worker_pass_' + outcome)
            if supervisor.quarantined:
                return
        except Exception:
            log.error('native_push_worker_pass_failed')
        # No unbounded fan-out. At most one delivery and one challenge per pass.
        for _ in range(20):
            if stop.is_set() or wakeup.is_set():
                break
            await asyncio.sleep(.25)


@asynccontextmanager
async def native_lifespan(app):
    if not enabled():
        yield
        return
    try:
        Config.load()
    except ConfigurationError:
        log.error('native_push_disabled_configuration')
        yield
        return
    from native_push_process import Supervisor
    supervisor,stop = Supervisor(),asyncio.Event()
    task = asyncio.create_task(_loop(supervisor,stop))
    try:
        yield
    finally:
        stop.set()
        await task
        await supervisor.close()
