-- Manual Supabase SQL migration: phase 1 (EXPAND + guarded legacy backfill).
-- Run this file in Supabase SQL Editor before deploying the matching application.

BEGIN;

-- Keep the approved legacy snapshot stable from preflight through backfill.
LOCK TABLE public.families, public.users IN ACCESS EXCLUSIVE MODE;

DO $preflight$
DECLARE
    legacy_family_id integer;
BEGIN
    IF to_regprocedure('gen_random_uuid()') IS NULL THEN
        RAISE EXCEPTION 'Preflight failed: gen_random_uuid() is unavailable';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'users'
          AND column_name IN ('family_role', 'member_public_id')
    ) OR EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'families'
          AND column_name = 'created_by_user_id'
    ) THEN
        RAISE EXCEPTION 'Preflight failed: one or more target columns already exist';
    END IF;

    IF (SELECT count(*) FROM public.families) <> 1 THEN
        RAISE EXCEPTION 'Preflight failed: expected exactly 1 legacy family';
    END IF;
    IF (SELECT count(*) FROM public.users) <> 2 THEN
        RAISE EXCEPTION 'Preflight failed: expected exactly 2 legacy users';
    END IF;

    SELECT family_id INTO legacy_family_id
    FROM public.users
    WHERE id = 1;

    IF legacy_family_id IS NULL THEN
        RAISE EXCEPTION 'Preflight failed: users.id=1 is missing or has no family';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.families WHERE id = legacy_family_id) THEN
        RAISE EXCEPTION 'Preflight failed: users.id=1 references a missing family';
    END IF;
    IF (SELECT count(*) FROM public.users WHERE family_id = legacy_family_id) <> 2 THEN
        RAISE EXCEPTION 'Preflight failed: both legacy users must belong to users.id=1 family';
    END IF;
END
$preflight$;

ALTER TABLE public.users
    ADD COLUMN family_role text NULL,
    ADD COLUMN member_public_id uuid DEFAULT gen_random_uuid();

ALTER TABLE public.users
    ADD CONSTRAINT users_family_role_check
        CHECK (family_role IS NULL OR family_role IN ('parent', 'child'));

UPDATE public.users
SET member_public_id = gen_random_uuid()
WHERE member_public_id IS NULL;

ALTER TABLE public.users
    ALTER COLUMN member_public_id SET NOT NULL,
    ADD CONSTRAINT users_member_public_id_key UNIQUE (member_public_id);

ALTER TABLE public.families
    ADD COLUMN created_by_user_id integer NULL,
    ADD CONSTRAINT families_created_by_user_id_fkey
        FOREIGN KEY (created_by_user_id)
        REFERENCES public.users(id)
        ON DELETE RESTRICT;

DO $backfill$
DECLARE
    legacy_family_id integer;
    affected integer;
BEGIN
    SELECT family_id INTO STRICT legacy_family_id
    FROM public.users
    WHERE id = 1;

    UPDATE public.families
    SET created_by_user_id = 1
    WHERE id = legacy_family_id
      AND created_by_user_id IS NULL;

    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 1 THEN
        RAISE EXCEPTION 'Backfill failed: expected exactly one guarded family update, got %', affected;
    END IF;
END
$backfill$;

COMMIT;
