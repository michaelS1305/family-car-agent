-- Manual only. Do not run through application startup.
-- Removes only the empty, unused Telegram onboarding table; no CASCADE.
BEGIN;

DO $remediation$
DECLARE
    table_name text;
    relation_oid oid;
    column_list text;
    seq record;
BEGIN
    -- Validate every expected relation before changing privileges.
    FOREACH table_name IN ARRAY ARRAY[
        'users', 'families', 'reservations', 'car_events',
        'conversation_messages', 'chat_requests', 'chat_tool_actions',
        'pwa_join_sessions', 'push_subscriptions', 'onboarding_sessions'
    ]
    LOOP
        relation_oid := to_regclass(format('public.%I', table_name));
        IF relation_oid IS NULL OR NOT EXISTS (
            SELECT 1 FROM pg_class
            WHERE oid = relation_oid AND relkind IN ('r', 'p')
        ) THEN
            RAISE EXCEPTION 'Expected ordinary/partitioned table public.% is missing or invalid', table_name;
        END IF;
    END LOOP;

    -- Prevent an insert between the empty check and DROP. Includes descendants.
    LOCK TABLE public.onboarding_sessions IN ACCESS EXCLUSIVE MODE;
    IF EXISTS (SELECT 1 FROM public.onboarding_sessions) THEN
        RAISE EXCEPTION 'Legacy onboarding_sessions is not empty; remediation aborted';
    END IF;

    FOREACH table_name IN ARRAY ARRAY[
        'users', 'families', 'reservations', 'car_events',
        'conversation_messages', 'chat_requests', 'chat_tool_actions',
        'pwa_join_sessions', 'push_subscriptions'
    ]
    LOOP
        relation_oid := to_regclass(format('public.%I', table_name));
        EXECUTE format(
            'REVOKE ALL PRIVILEGES ON TABLE public.%I FROM anon, authenticated, PUBLIC',
            table_name
        );

        -- Independently granted column privileges survive table-level REVOKE.
        SELECT string_agg(format('%I', attname), ', ' ORDER BY attnum)
        INTO column_list
        FROM pg_attribute
        WHERE attrelid = relation_oid AND attnum > 0 AND NOT attisdropped;
        IF column_list IS NOT NULL THEN
            EXECUTE format(
                'REVOKE SELECT (%1$s), INSERT (%1$s), UPDATE (%1$s), REFERENCES (%1$s)
                 ON TABLE public.%2$I FROM anon, authenticated, PUBLIC',
                column_list, table_name
            );
        END IF;

        FOR seq IN
            SELECT DISTINCT ns.nspname, s.relname
            FROM pg_depend d
            JOIN pg_class s ON s.oid = d.objid AND s.relkind = 'S'
            JOIN pg_namespace ns ON ns.oid = s.relnamespace
            WHERE d.classid = 'pg_class'::regclass
              AND d.refclassid = 'pg_class'::regclass
              AND d.refobjid = relation_oid
              AND d.refobjsubid > 0
              AND d.deptype IN ('a', 'i')
        LOOP
            EXECUTE format(
                'REVOKE ALL PRIVILEGES ON SEQUENCE %I.%I FROM anon, authenticated, PUBLIC',
                seq.nspname, seq.relname
            );
        END LOOP;
    END LOOP;

    -- RESTRICT is explicit: unexpected dependencies abort the whole transaction.
    DROP TABLE public.onboarding_sessions RESTRICT;
END
$remediation$;

COMMIT;
