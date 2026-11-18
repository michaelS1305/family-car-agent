-- Read-only operator verification, on the explicitly selected Dev database only.
BEGIN READ ONLY;
SELECT current_user,session_user;
SELECT attname,format_type(atttypid,atttypmod),attnotnull
FROM pg_attribute WHERE attrelid='public.native_push_events'::regclass
 AND attname IN ('source_event_id','reservation_ref','maintenance_ref','scheduled_for') AND NOT attisdropped;
SELECT attname,attnotnull,pg_get_expr(d.adbin,d.adrelid) AS default_expression
FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
WHERE a.attrelid='public.vehicle_maintenance'::regclass AND a.attname='completed';
SELECT conname,convalidated,pg_get_constraintdef(oid)
FROM pg_constraint WHERE conrelid='public.native_push_events'::regclass ORDER BY conname;
SELECT relname,relrowsecurity,relforcerowsecurity,pg_get_userbyid(relowner) AS owner
FROM pg_class WHERE oid='public.native_push_events'::regclass;
SELECT policyname FROM pg_policies WHERE schemaname='public' AND tablename='native_push_events';
SELECT r.rolname,p.privilege,has_table_privilege(r.oid,'public.native_push_events',p.privilege) AS allowed
FROM pg_roles r CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER','MAINTAIN']) p(privilege)
WHERE r.rolname IN ('postgres','anon','authenticated','service_role');
SELECT r.rolname,p.privilege,has_any_column_privilege(r.oid,'public.native_push_events',p.privilege) AS allowed
FROM pg_roles r CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','REFERENCES']) p(privilege)
WHERE r.rolname IN ('anon','authenticated','service_role');
SELECT pubname FROM pg_publication_tables WHERE schemaname='public' AND tablename='native_push_events';
ROLLBACK;
