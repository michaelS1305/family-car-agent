-- PREPARED; not executed in production. Pause lifecycle writers for cutover.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
DO $preflight$
DECLARE expected record;
BEGIN
    IF current_user <> 'postgres' THEN
        RAISE EXCEPTION 'Run as postgres';
    END IF;
    FOR expected IN SELECT * FROM (VALUES
        ('families','id','integer'), ('users','family_id','integer'),
        ('vehicles','family_id','integer'), ('vehicles','created_by_user_id','integer'),
        ('registered_devices','user_id','integer')
    ) AS required(table_name,column_name,type_name) LOOP
        IF NOT EXISTS (SELECT FROM pg_attribute WHERE
            attrelid=to_regclass('public.' || expected.table_name)
            AND attname=expected.column_name AND NOT attisdropped
            AND format_type(atttypid,atttypmod)=expected.type_name) THEN
            RAISE EXCEPTION 'Vehicle foundation missing or incompatible';
        END IF;
    END LOOP;
    IF EXISTS (SELECT FROM pg_attribute WHERE attrelid='public.families'::regclass
               AND attname='device_identities_created' AND NOT attisdropped)
       OR EXISTS (SELECT FROM pg_attribute WHERE attrelid IN
                   ('public.vehicles'::regclass,'public.registered_devices'::regclass)
                   AND attname IN ('creation_request_id','creation_fingerprint') AND NOT attisdropped) THEN
        RAISE EXCEPTION 'Already applied or conflicting creation metadata';
    END IF;
END
$preflight$;

LOCK TABLE public.families, public.users, public.vehicles, public.registered_devices
    IN ACCESS EXCLUSIVE MODE;
DO $ownership$
BEGIN
    IF EXISTS (SELECT FROM public.registered_devices d JOIN public.users u ON u.id=d.user_id
               WHERE u.family_id IS NULL) THEN
        RAISE EXCEPTION 'Device without family: resolve ownership before backfill';
    END IF;
END
$ownership$;

-- Resource-local metadata: historical rows remain NULL, preserving all refs.
ALTER TABLE public.vehicles
    ADD COLUMN creation_request_id uuid,
    ADD COLUMN creation_fingerprint bytea,
    ADD CONSTRAINT vehicles_creation_metadata_check CHECK (
        (creation_request_id IS NULL AND creation_fingerprint IS NULL) OR
        (creation_request_id IS NOT NULL AND creation_fingerprint IS NOT NULL
         AND octet_length(creation_fingerprint)=32)),
    ADD CONSTRAINT vehicles_creation_request_key UNIQUE(family_id,creation_request_id);
ALTER TABLE public.registered_devices
    ADD COLUMN creation_request_id uuid,
    ADD COLUMN creation_fingerprint bytea,
    ADD CONSTRAINT devices_creation_metadata_check CHECK (
        (creation_request_id IS NULL AND creation_fingerprint IS NULL) OR
        (creation_request_id IS NOT NULL AND creation_fingerprint IS NOT NULL
         AND octet_length(creation_fingerprint)=32)),
    ADD CONSTRAINT devices_creation_request_key UNIQUE(user_id,creation_request_id);

-- Account deletion removes devices. This non-personal cumulative counter must
-- survive member deletion, unlike counts of surviving device rows.
ALTER TABLE public.families ADD COLUMN device_identities_created bigint NOT NULL DEFAULT 0
    CONSTRAINT families_device_identities_created_check CHECK(device_identities_created>=0);
UPDATE public.families f SET device_identities_created=(
    SELECT count(*) FROM public.registered_devices d JOIN public.users u ON u.id=d.user_id
    WHERE u.family_id=f.id);
-- No grants/RLS changes; new columns retain the existing backend-only table ACL.
COMMIT;
