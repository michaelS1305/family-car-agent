"""Apple step of account_deletion_jobs, not a separate scheduler.

All HTTP happens after the durable attempt transaction. Only fixed diagnostics
and an unrelated random job reference leave this module via logging.
"""
from contextlib import contextmanager
import os
from dataclasses import dataclass, field
import logging
import time
from uuid import UUID

import jwt
import requests

from apple_credentials_security import Config
from deletion_gate import lock_identity

logger = logging.getLogger(__name__)
TERMINAL = frozenset({'revoked', 'not_applicable', 'manual_required'})
CATEGORIES = frozenset({
    'apple_credential_missing', 'apple_credential_mismatch', 'apple_capture_unresolved',
    'apple_decryption_failed', 'apple_client_configuration_invalid',
    'apple_revocation_timeout', 'apple_revocation_network_error',
    'apple_revocation_provider_rejected', 'apple_revocation_confirmed',
    'apple_manual_operator_resolution', 'supabase_auth_deletion_failed',
    'supabase_auth_verification_failed', 'deletion_finalization_failed',
    'deletion_cleanup_failed', 'deletion_preparation_failed',
    'apple_revocation_internal_error',
})
OPERATIONS = frozenset({'prepare', 'apple_revoke', 'application_cleanup',
                        'supabase_auth_delete', 'supabase_auth_verify', 'finalize', 'completed'})
ATTENTION = frozenset({'apple_credential_mismatch', 'apple_decryption_failed',
                       'apple_client_configuration_invalid', 'apple_revocation_provider_rejected'})


@dataclass(frozen=True)
class Attempt:
    owner: str = field(repr=False)
    job: UUID
    number: int


@contextmanager
def transaction(pool, owner):
    with pool.connection() as conn:
        conn.execute("SET LOCAL lock_timeout='3s'")
        conn.execute("SET LOCAL statement_timeout='10s'")
        lock_identity(conn, owner, exclusive=True)
        yield conn


def emit(job, operation, state, category=None):
    """Do not let logging handlers affect committed results; no raw values."""
    if operation not in OPERATIONS or state not in TERMINAL | {'unclassified', 'pending'}:
        return
    if category is not None and category not in CATEGORIES:
        return
    try:
        reference = str(UUID(str(job)))
        logger.warning('operation=account_deletion step=%s job_ref=%s apple_state=%s category=%s',
                    operation, reference, state, category or 'none')
    except Exception:
        pass


def begin(pool, owner):
    with transaction(pool, owner) as conn:
        row = conn.execute('''UPDATE account_deletion_jobs SET attempt_count=attempt_count+1,
            last_attempt_at=clock_timestamp(), last_operation='prepare'
            WHERE auth_user_id=%s RETURNING job_ref,attempt_count''', (owner,)).fetchone()
    return Attempt(str(owner), row[0], row[1]) if row else None


def note(pool, attempt, operation, category=None):
    if operation not in OPERATIONS or (category is not None and category not in CATEGORIES):
        raise ValueError('invalid deletion diagnostic')
    with transaction(pool, attempt.owner) as conn:
        row = conn.execute('''UPDATE account_deletion_jobs SET last_operation=%s,
            failure_category=COALESCE(%s,failure_category),
            operator_attention=CASE WHEN %s::text IS NULL THEN operator_attention ELSE %s END
            WHERE job_ref=%s AND attempt_count=%s
              AND (%s <> 'apple_revoke' OR apple_state='pending') RETURNING apple_state''',
            (operation, category, category, category in ATTENTION, attempt.job, attempt.number, operation)).fetchone()
    if row:
        emit(attempt.job, operation, row[0], category)
    return bool(row)


def _credential(conn, owner):
    return conn.execute('''SELECT c.environment,c.client_id,c.apple_subject,c.generation,
        c.key_id,c.refresh_ciphertext,a.auth_user_id,a.status FROM apple_credentials c
        LEFT JOIN apple_credential_attempts a ON a.generation=c.generation
        WHERE c.auth_user_id=%s''', (owner,)).fetchone()


def expected_identity():
    # This check needs no private key so non-Apple deletion remains available.
    return {
        'https://jouhqvbxhsvkluwkqmdg.supabase.co': ('dev', 'com.familycaragent.app.dev'),
        'https://xrgijytfigcuxmdktvmd.supabase.co': ('prod', 'com.familycaragent.app'),
    }.get(os.environ.get('SUPABASE_URL', '').rstrip('/'))


def _valid_credential(row, owner):
    return bool(row and (row[0], row[1]) in {('dev', 'com.familycaragent.app.dev'),
                                                ('prod', 'com.familycaragent.app')}
                and row[:2] == expected_identity()
                and isinstance(row[2], str) and row[2] and row[3] > 0
                and str(row[6]) == str(owner) and row[7] == 'stored')


