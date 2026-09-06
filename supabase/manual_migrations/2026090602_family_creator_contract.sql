-- Manual Supabase SQL migration: phase 2 (CONTRACT).
-- Run only after the new application is deployed, healthy, and production data is audited.

BEGIN;

-- Prevent a concurrent create from changing the audited invariants mid-contract.
LOCK TABLE public.families, public.users IN ACCESS EXCLUSIVE MODE;

DO $preflight$
BEGIN
    IF EXISTS (SELECT 1 FROM public.families WHERE created_by_user_id IS NULL) THEN
        RAISE EXCEPTION 'Contract preflight failed: family without created_by_user_id';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM public.families f
        LEFT JOIN public.users u ON u.id = f.created_by_user_id
        WHERE u.id IS NULL
    ) THEN
        RAISE EXCEPTION 'Contract preflight failed: family creator does not exist';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM public.families f
        JOIN public.users u ON u.id = f.created_by_user_id
        WHERE u.family_id IS DISTINCT FROM f.id
    ) THEN
        RAISE EXCEPTION 'Contract preflight failed: creator does not belong to the created family';
    END IF;
    IF EXISTS (SELECT 1 FROM public.users WHERE member_public_id IS NULL) THEN
        RAISE EXCEPTION 'Contract preflight failed: member_public_id is null';
    END IF;
    IF EXISTS (
        SELECT member_public_id
        FROM public.users
        GROUP BY member_public_id
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'Contract preflight failed: duplicate member_public_id';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.users
        WHERE family_role IS NOT NULL
          AND family_role NOT IN ('parent', 'child')
    ) THEN
        RAISE EXCEPTION 'Contract preflight failed: invalid family_role';
    END IF;
END
$preflight$;

ALTER TABLE public.families
    ALTER COLUMN created_by_user_id SET NOT NULL;

COMMIT;
