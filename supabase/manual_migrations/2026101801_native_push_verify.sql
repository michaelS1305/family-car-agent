-- READ ONLY. Run manually in DEV only after separate approval.
-- Valid both before and after migration. No row data or credentials are selected.
-- Before: native objects absent. After: four postgres-owned tables, RLS on,
-- no policies/publications/browser or service_role access; expected constraints/indexes.
BEGIN READ ONLY;
SELECT current_user, session_user;
SELECT rolname,rolsuper,rolbypassrls,rolinherit FROM pg_roles
WHERE rolname IN (current_user,session_user,'anon','authenticated','service_role');

SELECT c.relname,c.relkind,pg_get_userbyid(c.relowner) AS owner,
       c.relrowsecurity,c.relforcerowsecurity,c.relacl
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND (c.relname LIKE 'native_push_%' OR c.relname='push_subscriptions')
ORDER BY c.relname;

SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod) AS type,
       a.attnotnull,a.attidentity,a.attacl,pg_get_expr(d.adbin,d.adrelid) AS default_expression
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
JOIN pg_attribute a ON a.attrelid=c.oid
LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
WHERE n.nspname='public' AND a.attnum>0 AND NOT a.attisdropped
  AND (c.relname LIKE 'native_push_%' OR c.relname IN ('users','vehicle_events'))
ORDER BY c.relname,a.attnum;

SELECT c.conrelid::regclass AS tbl,c.conname,c.contype,c.convalidated,c.condeferrable,
       pg_get_constraintdef(c.oid) AS definition
FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace
WHERE n.nspname='public' AND (t.relname LIKE 'native_push_%' OR t.relname IN ('users','vehicle_events'))
ORDER BY t.relname,c.conname;

SELECT t.relname AS tbl,i.relname AS idx,x.indisvalid,x.indisready,pg_get_indexdef(i.oid)
FROM pg_index x JOIN pg_class t ON t.oid=x.indrelid JOIN pg_class i ON i.oid=x.indexrelid
JOIN pg_namespace n ON n.oid=t.relnamespace
WHERE n.nspname='public' AND (t.relname LIKE 'native_push_%' OR t.relname IN ('users','vehicle_events'))
ORDER BY t.relname,i.relname;

SELECT r.rolname,c.relname,p.privilege,has_table_privilege(r.oid,c.oid,p.privilege) AS allowed
FROM pg_roles r CROSS JOIN pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
CROSS JOIN (VALUES ('SELECT'),('INSERT'),('UPDATE'),('DELETE'),('TRUNCATE'),('REFERENCES'),('TRIGGER')) p(privilege)
WHERE r.rolname IN ('postgres','service_role','anon','authenticated')
  AND n.nspname='public' AND c.relkind='r' AND c.relname LIKE 'native_push_%'
ORDER BY c.relname,r.rolname,p.privilege;

SELECT r.rolname,c.relname,a.attname,p.privilege,
       has_column_privilege(r.oid,c.oid,a.attnum,p.privilege) AS allowed
FROM pg_roles r CROSS JOIN pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
CROSS JOIN (VALUES ('SELECT'),('INSERT'),('UPDATE'),('REFERENCES')) p(privilege)
WHERE r.rolname IN ('anon','authenticated','service_role')
  AND n.nspname='public' AND c.relkind='r' AND c.relname LIKE 'native_push_%'
ORDER BY c.relname,r.rolname,a.attnum,p.privilege;

SELECT * FROM pg_policies WHERE schemaname='public' AND tablename LIKE 'native_push_%';
SELECT pubname,puballtables FROM pg_publication;
SELECT p.pubname,n.nspname FROM pg_publication_namespace pn
JOIN pg_publication p ON p.oid=pn.pnpubid JOIN pg_namespace n ON n.oid=pn.pnnspid;
SELECT pubname,schemaname,tablename FROM pg_publication_tables
WHERE schemaname='public' AND tablename LIKE 'native_push_%';
SELECT tgrelid::regclass,tgname,pg_get_triggerdef(oid) FROM pg_trigger
WHERE NOT tgisinternal AND tgrelid IN (
    SELECT oid FROM pg_class WHERE relnamespace='public'::regnamespace AND relname LIKE 'native_push_%');
COMMIT;
