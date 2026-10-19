"""Durable source polling, inside the existing bounded push worker only.

No business transaction depends on this module. PostgreSQL unique keys arbitrate
concurrent passes. All content remains behind the installation-bound inbox.
"""
import os
from uuid import uuid4


def enabled():
    # Rollout gate: deploy the manual migration before enabling on Dev.
    return (os.getenv('NATIVE_PUSH_ENABLED', '').lower() == 'true' and
            os.getenv('NATIVE_PUSH_REMINDERS_ENABLED', '').lower() == 'true')


# The aliases e (event) and d (delivery) are shared by worker and inbox queries.
# Re-read the authoritative source; an outbox snapshot is never authorization.
ELIGIBLE = """(
 (e.event_type IN ('vehicle_taken','vehicle_returned') AND d.recipient_user_id<>e.actor_user_id)
 OR (e.event_type='reservation_reminder' AND d.recipient_user_id=e.actor_user_id
     AND EXISTS (SELECT 1 FROM reservations r WHERE r.reservation_ref=e.reservation_ref
       AND r.user_id=d.recipient_user_id AND r.vehicle_id=e.vehicle_id AND r.status='active'
       AND (r.start_time::timestamp AT TIME ZONE 'Asia/Jerusalem')=e.scheduled_for
       AND e.scheduled_for>clock_timestamp())
     AND EXISTS (SELECT 1 FROM vehicles rv WHERE rv.id=e.vehicle_id AND rv.retired_at IS NULL))
 OR (e.event_type='maintenance_reminder' AND d.recipient_user_id=e.actor_user_id
     AND EXISTS (SELECT 1 FROM vehicle_maintenance m JOIN vehicles mv ON mv.id=m.vehicle_id
       JOIN families f ON f.id=mv.family_id WHERE m.maintenance_ref=e.maintenance_ref
       AND m.vehicle_id=e.vehicle_id AND mv.family_id=e.family_id AND mv.retired_at IS NULL
       AND f.created_by_user_id=d.recipient_user_id AND NOT m.completed
       AND (m.scheduled_date::timestamp AT TIME ZONE 'Asia/Jerusalem')=e.scheduled_for
       AND e.scheduled_for>clock_timestamp()))
)"""


def eligibility():
    return ELIGIBLE if enabled() else "d.recipient_user_id<>e.actor_user_id"


def schedule(pool, project):
    if not enabled():
        return
    with pool.connection() as conn:
        conn.execute("SET LOCAL statement_timeout='3s'")
        conn.execute("SET LOCAL lock_timeout='1s'")
        # Bounded, nonblocking single producer pass. Delivery workers remain concurrent.
        if not conn.execute('SELECT pg_try_advisory_xact_lock(1178686280)').fetchone()[0]:
            return
        sources = conn.execute("""
            WITH sources AS (
              SELECT 'reservation_reminder' AS kind,r.reservation_ref AS ref,r.user_id AS recipient,
                v.id AS vehicle,v.family_id,
                r.start_time::timestamp AT TIME ZONE 'Asia/Jerusalem' AS scheduled,
                (r.start_time::timestamp AT TIME ZONE 'Asia/Jerusalem')-interval '1 hour' AS due
              FROM reservations r JOIN vehicles v ON v.id=r.vehicle_id
              WHERE r.status='active' AND v.retired_at IS NULL
              UNION ALL
              SELECT 'maintenance_reminder',m.maintenance_ref,f.created_by_user_id,v.id,v.family_id,
                m.scheduled_date::timestamp AT TIME ZONE 'Asia/Jerusalem',
                (m.scheduled_date-1+time '09:00') AT TIME ZONE 'Asia/Jerusalem'
              FROM vehicle_maintenance m JOIN vehicles v ON v.id=m.vehicle_id
              JOIN families f ON f.id=v.family_id WHERE NOT m.completed AND v.retired_at IS NULL
            ) SELECT s.kind,s.ref,s.recipient,s.vehicle,s.family_id,s.scheduled
            FROM sources s JOIN users u ON u.id=s.recipient AND u.family_id=s.family_id
            JOIN auth.users a ON a.id=u.auth_user_id
            WHERE s.due<=statement_timestamp() AND s.scheduled>statement_timestamp()
              AND NOT EXISTS (SELECT 1 FROM account_deletion_jobs j WHERE j.auth_user_id=u.auth_user_id)
              AND EXISTS (SELECT 1 FROM native_push_installations i WHERE i.user_id=s.recipient
                AND i.status='active' AND i.provider_project=%s)
              AND NOT EXISTS (SELECT 1 FROM native_push_events e WHERE e.event_type=s.kind
                AND COALESCE(e.reservation_ref,e.maintenance_ref)=s.ref
                AND e.scheduled_for=s.scheduled AND e.actor_user_id=s.recipient AND e.vehicle_id=s.vehicle)
            ORDER BY s.scheduled,s.ref LIMIT 50
            """, (project,)).fetchall()
        for kind, ref, recipient, vehicle, family, scheduled in sources:
            event = uuid4()
            key = ('native_push_events_reservation_occurrence_key' if kind=='reservation_reminder'
                   else 'native_push_events_maintenance_occurrence_key')
            row = conn.execute("""INSERT INTO native_push_events
                (event_ref,family_id,actor_user_id,vehicle_id,event_type,occurred_at,expires_at,status,
                 reservation_ref,maintenance_ref,scheduled_for)
                SELECT %s,%s,%s,%s,%s,statement_timestamp(),
                  LEAST(statement_timestamp()+interval '5 minutes',%s),'pending',%s,%s,%s
                WHERE %s>statement_timestamp()
                ON CONFLICT ON CONSTRAINT """ + key + " DO NOTHING RETURNING event_ref",
                (event,family,recipient,vehicle,kind,scheduled,
                 ref if kind=='reservation_reminder' else None,
                 ref if kind=='maintenance_reminder' else None,scheduled,scheduled)).fetchone()
            if row:
                conn.execute("""INSERT INTO native_push_deliveries
                    (delivery_ref,event_ref,installation_ref,recipient_user_id,installation_generation,
                     status,next_attempt_at,created_at,updated_at)
                    SELECT gen_random_uuid(),%s,installation_ref,user_id,generation,'pending',
                      statement_timestamp(),statement_timestamp(),statement_timestamp()
                    FROM native_push_installations WHERE user_id=%s AND status='active' AND provider_project=%s
                    """, (event,recipient,project))