def _identity_matches(conn, owner, credential):
    # Revalidate the source of a previous mismatch, not its historical diagnostic.
    # After Auth is already absent, recovery relies on the Stage 1 stored binding
    # and authenticated ciphertext, as in initial classification.
    if not conn.execute('SELECT 1 FROM auth.users WHERE id=%s', (owner,)).fetchone():
        return True
    identities = conn.execute("SELECT provider_id,identity_data->>'sub' FROM auth.identities "
                              "WHERE user_id=%s AND provider='apple'", (owner,)).fetchall()
    return identities == [(credential[2], credential[2])]


def prepare(pool, attempt):
    """The existing identity fence prevents any later capture finish or begin.

    Pending capture attempts may have issued tokens we never obtained. They are
    NOT evidence of revocation. Preserve that uncertainty through finalization.
    """
    with transaction(pool, attempt.owner) as conn:
        job = conn.execute('''SELECT apple_state FROM account_deletion_jobs
            WHERE job_ref=%s AND attempt_count=%s FOR UPDATE''',
            (attempt.job, attempt.number)).fetchone()
        if not job:
            return False
        if job[0] != 'unclassified':
            return True
        identities = conn.execute("SELECT provider_id,identity_data->>'sub' FROM auth.identities "
                                  "WHERE user_id=%s AND provider='apple'", (attempt.owner,)).fetchall()
        credential = _credential(conn, attempt.owner)
        uncertain = bool(conn.execute("SELECT 1 FROM apple_credential_attempts WHERE auth_user_id=%s "
                                     "AND status='pending' LIMIT 1", (attempt.owner,)).fetchone())
        auth_exists = bool(conn.execute('SELECT 1 FROM auth.users WHERE id=%s', (attempt.owner,)).fetchone())
        generation = credential[3] if credential else None
        category = None
        has_attempts = bool(conn.execute('SELECT 1 FROM apple_credential_attempts WHERE auth_user_id=%s LIMIT 1',
                                        (attempt.owner,)).fetchone())
        if not identities and not credential and not has_attempts and auth_exists:
            state = 'not_applicable'
        elif not credential:
            state, category = 'manual_required', 'apple_credential_missing'
        else:
            state = 'pending'
            if (not _valid_credential(credential, attempt.owner)
                    or (auth_exists and identities != [(credential[2], credential[2])])):
                category = 'apple_credential_mismatch'
        conn.execute('''UPDATE account_deletion_jobs SET apple_state=%s,apple_generation=%s,
            apple_capture_uncertain=%s,failure_category=%s,operator_attention=%s,apple_resolution_reason=%s
            WHERE job_ref=%s AND attempt_count=%s''',
            (state, generation, uncertain, category, category in ATTENTION,
             category if state == 'manual_required' else None, attempt.job, attempt.number))
    emit(attempt.job, 'prepare', state, category)
    return True


def revoke(config, token, *, http=None):
    """200 includes already-invalidated tokens. All other outcomes are failures.

    Never consume/log a provider body, and never follow redirects or use proxy
    environment credentials. stream=True bounds response processing to headers.
    """
    now = int(time.time())
    secret = jwt.encode({'iss': config.team, 'iat': now, 'exp': now + 300,
                         'aud': 'https://appleid.apple.com', 'sub': config.client},
                        config.private_key, algorithm='ES256', headers={'kid': config.kid})
    try:
        with (http or requests.Session()) as session:
            session.trust_env = False
            with session.post('https://appleid.apple.com/auth/revoke', data={
                    'client_id': config.client, 'client_secret': secret, 'token': token,
                    'token_type_hint': 'refresh_token'}, timeout=(5, 10),
                    allow_redirects=False, stream=True) as response:
                return ('apple_revocation_confirmed' if response.status_code == 200
                        else 'apple_revocation_provider_rejected')
    except requests.Timeout:
        return 'apple_revocation_timeout'
    except requests.RequestException:
        return 'apple_revocation_network_error'


