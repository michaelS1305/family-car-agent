-- READ ONLY. Save results BEFORE remediation, then run again AFTER.
-- All access flags must be false afterward; missing expected objects fail review.
-- Compare function_snapshot and rls_snapshot before/after for exact equality.
-- A post-only snapshot cannot prove that historical ACL/RLS state is unchanged.
WITH expected(name) AS (
    VALUES ('users'), ('families'), ('reservations'), ('car_events'),
           ('conversation_messages'), ('chat_requests'), ('chat_tool_actions'),
           ('pwa_join_sessions'), ('push_subscriptions')
), relations AS (
    SELECT e.name, c.oid, c.relkind
    FROM expected e
    LEFT JOIN pg_class c ON c.oid = to_regclass(format('public.%I', e.name))
), roles AS (
    SELECT v.name, r.oid
    FROM (VALUES ('anon'), ('authenticated')) v(name)
    LEFT JOIN pg_roles r ON r.rolname = v.name
), results AS (
    SELECT 'table_access' AS section, t.name AS object_name,
           r.name AS role_name,
           jsonb_build_object(
               'valid_table', t.oid IS NOT NULL AND t.relkind IN ('r', 'p'),
               'role_exists', r.oid IS NOT NULL,
               'select', has_table_privilege(r.oid, t.oid, 'SELECT'),
               'insert', has_table_privilege(r.oid, t.oid, 'INSERT'),
               'update', has_table_privilege(r.oid, t.oid, 'UPDATE'),
               'delete', has_table_privilege(r.oid, t.oid, 'DELETE'),
               'column_select', has_any_column_privilege(r.oid, t.oid, 'SELECT'),
               'column_insert', has_any_column_privilege(r.oid, t.oid, 'INSERT'),
               'column_update', has_any_column_privilege(r.oid, t.oid, 'UPDATE')
           ) AS details
    FROM relations t CROSS JOIN roles r
    UNION ALL
    SELECT DISTINCT 'sequence_access', format('%I.%I', n.nspname, s.relname), r.name,
           jsonb_build_object(
               'owned_by', t.name,
               'usage', has_sequence_privilege(r.oid, s.oid, 'USAGE'),
               'select', has_sequence_privilege(r.oid, s.oid, 'SELECT'),
               'update', has_sequence_privilege(r.oid, s.oid, 'UPDATE')
           )
    FROM relations t
    JOIN pg_depend d ON d.refobjid = t.oid
        AND d.classid = 'pg_class'::regclass
        AND d.refclassid = 'pg_class'::regclass
        AND d.refobjsubid > 0 AND d.deptype IN ('a', 'i')
    JOIN pg_class s ON s.oid = d.objid AND s.relkind = 'S'
    JOIN pg_namespace n ON n.oid = s.relnamespace
    CROSS JOIN roles r
    UNION ALL
    SELECT 'function_snapshot', f.signature, r.name,
           jsonb_build_object(
               'exists', p.oid IS NOT NULL,
               'owner', pg_get_userbyid(p.proowner),
               'acl', p.proacl::text,
               'execute', has_function_privilege(r.oid, p.oid, 'EXECUTE'),
               'security_definer', p.prosecdef,
               'settings', p.proconfig
           )
    FROM (VALUES ('public.broadcast_car_status_changed()'),
                 ('public.can_receive_car_status_topic(text)')) f(signature)
    LEFT JOIN pg_proc p ON p.oid = to_regprocedure(f.signature)
    CROSS JOIN roles r
    UNION ALL
    SELECT 'rls_snapshot', 'public.pwa_join_sessions', NULL,
           jsonb_build_object('exists', c.oid IS NOT NULL,
                              'rls', c.relrowsecurity, 'force_rls', c.relforcerowsecurity)
    FROM (VALUES (1)) anchor(x)
    LEFT JOIN pg_class c ON c.oid = to_regclass('public.pwa_join_sessions')
    UNION ALL
    SELECT 'legacy_removal', 'public.onboarding_sessions', NULL,
           jsonb_build_object('absent', to_regclass('public.onboarding_sessions') IS NULL)
)
SELECT * FROM results ORDER BY section, object_name, role_name;
