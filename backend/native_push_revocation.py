"""iOS-only, terminal, installation-scoped cancellation authority.

The caller owns the transaction. No bearer credentials are retained here.
Preparation precedes registration, so cancellation can win even before begin.
"""
import hashlib
import hmac

from native_push_registration import ERASE, response, scope


def digest(secret):
    return hashlib.sha256(b'fca-ios-push-revocation-v1\0' + secret.encode('ascii')).digest()


def prepare(conn, user, config, installation_ref, secret):
    if config.environment != 'dev':
        return response('REGISTRATION_UNAVAILABLE')
    scope(conn, user)
    # Do not attach cancellation authority to any existing installation.
    row = conn.execute('SELECT user_id,secret_hash,revoked_at FROM native_push_ios_revocations '
                       'WHERE installation_ref=%s FOR UPDATE', (installation_ref,)).fetchone()
    if row:
        if row[0] == user.user_id and hmac.compare_digest(bytes(row[1]), digest(secret)) and row[2] is None:
            return response('PREPARED')
        return response('REGISTRATION_UNAVAILABLE')
    if conn.execute('SELECT 1 FROM native_push_installations WHERE installation_ref=%s',
                    (installation_ref,)).fetchone():
        return response('REGISTRATION_UNAVAILABLE')
    if conn.execute('SELECT count(*) FROM native_push_ios_revocations WHERE user_id=%s '
                    'AND created_at>clock_timestamp()-interval \'10 minutes\'',
                    (user.user_id,)).fetchone()[0] >= 10:
        return response('RATE_LIMITED')
    # Includes prepared authorities whose registration has not arrived yet.
    if conn.execute('SELECT count(*) FROM native_push_ios_revocations WHERE user_id=%s AND revoked_at IS NULL',
                    (user.user_id,)).fetchone()[0] >= 20:
        return response('INSTALLATION_LIMIT')
    made = conn.execute('INSERT INTO native_push_ios_revocations '
        '(installation_ref,user_id,provider_project,secret_hash) VALUES(%s,%s,%s,%s) '
        'ON CONFLICT DO NOTHING RETURNING installation_ref',
        (installation_ref,user.user_id,config.project,digest(secret))).fetchone()
    return response('PREPARED' if made else 'REGISTRATION_UNAVAILABLE')


def permitted(conn, user_id, project, installation_ref):
    # Held through begin/confirm commit; cancel takes the same row lock.
    return conn.execute('SELECT 1 FROM native_push_ios_revocations WHERE installation_ref=%s '
        'AND user_id=%s AND provider_project=%s AND revoked_at IS NULL FOR UPDATE',
        (installation_ref,user_id,project)).fetchone() is not None


def cancel(conn, config, installation_ref, secret):
    if config.environment != 'dev':
        return response('REGISTRATION_UNAVAILABLE')
    # Authenticate before acquiring the shared per-owner serialization lock.
    row = conn.execute('SELECT user_id,secret_hash FROM native_push_ios_revocations '
        'WHERE installation_ref=%s AND provider_project=%s', (installation_ref,config.project)).fetchone()
    if not row or not hmac.compare_digest(bytes(row[1]), digest(secret)):
        return response('REGISTRATION_UNAVAILABLE')
    conn.execute('SELECT pg_advisory_xact_lock(1178814544,%s)', (row[0],))
    conn.execute('UPDATE native_push_ios_revocations SET revoked_at=COALESCE(revoked_at,clock_timestamp()) '
                 'WHERE installation_ref=%s', (installation_ref,))
    conn.execute("UPDATE native_push_installations SET status='revoked',generation=generation+1,"
        'token_ciphertext=NULL,token_fingerprint=NULL,encryption_key_id=NULL,revoked_at=clock_timestamp(),'
        "updated_at=clock_timestamp() WHERE installation_ref=%s AND user_id=%s AND platform='ios' "
        "AND provider_project=%s AND status<>'revoked'", (installation_ref,row[0],config.project))
    conn.execute("UPDATE native_push_registration_challenges SET status='cancelled'," + ERASE +
        " WHERE installation_ref=%s AND user_id=%s AND status='pending' AND EXISTS "
        "(SELECT 1 FROM native_push_installations i WHERE i.installation_ref=native_push_registration_challenges.installation_ref "
        "AND i.platform='ios')", (installation_ref,row[0]))
    return response('REVOKED')
