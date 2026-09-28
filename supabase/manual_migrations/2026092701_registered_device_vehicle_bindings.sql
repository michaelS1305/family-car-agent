-- PREPARED / UNEXECUTED. Explicit native installation authority; no backfill.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
DO $preflight$
DECLARE item record;
BEGIN
    IF current_user <> 'postgres'
       OR NOT EXISTS (SELECT FROM pg_roles WHERE rolname='anon')
       OR NOT EXISTS (SELECT FROM pg_roles WHERE rolname='authenticated')
       OR NOT EXISTS (SELECT FROM pg_roles WHERE rolname='service_role')
       OR to_regclass('public.registered_device_vehicle_bindings') IS NOT NULL
       OR to_regclass('public.registered_device_vehicle_bindings_vehicle_idx') IS NOT NULL THEN
        RAISE EXCEPTION 'Unexpected executor, roles or conflicting binding objects';
    END IF;
    FOR item IN SELECT * FROM (VALUES ('registered_devices'), ('vehicles')) AS t(name)
    LOOP
        IF NOT EXISTS (
            SELECT FROM pg_attribute a JOIN pg_constraint c
              ON c.conrelid=a.attrelid AND c.contype='p' AND c.conkey=ARRAY[a.attnum]
            WHERE a.attrelid=to_regclass('public.' || item.name)
              AND a.attname='id' AND a.atttypid='integer'::regtype
              AND a.attnotnull AND NOT a.attisdropped
        ) THEN
            RAISE EXCEPTION 'Expected parent integer primary key missing';
        END IF;
    END LOOP;
END
$preflight$;
CREATE TABLE public.registered_device_vehicle_bindings (
    device_id integer NOT NULL REFERENCES public.registered_devices(id) ON DELETE CASCADE,
    vehicle_id integer NOT NULL REFERENCES public.vehicles(id) ON DELETE CASCADE,
    PRIMARY KEY (device_id, vehicle_id)
);
CREATE INDEX registered_device_vehicle_bindings_vehicle_idx
    ON public.registered_device_vehicle_bindings(vehicle_id);
-- Match the Vehicle Identity foundation ACL model; no browser policies.
REVOKE ALL PRIVILEGES ON TABLE public.registered_device_vehicle_bindings
    FROM PUBLIC, anon, authenticated;
REVOKE ALL PRIVILEGES (device_id, vehicle_id) ON TABLE public.registered_device_vehicle_bindings
    FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER, TRUNCATE
    ON TABLE public.registered_device_vehicle_bindings TO service_role;
COMMIT;
