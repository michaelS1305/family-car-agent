-- Read-only verification after separately approved migration; no identities or secrets.
BEGIN READ ONLY;
SELECT table_name, column_name, data_type, is_nullable, column_default
FROM information_schema.columns WHERE table_schema='public'
 AND table_name IN ('account_deletion_jobs','apple_credentials','apple_credential_attempts')
ORDER BY table_name, ordinal_position;
SELECT conrelid::regclass AS relation, conname, convalidated, pg_get_constraintdef(oid)
FROM pg_constraint WHERE conrelid IN ('public.account_deletion_jobs'::regclass,
 'public.apple_credentials'::regclass,'public.apple_credential_attempts'::regclass);
SELECT relname, relrowsecurity, relacl FROM pg_class WHERE oid IN
 ('public.account_deletion_jobs'::regclass,'public.apple_credentials'::regclass,
  'public.apple_credential_attempts'::regclass);
SELECT role_name, relation,
 has_table_privilege(role_name,relation,'SELECT,INSERT,UPDATE,DELETE') AS client_access_must_be_false
FROM (VALUES ('anon'),('authenticated')) r(role_name)
CROSS JOIN (VALUES ('public.account_deletion_jobs'),('public.apple_credentials'),
 ('public.apple_credential_attempts')) t(relation);
SELECT role_name,
 has_sequence_privilege(role_name,'public.apple_credential_attempts_generation_seq','USAGE,SELECT,UPDATE') AS sequence_access_must_be_false,
 has_function_privilege(role_name,'public.resolve_apple_deletion_manually(uuid,text,boolean)','EXECUTE') AS execute_must_be_false
FROM (VALUES ('anon'),('authenticated')) r(role_name);
SELECT phase, apple_state, count(*) FROM public.account_deletion_jobs GROUP BY phase, apple_state;
COMMIT;
