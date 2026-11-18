"""Exact migration checks in a disposable, network-disabled PostgreSQL 17 container.
No host ports, existing database, credentials, providers or application workers are used.
Requires an already available postgres:17 image; never pulls an image.
"""
from pathlib import Path
import subprocess
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[2]
MIGRATION=ROOT/'supabase/manual_migrations/2026111801_apple_production_credentials_revocation.sql'
FOUNDATION=ROOT/'supabase/manual_migrations/2026091603_account_deletion_jobs.sql'
name='fca-apple-migration-'+uuid4().hex[:12]

def docker(*args, input=None, check=True):
    result=subprocess.run(['docker',*args],input=input,text=True,capture_output=True,timeout=60)
    if check and result.returncode: raise RuntimeError(result.stderr)
    return result

def sql(text, database='postgres', succeeds=True):
    result=docker('exec','-i',name,'psql','-X','-U','postgres','-v','ON_ERROR_STOP=1','-d',database,
                  input=text,check=False)
    if (result.returncode==0)!=succeeds: raise AssertionError(result.stderr or 'Unexpected SQL success')
    return result.stdout

fixture="""
CREATE SCHEMA auth;
CREATE TABLE auth.users(id uuid PRIMARY KEY);
CREATE TABLE auth.identities(user_id uuid, provider text, provider_id text, identity_data jsonb);
CREATE TABLE public.users(id integer PRIMARY KEY, auth_user_id uuid, family_id integer);
CREATE TABLE public.families(id integer PRIMARY KEY, created_by_user_id integer NOT NULL);
"""
try:
    docker('image','inspect','postgres:17')
    docker('run','--pull=never','--detach','--name',name,'--network=none',
           '--tmpfs','/var/lib/postgresql/data','--env','POSTGRES_HOST_AUTH_METHOD=trust','postgres:17')
    for _ in range(60):
        if docker('exec',name,'pg_isready','-U','postgres',check=False).returncode==0: break
        time.sleep(.25)
    else: raise RuntimeError('Local PostgreSQL did not become ready')
    sql('CREATE ROLE anon; CREATE ROLE authenticated;')
    sql(fixture+FOUNDATION.read_text())
    sql("INSERT INTO account_deletion_jobs(auth_user_id) VALUES ('00000000-0000-0000-0000-000000000001');"
        "CREATE TABLE before_jobs AS SELECT * FROM account_deletion_jobs;")
    sql(MIGRATION.read_text())
    sql(MIGRATION.with_name(MIGRATION.stem+'_verify.sql').read_text())
    sql("""DO $$ BEGIN
      IF EXISTS ((SELECT auth_user_id,phase,created_at,next_attempt_at FROM account_deletion_jobs EXCEPT SELECT * FROM before_jobs)
         UNION ALL (SELECT * FROM before_jobs EXCEPT SELECT auth_user_id,phase,created_at,next_attempt_at FROM account_deletion_jobs))
         THEN RAISE EXCEPTION 'Existing job changed'; END IF;
      IF EXISTS (SELECT 1 FROM account_deletion_jobs WHERE apple_state<>'unclassified' OR attempt_count<>0)
         THEN RAISE EXCEPTION 'Incorrect additive state'; END IF;
      IF (SELECT count(*) FROM pg_class WHERE oid IN ('apple_credentials'::regclass,'apple_credential_attempts'::regclass,
          'account_deletion_jobs'::regclass) AND relrowsecurity)<>3 THEN RAISE EXCEPTION 'RLS missing'; END IF;
      IF has_table_privilege('anon','apple_credentials','SELECT,INSERT,UPDATE,DELETE') OR
         has_table_privilege('authenticated','apple_credential_attempts','SELECT,INSERT,UPDATE,DELETE') OR
         has_sequence_privilege('authenticated','apple_credential_attempts_generation_seq','USAGE,SELECT,UPDATE') OR
         has_function_privilege('anon','resolve_apple_deletion_manually(uuid,text,boolean)','EXECUTE') OR
         has_function_privilege('authenticated','resolve_apple_deletion_manually(uuid,text,boolean)','EXECUTE')
         THEN RAISE EXCEPTION 'Client access leaked'; END IF;
    END $$;""")
    for env,client in [('dev','com.familycaragent.app.dev'),('prod','com.familycaragent.app')]:
        sql(f"""BEGIN;
          INSERT INTO apple_credential_attempts(auth_user_id,code_digest,status)
          VALUES ('00000000-0000-0000-0000-000000000001',decode(repeat('ab',32),'hex'),'stored');
          INSERT INTO apple_credentials(auth_user_id,environment,client_id,apple_subject,generation,key_id,refresh_ciphertext)
          SELECT auth_user_id,'{env}','{client}','synthetic',generation,'fixture',decode(repeat('ab',40),'hex')
          FROM apple_credential_attempts;
          ROLLBACK;""")
    sql("""BEGIN;
       INSERT INTO apple_credential_attempts(auth_user_id,code_digest)
       VALUES ('00000000-0000-0000-0000-000000000001',decode(repeat('ab',32),'hex'));
       INSERT INTO apple_credentials(auth_user_id,environment,client_id,apple_subject,generation,key_id,refresh_ciphertext)
       SELECT auth_user_id,'prod','com.familycaragent.app.dev','synthetic',generation,'fixture',decode(repeat('ab',40),'hex')
       FROM apple_credential_attempts; COMMIT;""",succeeds=False)
    sql(MIGRATION.read_text(),succeeds=False)
    for index,change in enumerate([
        'ALTER TABLE account_deletion_jobs ADD COLUMN unexpected text;',
        "ALTER TABLE account_deletion_jobs ALTER COLUMN phase SET DEFAULT 'auth_pending';",
        'ALTER TABLE account_deletion_jobs DROP CONSTRAINT account_deletion_jobs_phase_check;',
    ]):
        db='unexpected'+str(index); sql('CREATE DATABASE '+db+';')
        sql(fixture+FOUNDATION.read_text()+change,database=db)
        sql(MIGRATION.read_text(),database=db,succeeds=False)
        sql("DO $$ BEGIN IF to_regclass('public.apple_credentials') IS NOT NULL THEN RAISE EXCEPTION 'Partial migration'; END IF; END $$;",database=db)
    print('Exact migration passed: preserved jobs, both environments, mixed identity rejection, RLS/ACL, repeat/drift rollback')
finally:
    docker('rm','--force',name,check=False)