def advance(pool, attempt):
    with transaction(pool, attempt.owner) as conn:
        job = conn.execute('''SELECT apple_state,apple_generation,apple_capture_uncertain,failure_category,apple_resolution_reason
            FROM account_deletion_jobs WHERE job_ref=%s AND attempt_count=%s FOR UPDATE''',
            (attempt.job, attempt.number)).fetchone()
        if not job:
            return False
        credential = _credential(conn, attempt.owner)
        if job[0] == 'manual_required':
            if job[4] in {'apple_credential_missing', 'apple_capture_unresolved', 'apple_manual_operator_resolution'}:
                return True
            category = 'apple_credential_mismatch'
        elif job[0] == 'not_applicable':
            if not credential and not conn.execute(
                    'SELECT 1 FROM apple_credential_attempts WHERE auth_user_id=%s',
                    (attempt.owner,)).fetchone():
                return True
            category = 'apple_credential_mismatch'
        elif job[0] == 'revoked':
            if _valid_credential(credential, attempt.owner) and credential[3] == job[1]:
                return True
            category = 'apple_credential_mismatch'
        elif (job[0] != 'pending'
                or not _valid_credential(credential, attempt.owner) or credential[3] != job[1]
                or not _identity_matches(conn, attempt.owner, credential)):
            category = 'apple_credential_mismatch'
        else:
            category = None
    if category:
        note(pool, attempt, 'prepare', category)
        return False
    try:
        config = Config.load()
    except Exception:
        note(pool, attempt, 'apple_revoke', 'apple_client_configuration_invalid')
        return False
    if config.environment != credential[0] or config.client != credential[1]:
        note(pool, attempt, 'apple_revoke', 'apple_credential_mismatch')
        return False
    try:
        token = config.open(credential[5], credential[4], attempt.owner, credential[2], credential[3])
        if not 1 <= len(token) <= 8192:
            raise ValueError()
    except Exception:
        note(pool, attempt, 'apple_revoke', 'apple_decryption_failed')
        return False
    # Persist operation BEFORE external I/O; failure prevents dispatch.
    if not note(pool, attempt, 'apple_revoke'):
        return False
    category = revoke(config, token)
    if category != 'apple_revocation_confirmed':
        note(pool, attempt, 'apple_revoke', category)
        return False
    with transaction(pool, attempt.owner) as conn:
        # Owner + version + attempt fencing. A stale success is retried safely;
        # neither stale success nor stale failure can overwrite a newer decision.
        row = conn.execute('''UPDATE account_deletion_jobs j SET
            apple_state=CASE WHEN apple_capture_uncertain THEN 'manual_required' ELSE 'revoked' END,
            apple_confirmed_at=clock_timestamp(),
            apple_resolution_reason=CASE WHEN apple_capture_uncertain THEN 'apple_capture_unresolved' ELSE NULL END,
            failure_category=CASE WHEN apple_capture_uncertain THEN 'apple_capture_unresolved'
                                  ELSE 'apple_revocation_confirmed' END,
            operator_attention=false
            WHERE j.job_ref=%s AND j.attempt_count=%s AND j.apple_state='pending'
              AND j.apple_generation=%s
              AND EXISTS(SELECT 1 FROM apple_credentials c WHERE c.auth_user_id=j.auth_user_id
                         AND c.generation=j.apple_generation)
            RETURNING apple_state,failure_category''',
            (attempt.job, attempt.number, credential[3])).fetchone()
    if row:
        emit(attempt.job, 'apple_revoke', row[0], row[1])
    return bool(row)


def finalize(pool, attempt):
    with transaction(pool, attempt.owner) as conn:
        row = conn.execute('''SELECT phase,apple_state,apple_generation,apple_resolution_reason FROM account_deletion_jobs
            WHERE job_ref=%s AND attempt_count=%s FOR UPDATE''',
            (attempt.job, attempt.number)).fetchone()
        if not row or row[0] != 'auth_pending' or row[1] not in TERMINAL:
            return False
        if row[1] == 'manual_required' and row[3] not in {
                'apple_credential_missing', 'apple_capture_unresolved', 'apple_manual_operator_resolution'}:
            raise ValueError('deletion manual resolution invariant')
        if conn.execute('SELECT 1 FROM auth.users WHERE id=%s', (attempt.owner,)).fetchone():
            return False
        credential = _credential(conn, attempt.owner)
        if row[1] == 'revoked' and (not _valid_credential(credential, attempt.owner)
                                      or credential[3] != row[2]):
            raise ValueError('deletion finalization invariant')
        if row[1] == 'not_applicable' and (credential or conn.execute(
                'SELECT 1 FROM apple_credential_attempts WHERE auth_user_id=%s',
                (attempt.owner,)).fetchone()):
            raise ValueError('deletion finalization invariant')
        conn.execute('DELETE FROM apple_credentials WHERE auth_user_id=%s', (attempt.owner,))
        conn.execute('DELETE FROM apple_credential_attempts WHERE auth_user_id=%s', (attempt.owner,))
        conn.execute('DELETE FROM account_deletion_jobs WHERE job_ref=%s AND attempt_count=%s',
                     (attempt.job, attempt.number))
    emit(attempt.job, 'completed', row[1])
    return True
