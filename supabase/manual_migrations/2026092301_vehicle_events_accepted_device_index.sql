-- PREPARED / NOT EXECUTED IN PRODUCTION. Index only; apply before backend rollout.
-- Backend chronology checks must not scan an arbitrarily long terminal tail.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $preflight$
BEGIN
    IF current_user <> 'postgres' THEN
        RAISE EXCEPTION 'Run this manual migration as postgres';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_class WHERE oid=to_regclass('public.vehicle_events') AND relkind='r')
       OR NOT EXISTS (SELECT FROM pg_attribute WHERE attrelid=to_regclass('public.vehicle_events')
                      AND attname='device_id' AND atttypid='integer'::regtype AND NOT attisdropped)
       OR NOT EXISTS (SELECT FROM pg_attribute WHERE attrelid=to_regclass('public.vehicle_events')
                      AND attname='device_sequence' AND atttypid='bigint'::regtype AND NOT attisdropped)
       OR NOT EXISTS (SELECT FROM pg_attribute WHERE attrelid=to_regclass('public.vehicle_events')
                      AND attname='admission_outcome' AND atttypid='text'::regtype AND NOT attisdropped) THEN
        RAISE EXCEPTION 'Expected Vehicle Identity foundation columns';
    END IF;
    IF to_regclass('public.vehicle_events_device_accepted_sequence_idx') IS NOT NULL THEN
        RAISE EXCEPTION 'Already applied or conflicting index';
    END IF;
END
$preflight$;

CREATE INDEX vehicle_events_device_accepted_sequence_idx
    ON public.vehicle_events (device_id, device_sequence)
    WHERE admission_outcome = 'accepted';
COMMIT;
