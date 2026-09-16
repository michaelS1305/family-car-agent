-- MANUAL ONLY. Keep Create traffic paused from before execution until all
-- workers use the matching history-aware allocator. See README.md for cutover.
BEGIN;

DO $preflight$
DECLARE
    code_attribute smallint;
BEGIN
    IF current_user <> 'postgres' THEN
        RAISE EXCEPTION 'Run this manual migration as postgres';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_class
        WHERE oid = to_regclass('public.families') AND relkind IN ('r', 'p')
    ) THEN
        RAISE EXCEPTION 'Expected public.families table';
    END IF;

    -- Prevent writes/TRUNCATE between validation and the committed backfill.
    LOCK TABLE public.families IN SHARE MODE;

    SELECT attnum INTO code_attribute
    FROM pg_attribute
    WHERE attrelid = 'public.families'::regclass
      AND attname = 'family_code'
      AND NOT attisdropped
      AND attnotnull
      AND atttypid = 'text'::regtype;
    IF code_attribute IS NULL OR NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.families'::regclass
          AND contype = 'u'
          AND conkey = ARRAY[code_attribute]
          AND convalidated
    ) THEN
        RAISE EXCEPTION 'Expected families.family_code TEXT UNIQUE NOT NULL';
    END IF;

    IF to_regclass('public.family_code_history') IS NOT NULL
       OR to_regclass('public.family_code_history_pkey') IS NOT NULL THEN
        RAISE EXCEPTION 'Family code history already exists or conflicting objects exist';
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.families
        WHERE family_code IS NULL
           OR octet_length(family_code) <> 6
           OR NOT (family_code COLLATE "C" ~ '^[a-z0-9]{6}$')
    ) THEN
        RAISE EXCEPTION 'Existing family codes are not canonical; no values were changed';
    END IF;
END
$preflight$;

-- Persistent set of assigned codes, not an allocation ban. No ownership FK:
-- deleting/truncating a family must not erase the knowledge that its code was used.
CREATE TABLE public.family_code_history (
    code text COLLATE "C" PRIMARY KEY,
    CONSTRAINT family_code_history_code_check CHECK (
        octet_length(code) = 6 AND code ~ '^[a-z0-9]{6}$'
    )
);

INSERT INTO public.family_code_history (code)
SELECT family_code FROM public.families;

REVOKE ALL PRIVILEGES
ON TABLE public.family_code_history
FROM PUBLIC, anon, authenticated;

REVOKE ALL PRIVILEGES (code)
ON TABLE public.family_code_history
FROM PUBLIC, anon, authenticated;

COMMIT;
