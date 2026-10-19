"""Transactional Native Push ownership. Caller owns commit; no provider I/O.

Installation ownership never transfers. Account switch must revoke under the old
identity and use a new installation reference under the new identity.
"""
from datetime import timedelta
import hmac
import secrets
from uuid import uuid4

from deletion_gate import IdentityUnavailable, require_auth
from native_push_security import ConfigurationError, nonce_hash, nonce_context, token_context

ERASE = ("candidate_token_ciphertext=NULL,candidate_fingerprint=NULL,encryption_key_id=NULL,"
         "nonce_hash=NULL,nonce_ciphertext=NULL,next_attempt_at=NULL,lease_token=NULL,lease_until=NULL")


def scope(conn, user):
    require_auth(conn, user.auth_user_id)
    # Separate namespace; serialize same-owner quotas, confirmations and revokes.
    conn.execute('SELECT pg_advisory_xact_lock(1178814544,%s)', (user.user_id,))
    if not conn.execute('SELECT 1 FROM users WHERE id=%s AND auth_user_id=%s AND family_id=%s FOR SHARE',
                        (user.user_id, user.auth_user_id, user.family_id)).fetchone():
        raise IdentityUnavailable()


def response(code, **values):
    return {'code': code, **values}


def key_cohort(conn, config):
    """Fail closed on key drift; no silent fingerprint-uniqueness bypass.

    Keys are one immutable cohort per provider project in this version. Rotation
    requires revoking existing active installations, then re-registering them.
    """
    if conn.execute("SELECT 1 FROM native_push_installations WHERE provider_project=%s "
                    "AND status='active' AND encryption_key_id<>%s LIMIT 1", (config.project,config.key_id)).fetchone():
        raise ConfigurationError()
    sample = conn.execute("SELECT user_id,installation_ref,token_ciphertext,encryption_key_id,token_fingerprint "
        "FROM native_push_installations WHERE provider_project=%s AND status='active' LIMIT 1", (config.project,)).fetchone()
    if sample:
        token = config.open(sample[2],sample[3],token_context(sample[0],sample[1]))
        if not hmac.compare_digest(config.fingerprint(token),bytes(sample[4])):
            raise ConfigurationError()


def begin(conn, user, config, *, installation_ref, request_id, platform, token):
    scope(conn, user)
    key_cohort(conn,config)
    now = conn.execute('SELECT clock_timestamp()').fetchone()[0]
    fingerprint = config.fingerprint(token)
    previous = conn.execute(
        'SELECT challenge_ref,installation_ref,status,candidate_fingerprint,expires_at '
        'FROM native_push_registration_challenges WHERE user_id=%s AND request_id=%s',
        (user.user_id, request_id)).fetchone()
    if previous:
        if previous[1] != installation_ref or (previous[3] is not None and
                                              not hmac.compare_digest(bytes(previous[3]), fingerprint)):
            return response('REGISTRATION_UNAVAILABLE')
        return response('CHALLENGE_EXISTS', challenge_ref=str(previous[0]), status=previous[2])
    # Keep terminal rows as rate-limit evidence; no deletion on revoke/rotation.
    recent = conn.execute('SELECT count(*) FROM native_push_registration_challenges '
        "WHERE user_id=%s AND created_at>%s-interval '10 minutes'", (user.user_id, now)).fetchone()[0]
    if recent >= 10:
        return response('RATE_LIMITED')
    conn.execute("UPDATE native_push_registration_challenges SET status='expired'," + ERASE +
                 " WHERE user_id=%s AND status='pending' AND expires_at<=%s", (user.user_id, now))
    installation = conn.execute('SELECT user_id,platform,provider_project,generation,status '
        'FROM native_push_installations WHERE installation_ref=%s FOR UPDATE', (installation_ref,)).fetchone()
    if installation and (installation[0] != user.user_id or installation[1] != platform
                         or installation[2] != config.project):
        return response('REGISTRATION_UNAVAILABLE')
    if not installation:
        count = conn.execute('SELECT count(*) FROM native_push_installations WHERE user_id=%s',
                             (user.user_id,)).fetchone()[0]
        if count >= 20:
            return response('INSTALLATION_LIMIT')
        # Race on an arbitrary ref: ON CONFLICT followed by non-enumerating refusal.
        made = conn.execute("INSERT INTO native_push_installations (installation_ref,user_id,platform,provider,"
            "provider_project,generation,status) VALUES(%s,%s,%s,'fcm',%s,1,'pending') "
            "ON CONFLICT DO NOTHING RETURNING generation", (installation_ref,user.user_id,platform,config.project)).fetchone()
        if not made:
            return response('REGISTRATION_UNAVAILABLE')
        generation = 1
    else:
        generation = installation[3]
    pending = conn.execute("SELECT count(*) FROM native_push_registration_challenges WHERE user_id=%s "
                           "AND status='pending' AND installation_ref<>%s", (user.user_id, installation_ref)).fetchone()[0]
    if pending >= 5:
        return response('RATE_LIMITED')
    conn.execute("UPDATE native_push_registration_challenges SET status='cancelled'," + ERASE +
                 " WHERE installation_ref=%s AND user_id=%s AND status='pending'", (installation_ref,user.user_id))
    ref, nonce = uuid4(), secrets.token_urlsafe(32)
    conn.execute('INSERT INTO native_push_registration_challenges '
        '(challenge_ref,installation_ref,user_id,request_id,expected_generation,candidate_token_ciphertext,'
        'candidate_fingerprint,encryption_key_id,nonce_hash,nonce_ciphertext,status,created_at,expires_at,next_attempt_at) '
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s)",
        (ref,installation_ref,user.user_id,request_id,generation,
         config.seal(token,token_context(user.user_id,installation_ref)),fingerprint,config.key_id,
         nonce_hash(nonce),config.seal(nonce,nonce_context(user.user_id,ref)),now,now+timedelta(minutes=2),now))
    return response('CHALLENGE_PENDING', challenge_ref=str(ref), expected_generation=generation,
                    expires_at=(now+timedelta(minutes=2)).isoformat())


