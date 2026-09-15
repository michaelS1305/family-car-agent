-- MANUAL ONLY. Run before deploying the matching backend.
BEGIN;

DO $preflight$
DECLARE
    expected record;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_class
        WHERE oid = to_regclass('public.users') AND relkind IN ('r', 'p')
    ) THEN
        RAISE EXCEPTION 'Expected public.users table';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_class
        WHERE oid = to_regclass('public.families') AND relkind IN ('r', 'p')
    ) THEN
        RAISE EXCEPTION 'Expected public.families table';
    END IF;

    FOR expected IN SELECT * FROM (VALUES
        ('public.users', 'id', 'integer'),
        ('public.families', 'id', 'integer')
    ) AS required(table_name, column_name, type_name)
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_attribute
            WHERE attrelid = to_regclass(expected.table_name)
              AND attname = expected.column_name
              AND NOT attisdropped
              AND attnotnull
              AND format_type(atttypid, atttypmod) = expected.type_name
        ) THEN
            RAISE EXCEPTION 'Unexpected required column: %.%',
                expected.table_name, expected.column_name;
        END IF;
    END LOOP;

    IF to_regclass('public.carplay_transition_admissions') IS NOT NULL
       OR to_regclass('public.carplay_transition_admissions_user_admitted_idx') IS NOT NULL
       OR to_regclass('public.carplay_transition_admissions_family_admitted_idx') IS NOT NULL
       OR to_regclass('public.carplay_transition_admissions_admitted_idx') IS NOT NULL THEN
        RAISE EXCEPTION 'CarPlay transition admission migration already applied or conflicting objects exist';
    END IF;
END
$preflight$;

CREATE TABLE public.carplay_transition_admissions (
    admission_id uuid PRIMARY KEY,
    user_id integer NOT NULL,
    family_id integer NOT NULL,
    admitted_at timestamptz NOT NULL DEFAULT clock_timestamp(),

    CONSTRAINT carplay_transition_admissions_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE,
    CONSTRAINT carplay_transition_admissions_family_id_fkey
        FOREIGN KEY (family_id) REFERENCES public.families(id) ON DELETE CASCADE,
    CONSTRAINT carplay_transition_admissions_admitted_at_check
        CHECK (isfinite(admitted_at))
);

CREATE INDEX carplay_transition_admissions_user_admitted_idx
    ON public.carplay_transition_admissions (user_id, admitted_at);
CREATE INDEX carplay_transition_admissions_family_admitted_idx
    ON public.carplay_transition_admissions (family_id, admitted_at);
CREATE INDEX carplay_transition_admissions_admitted_idx
    ON public.carplay_transition_admissions (admitted_at);

REVOKE ALL PRIVILEGES
ON TABLE public.carplay_transition_admissions
FROM PUBLIC, anon, authenticated;

REVOKE ALL PRIVILEGES (admission_id, user_id, family_id, admitted_at)
ON TABLE public.carplay_transition_admissions
FROM PUBLIC, anon, authenticated;

COMMIT;
