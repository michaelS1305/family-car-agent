"""Incremental operational cleanup; never deletes installation/replay tombstones."""
import os
from native_push_registration import ERASE


def batch_size():
    try:
        return min(100, max(1, int(os.getenv('NATIVE_PUSH_CLEANUP_BATCH', '50'))))
    except ValueError:
        return 50


def cleanup(pool):
    size = batch_size()
    with pool.connection() as conn:
        conn.execute("SET LOCAL lock_timeout='250ms'")
        conn.execute("SET LOCAL statement_timeout='2s'")
        conn.execute("WITH due AS (SELECT challenge_ref FROM native_push_registration_challenges "
                     "WHERE status='pending' AND expires_at<=clock_timestamp() "
                     "AND (lease_until IS NULL OR lease_until<=clock_timestamp()) "
                     "ORDER BY expires_at LIMIT %s FOR UPDATE SKIP LOCKED) "
                     "UPDATE native_push_registration_challenges SET status='expired'," + ERASE +
                     " WHERE challenge_ref IN (SELECT challenge_ref FROM due)", (size,))
        # Consume expired leases first, without permitting ambiguous send replay.
        conn.execute("WITH due AS (SELECT delivery_ref FROM native_push_deliveries WHERE status='leased' "
                     "AND lease_until<=clock_timestamp() ORDER BY lease_until LIMIT %s FOR UPDATE SKIP LOCKED) "
                     "UPDATE native_push_deliveries SET status='failed',lease_token=NULL,lease_until=NULL,"
                     "last_error_code='transport_uncertain',updated_at=clock_timestamp() "
                     "WHERE delivery_ref IN (SELECT delivery_ref FROM due)", (size,))
        conn.execute("WITH due AS (SELECT d.delivery_ref FROM native_push_deliveries d JOIN native_push_events e USING(event_ref) "
                     "WHERE d.status IN ('pending','retry_wait') AND e.expires_at<=clock_timestamp() "
                     "ORDER BY e.expires_at LIMIT %s FOR UPDATE OF d SKIP LOCKED) "
                     "UPDATE native_push_deliveries SET status='expired',next_attempt_at=NULL,"
                     "last_error_code='expired',updated_at=clock_timestamp() WHERE delivery_ref IN (SELECT delivery_ref FROM due)", (size,))
        # Delete children in bounded batches, never through an unbounded cascade.
        conn.execute("WITH due AS (SELECT d.delivery_ref FROM native_push_deliveries d JOIN native_push_events e USING(event_ref) "
                     "WHERE d.status IN ('accepted','expired','cancelled','failed') AND d.lease_token IS NULL "
                     "AND GREATEST(d.updated_at,e.expires_at)<clock_timestamp()-interval '7 days' "
                     "ORDER BY d.updated_at LIMIT %s FOR UPDATE OF d SKIP LOCKED) "
                     "DELETE FROM native_push_deliveries WHERE delivery_ref IN (SELECT delivery_ref FROM due)", (size,))
        conn.execute("WITH due AS (SELECT e.event_ref FROM native_push_events e "
                     "WHERE e.expires_at<clock_timestamp()-interval '7 days' "
                     "AND NOT EXISTS (SELECT 1 FROM native_push_deliveries d WHERE d.event_ref=e.event_ref) "
                     "ORDER BY e.expires_at LIMIT %s FOR UPDATE OF e SKIP LOCKED) "
                     "DELETE FROM native_push_events WHERE event_ref IN (SELECT event_ref FROM due)", (size,))
        # Terminal challenges intentionally retained: UNIQUE(user_id,request_id)
        # is an unbounded replay guarantee, not merely a seven-day rate limit.
