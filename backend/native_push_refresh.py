"""Installation-bound short-lived inbox. Caller owns the transaction."""
from deletion_gate import require_auth, IdentityUnavailable
from vehicle_admission import CAR_TRANSITION_LOCK_NAMESPACE


class RefreshError(Exception):
    def __init__(self, code, status=403):
        self.code, self.status = code, status
        super().__init__(code)


def events(conn, user, config, installation_ref, expected_generation, limit=20, cursor=None):
    if not 1 <= limit <= 50 or expected_generation < 1:
        raise RefreshError('INVALID_NATIVE_PUSH_REQUEST', 422)
    require_auth(conn, user.auth_user_id)
    if user.family_id is None:
        raise IdentityUnavailable()
    # Established identity -> family -> user/installation lock order. Revocation
    # takes the installation row exclusively; no network occurs under these locks.
    conn.execute('SELECT pg_advisory_xact_lock(%s,%s)', (CAR_TRANSITION_LOCK_NAMESPACE, user.family_id))
    if not conn.execute('SELECT id FROM families WHERE id=%s FOR SHARE', (user.family_id,)).fetchone():
        raise IdentityUnavailable()
    if not conn.execute('SELECT 1 FROM users WHERE id=%s AND auth_user_id=%s AND family_id=%s FOR SHARE',
                        (user.user_id, user.auth_user_id, user.family_id)).fetchone():
        raise IdentityUnavailable()
    if not conn.execute("SELECT 1 FROM native_push_installations WHERE installation_ref=%s AND user_id=%s "
                        "AND generation=%s AND status='active' AND provider_project=%s FOR SHARE",
                        (installation_ref, user.user_id, expected_generation, config.project)).fetchone():
        raise RefreshError('NATIVE_PUSH_ACCESS_DENIED')
    scope = (" FROM native_push_events e JOIN native_push_deliveries d USING(event_ref) "
             "JOIN users actor ON actor.id=e.actor_user_id JOIN auth.users a ON a.id=actor.auth_user_id "
             "JOIN vehicles v ON v.id=e.vehicle_id AND v.family_id=e.family_id "
             "WHERE d.installation_ref=%s AND d.recipient_user_id=%s AND d.installation_generation=%s "
             "AND e.family_id=%s AND actor.family_id=e.family_id AND e.actor_user_id<>%s "
             "AND e.status IN ('pending','complete') AND e.expires_at>clock_timestamp() "
             "AND NOT EXISTS (SELECT 1 FROM account_deletion_jobs j WHERE j.auth_user_id=actor.auth_user_id) ")
    params = (installation_ref, user.user_id, expected_generation, user.family_id, user.user_id)
    boundary, extra = '', ()
    if cursor is not None:
        row = conn.execute('SELECT e.occurred_at,e.event_ref' + scope + 'AND e.event_ref=%s', (*params, cursor)).fetchone()
        if not row:
            raise RefreshError('INVALID_NATIVE_PUSH_CURSOR', 422)
        boundary, extra = 'AND (e.occurred_at,e.event_ref)<(%s,%s) ', tuple(row)
    rows = conn.execute('SELECT e.event_ref,e.event_type,e.occurred_at,e.expires_at,actor.name,v.vehicle_ref,v.display_name' +
                        scope + boundary + 'ORDER BY e.occurred_at DESC,e.event_ref DESC LIMIT %s',
                        (*params, *extra, limit + 1)).fetchall()
    items = [dict(event_ref=str(ref), type=kind, occurred_at=occurred.isoformat(), expires_at=expires.isoformat(),
                  actor_name=name, vehicle_ref=str(vehicle), vehicle_name=display)
             for ref, kind, occurred, expires, name, vehicle, display in rows[:limit]]
    more = len(rows) > limit
    return dict(items=items, has_more=more, next_cursor=items[-1]['event_ref'] if more else None)
