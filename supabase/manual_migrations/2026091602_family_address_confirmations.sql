-- MANUAL ONLY. Prepared, not executed. No application integration or backfill.
BEGIN;

DO $preflight$
DECLARE
    expected record;
    object_name text;
BEGIN
    IF current_user <> 'postgres' THEN
        RAISE EXCEPTION 'Run this manual migration as postgres';
    END IF;
    FOR expected IN SELECT * FROM (VALUES
        ('auth.users', 'id', 'uuid', true),
        ('public.users', 'id', 'integer', true),
        ('public.users', 'auth_user_id', 'uuid', false),
        ('public.users', 'family_id', 'integer', false),
        ('public.families', 'id', 'integer', true),
        ('public.families', 'home_address', 'text', true),
        ('public.families', 'home_latitude', 'double precision', false),
        ('public.families', 'home_longitude', 'double precision', false)
    ) AS required(table_name, column_name, type_name, require_not_null)
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_class
            WHERE oid = to_regclass(expected.table_name) AND relkind IN ('r', 'p')
        ) OR NOT EXISTS (
            SELECT 1 FROM pg_attribute
            WHERE attrelid = to_regclass(expected.table_name)
              AND attname = expected.column_name AND NOT attisdropped
              AND format_type(atttypid, atttypmod) = expected.type_name
              AND (NOT expected.require_not_null OR attnotnull)
        ) THEN
            RAISE EXCEPTION 'Unexpected required column: %.%',
                expected.table_name, expected.column_name;
        END IF;
    END LOOP;

    FOREACH object_name IN ARRAY ARRAY[
        'family_address_confirmations',
        'family_address_confirmations_pkey',
        'family_address_confirmations_create_identity_idx',
        'family_address_confirmations_update_identity_idx',
        'family_address_confirmations_auth_idx',
        'family_address_confirmations_family_idx',
        'family_address_confirmations_expiry_idx'
    ] LOOP
        IF to_regclass('public.' || object_name) IS NOT NULL THEN
            RAISE EXCEPTION 'Confirmation migration already applied or conflicting object: %', object_name;
        END IF;
    END LOOP;
END
$preflight$;

-- Python will send hashlib.sha256(raw_token.encode('ascii')).digest(): 32 bytes.
-- Raw tokens are never stored. FKs ensure existence, not creator/membership
-- authorization: the later backend must recheck those relationships at commit.
CREATE TABLE public.family_address_confirmations (
    token_digest bytea PRIMARY KEY CHECK (octet_length(token_digest) = 32),
    purpose text NOT NULL CHECK (purpose IN ('create_family', 'family_address_update')),
    auth_user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    user_id integer REFERENCES public.users(id) ON DELETE CASCADE,
    family_id integer REFERENCES public.families(id) ON DELETE CASCADE,
    -- The request remains capped at 200 characters by the API. Normalization
    -- can add separator spaces; families.home_address itself is unbounded TEXT.
    normalized_address text NOT NULL CHECK (btrim(normalized_address) <> ''),
    display_address text NOT NULL CHECK (btrim(display_address) <> ''),
    latitude double precision NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude double precision NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    expires_at timestamptz NOT NULL DEFAULT (clock_timestamp() + INTERVAL '15 minutes')
        CHECK (isfinite(expires_at)),
    CONSTRAINT family_address_confirmations_binding_check CHECK (
        (purpose = 'create_family' AND user_id IS NULL AND family_id IS NULL)
        OR (purpose = 'family_address_update' AND user_id IS NOT NULL AND family_id IS NOT NULL)
    )
);

-- Preserve one pending Create per auth user, and one Update per internal user
-- (even if their family changes). Replacement also refreshes expires_at.
CREATE UNIQUE INDEX family_address_confirmations_create_identity_idx
    ON public.family_address_confirmations (auth_user_id) WHERE purpose = 'create_family';
CREATE UNIQUE INDEX family_address_confirmations_update_identity_idx
    ON public.family_address_confirmations (user_id) WHERE purpose = 'family_address_update';
-- Support cascade cleanup for all purposes and bounded expiry cleanup.
CREATE INDEX family_address_confirmations_auth_idx
    ON public.family_address_confirmations (auth_user_id);
CREATE INDEX family_address_confirmations_family_idx
    ON public.family_address_confirmations (family_id) WHERE family_id IS NOT NULL;
CREATE INDEX family_address_confirmations_expiry_idx
    ON public.family_address_confirmations (expires_at);

-- Backend postgres owns/accesses this table. No browser policies or grants.
-- Consistent with the repository's ACL-based backend-only security boundary.
REVOKE ALL PRIVILEGES ON TABLE public.family_address_confirmations
FROM PUBLIC, anon, authenticated;
REVOKE ALL PRIVILEGES (
    token_digest, purpose, auth_user_id, user_id, family_id,
    normalized_address, display_address, latitude, longitude, expires_at
) ON TABLE public.family_address_confirmations
FROM PUBLIC, anon, authenticated;

COMMIT;