def confirm(conn, user, config, *, installation_ref, challenge_ref, nonce):
    scope(conn, user)
    installation = conn.execute('SELECT generation,status FROM native_push_installations '
        'WHERE installation_ref=%s AND user_id=%s AND provider_project=%s FOR UPDATE',
        (installation_ref,user.user_id,config.project)).fetchone()
    if not installation:
        return response('REGISTRATION_UNAVAILABLE')
    challenge = conn.execute('SELECT status,expected_generation,expires_at,verify_attempts,nonce_hash,'
        'candidate_token_ciphertext,candidate_fingerprint,encryption_key_id,activated_generation '
        'FROM native_push_registration_challenges WHERE challenge_ref=%s AND installation_ref=%s AND user_id=%s FOR UPDATE',
        (challenge_ref,installation_ref,user.user_id)).fetchone()
    if not challenge:
        return response('REGISTRATION_UNAVAILABLE')
    status,generation,expires,attempts,hashed,cipher,fingerprint,key_id,activated = challenge
    if status == 'consumed':
        if activated == installation[0] and installation[1] == 'active':
            return response('ACTIVE', generation=activated)
        return response('REGISTRATION_UNAVAILABLE')
    if status != 'pending':
        return response('REGISTRATION_UNAVAILABLE')
    now = conn.execute('SELECT clock_timestamp()').fetchone()[0]
    if expires <= now or generation != installation[0] or attempts >= 5:
        conn.execute("UPDATE native_push_registration_challenges SET status=%s," + ERASE +
            ' WHERE challenge_ref=%s', ('expired' if expires <= now else 'cancelled',challenge_ref))
        return response('REGISTRATION_UNAVAILABLE')
    conn.execute('UPDATE native_push_registration_challenges SET verify_attempts=verify_attempts+1 WHERE challenge_ref=%s',
                 (challenge_ref,))
    if not hmac.compare_digest(bytes(hashed),nonce_hash(nonce)):
        if attempts + 1 >= 5:
            conn.execute("UPDATE native_push_registration_challenges SET status='cancelled'," + ERASE +
                         ' WHERE challenge_ref=%s', (challenge_ref,))
        return response('REGISTRATION_UNAVAILABLE')
    key_cohort(conn,config)
    candidate = config.open(cipher,key_id,token_context(user.user_id,installation_ref))
    if not hmac.compare_digest(config.fingerprint(candidate),bytes(fingerprint)):
        raise ConfigurationError()
    # Serialize activation by fingerprint (not by candidate token registration).
    key = int.from_bytes(bytes(fingerprint)[:4], 'big', signed=True)
    conn.execute('SELECT pg_advisory_xact_lock(1178814545,%s)', (key,))
    if conn.execute("SELECT 1 FROM native_push_installations WHERE provider_project=%s AND token_fingerprint=%s "
                    "AND status='active' AND installation_ref<>%s", (config.project,fingerprint,installation_ref)).fetchone():
        conn.execute("UPDATE native_push_registration_challenges SET status='cancelled'," + ERASE +
                     ' WHERE challenge_ref=%s', (challenge_ref,))
        return response('REGISTRATION_UNAVAILABLE')
    conn.execute("UPDATE native_push_installations SET generation=generation+1,status='active',"
        'token_ciphertext=%s,token_fingerprint=%s,encryption_key_id=%s,verified_at=%s,revoked_at=NULL,'
        'updated_at=%s,last_seen_at=%s WHERE installation_ref=%s AND user_id=%s',
        (cipher,fingerprint,key_id,now,now,now,installation_ref,user.user_id))
    conn.execute("UPDATE native_push_registration_challenges SET status='consumed',activated_generation=%s," + ERASE +
                 ' WHERE challenge_ref=%s', (generation+1,challenge_ref))
    return response('ACTIVE', generation=generation+1)


def revoke(conn, user, config, installation_ref, expected_generation):
    scope(conn,user)
    changed = conn.execute("UPDATE native_push_installations SET status='revoked',generation=generation+1,"
        'token_ciphertext=NULL,token_fingerprint=NULL,encryption_key_id=NULL,revoked_at=clock_timestamp(),'
        "updated_at=clock_timestamp() WHERE installation_ref=%s AND user_id=%s AND generation=%s "
        "AND provider_project=%s AND status<>'revoked' RETURNING installation_ref",
        (installation_ref,user.user_id,expected_generation,config.project)).fetchone()
    if changed:
        conn.execute("UPDATE native_push_registration_challenges SET status='cancelled'," + ERASE +
            " WHERE installation_ref=%s AND user_id=%s AND status='pending'", (installation_ref,user.user_id))
    return response('REVOKED' if changed else 'REGISTRATION_UNAVAILABLE')
