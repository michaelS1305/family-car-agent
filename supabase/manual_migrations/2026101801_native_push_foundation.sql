-- PREPARED / UNEXECUTED. Native Push foundation only. Manual Dev review required.
-- Verified Dev runtime: postgres, BYPASSRLS. This is NOT verification of Prod.
-- No provider calls, event producers, worker, triggers, extensions or legacy changes.
-- UUIDs are supplied by future server code. Never execute from application startup.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $preflight$
DECLARE
    expected record;
BEGIN
    IF current_user <> 'postgres' OR NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolbypassrls
    ) THEN
        RAISE EXCEPTION 'Expected manually verified postgres/BYPASSRLS executor';
    END IF;
    IF (SELECT count(*) FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role')) <> 3 THEN
        RAISE EXCEPTION 'Expected Supabase roles missing';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
               WHERE n.nspname='public' AND c.relname LIKE 'native_push_%') THEN
        RAISE EXCEPTION 'Native Push objects already exist; do not rerun or merge';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_publication WHERE puballtables)
       OR EXISTS (SELECT 1 FROM pg_publication_namespace WHERE pnnspid='public'::regnamespace) THEN
        RAISE EXCEPTION 'Automatic publication would include Native Push tables';
    END IF;
    FOR expected IN SELECT * FROM (VALUES
        ('users','id','integer'),
        ('vehicle_events','event_id','uuid'),
        ('vehicle_events','user_id','integer'),
        ('vehicle_events','vehicle_id','integer'),
        ('vehicle_events','family_id','integer'),
        ('vehicle_events','occurred_at','timestamp with time zone')
    ) AS required(tbl,col,typ) LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
            WHERE a.attrelid=to_regclass('public.' || expected.tbl)
              AND c.relkind='r' AND a.attname=expected.col AND a.attnotnull
              AND NOT a.attisdropped AND format_type(a.atttypid,a.atttypmod)=expected.typ
        ) THEN RAISE EXCEPTION 'Required column mismatch: %.%', expected.tbl, expected.col;
        END IF;
    END LOOP;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint c WHERE c.conrelid='public.users'::regclass
          AND c.contype='p' AND c.convalidated AND NOT c.condeferrable
          AND c.conkey=ARRAY[(SELECT attnum FROM pg_attribute
                              WHERE attrelid=c.conrelid AND attname='id')]::smallint[]
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_constraint c JOIN pg_index i ON i.indexrelid=c.conindid
        WHERE c.conrelid='public.vehicle_events'::regclass AND c.contype='u'
          AND c.convalidated AND NOT c.condeferrable AND i.indisvalid AND i.indisready
          AND c.conkey=ARRAY(SELECT a.attnum FROM unnest(
              ARRAY['event_id','user_id','vehicle_id','family_id']) WITH ORDINALITY AS k(name,ord)
              JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attname=k.name ORDER BY k.ord)
    ) THEN RAISE EXCEPTION 'Required user PK or vehicle event composite unique key missing';
    END IF;
END
$preflight$;

CREATE TABLE public.native_push_installations (
    installation_ref uuid NOT NULL,
    user_id integer NOT NULL,
    platform text NOT NULL CHECK (platform IN ('android','ios')),
    provider text NOT NULL CHECK (provider='fcm'),
    provider_project text NOT NULL CHECK (btrim(provider_project)<>''),
    generation bigint NOT NULL CHECK (generation>0),
    token_ciphertext bytea,
    token_fingerprint bytea CHECK (octet_length(token_fingerprint)=32),
    encryption_key_id text,
    status text NOT NULL CHECK (status IN ('pending','active','revoked','invalid')),
    verified_at timestamptz CHECK (isfinite(verified_at)),
    revoked_at timestamptz CHECK (isfinite(revoked_at)),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK (isfinite(created_at)),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK (isfinite(updated_at)),
    last_seen_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK (isfinite(last_seen_at)),
    CONSTRAINT native_push_installations_pkey PRIMARY KEY (installation_ref),
    CONSTRAINT native_push_installations_owner_key UNIQUE (installation_ref,user_id),
    CONSTRAINT native_push_installations_user_fkey FOREIGN KEY (user_id)
        REFERENCES public.users(id) ON DELETE CASCADE,
    CONSTRAINT native_push_installations_material_check CHECK (
        (token_ciphertext IS NULL AND token_fingerprint IS NULL AND encryption_key_id IS NULL)
        OR (token_ciphertext IS NOT NULL AND octet_length(token_ciphertext)>0
            AND token_fingerprint IS NOT NULL AND encryption_key_id IS NOT NULL AND btrim(encryption_key_id)<>'')),
    CONSTRAINT native_push_installations_active_check CHECK (
        status<>'active' OR (token_ciphertext IS NOT NULL AND verified_at IS NOT NULL AND revoked_at IS NULL)),
    CONSTRAINT native_push_installations_revoked_check CHECK ((status='revoked')=(revoked_at IS NOT NULL)),
    CONSTRAINT native_push_installations_times_check CHECK (updated_at>=created_at AND last_seen_at>=created_at)
);
CREATE UNIQUE INDEX native_push_installations_token_key
    ON public.native_push_installations(provider_project,token_fingerprint) WHERE status='active';
CREATE INDEX native_push_installations_owner_idx ON public.native_push_installations(user_id,status);
CREATE INDEX native_push_installations_cleanup_idx ON public.native_push_installations(status,last_seen_at);

CREATE TABLE public.native_push_registration_challenges (
    challenge_ref uuid NOT NULL,
    installation_ref uuid NOT NULL,
    user_id integer NOT NULL,
    request_id uuid NOT NULL,
    expected_generation bigint NOT NULL CHECK (expected_generation>0),
    candidate_token_ciphertext bytea,
    candidate_fingerprint bytea CHECK (octet_length(candidate_fingerprint)=32),
    encryption_key_id text,
    nonce_hash bytea CHECK (octet_length(nonce_hash)=32),
    nonce_ciphertext bytea,
    status text NOT NULL CHECK (status IN ('pending','consumed','expired','cancelled')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK (isfinite(created_at)),
    expires_at timestamptz NOT NULL CHECK (isfinite(expires_at)),
    send_attempts integer NOT NULL DEFAULT 0 CHECK (send_attempts>=0),
    verify_attempts integer NOT NULL DEFAULT 0 CHECK (verify_attempts>=0),
    next_attempt_at timestamptz CHECK (isfinite(next_attempt_at)),
    lease_token uuid,
    lease_until timestamptz CHECK (isfinite(lease_until)),
    activated_generation bigint,
    CONSTRAINT native_push_registration_challenges_pkey PRIMARY KEY (challenge_ref),
    CONSTRAINT native_push_registration_challenges_request_key UNIQUE (user_id,request_id),
    CONSTRAINT native_push_registration_challenges_owner_fkey FOREIGN KEY (installation_ref,user_id)
        REFERENCES public.native_push_installations(installation_ref,user_id) ON DELETE CASCADE,
    CONSTRAINT native_push_registration_challenges_time_check CHECK (expires_at>created_at),
    CONSTRAINT native_push_registration_challenges_lease_check CHECK (
        (lease_token IS NULL)=(lease_until IS NULL)
        AND (lease_until IS NULL OR (status='pending' AND lease_until>created_at AND lease_until<=expires_at))),
    CONSTRAINT native_push_registration_challenges_state_check CHECK (
        (status='pending' AND candidate_token_ciphertext IS NOT NULL AND octet_length(candidate_token_ciphertext)>0
         AND candidate_fingerprint IS NOT NULL AND encryption_key_id IS NOT NULL AND btrim(encryption_key_id)<>''
         AND nonce_hash IS NOT NULL AND nonce_ciphertext IS NOT NULL AND octet_length(nonce_ciphertext)>0
         AND activated_generation IS NULL AND next_attempt_at IS NOT NULL
         AND next_attempt_at>=created_at AND next_attempt_at<expires_at)
        OR (status<>'pending' AND candidate_token_ciphertext IS NULL AND candidate_fingerprint IS NULL
            AND encryption_key_id IS NULL AND nonce_hash IS NULL AND nonce_ciphertext IS NULL
            AND next_attempt_at IS NULL AND lease_token IS NULL AND lease_until IS NULL
            AND ((status='consumed' AND activated_generation IS NOT NULL AND activated_generation>expected_generation)
                 OR (status IN ('expired','cancelled') AND activated_generation IS NULL))))
);
CREATE UNIQUE INDEX native_push_registration_challenges_pending_key
    ON public.native_push_registration_challenges(installation_ref) WHERE status='pending';
CREATE INDEX native_push_registration_challenges_owner_idx
    ON public.native_push_registration_challenges(installation_ref,user_id);
CREATE INDEX native_push_registration_challenges_due_idx
    ON public.native_push_registration_challenges(next_attempt_at,challenge_ref) WHERE status='pending' AND lease_token IS NULL;
CREATE INDEX native_push_registration_challenges_lease_idx
    ON public.native_push_registration_challenges(lease_until) WHERE status='pending' AND lease_token IS NOT NULL;
CREATE INDEX native_push_registration_challenges_cleanup_idx
    ON public.native_push_registration_challenges(expires_at);

CREATE TABLE public.native_push_events (
    event_ref uuid NOT NULL,
    source_event_id uuid NOT NULL,
    family_id integer NOT NULL,
    actor_user_id integer NOT NULL,
    vehicle_id integer NOT NULL,
    event_type text NOT NULL CHECK (event_type IN ('vehicle_taken','vehicle_returned')),
    occurred_at timestamptz NOT NULL CHECK (isfinite(occurred_at)),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK (isfinite(created_at)),
    expires_at timestamptz NOT NULL CHECK (isfinite(expires_at)),
    status text NOT NULL CHECK (status IN ('pending','complete','expired','cancelled')),
    CONSTRAINT native_push_events_pkey PRIMARY KEY (event_ref),
    CONSTRAINT native_push_events_source_key UNIQUE (source_event_id,event_type),
    CONSTRAINT native_push_events_source_fkey FOREIGN KEY (source_event_id,actor_user_id,vehicle_id,family_id)
        REFERENCES public.vehicle_events(event_id,user_id,vehicle_id,family_id) ON DELETE CASCADE,
    CONSTRAINT native_push_events_ttl_check CHECK (expires_at=occurred_at+INTERVAL '5 minutes')
);
CREATE INDEX native_push_events_expiry_idx ON public.native_push_events(status,expires_at);
CREATE INDEX native_push_events_family_idx ON public.native_push_events(family_id);

CREATE TABLE public.native_push_deliveries (
    delivery_ref uuid NOT NULL,
    event_ref uuid NOT NULL,
    installation_ref uuid NOT NULL,
    recipient_user_id integer NOT NULL,
    installation_generation bigint NOT NULL CHECK (installation_generation>0),
    status text NOT NULL CHECK (status IN ('pending','leased','retry_wait','accepted','expired','cancelled','failed')),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count>=0),
    next_attempt_at timestamptz CHECK (isfinite(next_attempt_at)),
    lease_token uuid,
    lease_until timestamptz CHECK (isfinite(lease_until)),
    accepted_at timestamptz CHECK (isfinite(accepted_at)),
    last_error_code text CHECK (last_error_code IN (
        'unregistered','rate_limited','provider_unavailable','transport_uncertain',
        'configuration','invalid_payload','generation_changed','identity_unavailable','expired')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK (isfinite(created_at)),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK (isfinite(updated_at)),
    CONSTRAINT native_push_deliveries_pkey PRIMARY KEY (delivery_ref),
    CONSTRAINT native_push_deliveries_target_key UNIQUE (event_ref,installation_ref),
    CONSTRAINT native_push_deliveries_event_fkey FOREIGN KEY (event_ref)
        REFERENCES public.native_push_events(event_ref) ON DELETE CASCADE,
    CONSTRAINT native_push_deliveries_owner_fkey FOREIGN KEY (installation_ref,recipient_user_id)
        REFERENCES public.native_push_installations(installation_ref,user_id) ON DELETE CASCADE,
    CONSTRAINT native_push_deliveries_lease_check CHECK (
        (status='leased' AND lease_token IS NOT NULL AND lease_until IS NOT NULL AND lease_until>created_at)
        OR (status<>'leased' AND lease_token IS NULL AND lease_until IS NULL)),
    CONSTRAINT native_push_deliveries_acceptance_check CHECK ((status='accepted')=(accepted_at IS NOT NULL)),
    CONSTRAINT native_push_deliveries_schedule_check CHECK (
        (status IN ('pending','retry_wait') AND next_attempt_at IS NOT NULL AND next_attempt_at>=created_at)
        OR (status NOT IN ('pending','retry_wait') AND next_attempt_at IS NULL)),
    CONSTRAINT native_push_deliveries_times_check CHECK (updated_at>=created_at AND (accepted_at IS NULL OR accepted_at>=created_at))
);
CREATE INDEX native_push_deliveries_owner_idx ON public.native_push_deliveries(installation_ref,recipient_user_id);
CREATE INDEX native_push_deliveries_due_idx ON public.native_push_deliveries(next_attempt_at,delivery_ref)
    WHERE status IN ('pending','retry_wait');
CREATE INDEX native_push_deliveries_lease_idx ON public.native_push_deliveries(lease_until)
    WHERE status='leased';
CREATE INDEX native_push_deliveries_cleanup_idx ON public.native_push_deliveries(status,updated_at);

-- Remove inherited default grants on THESE new objects only. No global defaults change.
-- postgres owns the objects; ownership/BYPASSRLS means API authorization is mandatory.
DO $security$
DECLARE
    t text;
    cols text;
    grantee_name text;
BEGIN
    FOREACH t IN ARRAY ARRAY['native_push_installations','native_push_registration_challenges',
                             'native_push_events','native_push_deliveries'] LOOP
        EXECUTE format('ALTER TABLE public.%I OWNER TO postgres',t);
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
        EXECUTE format('ALTER TABLE public.%I NO FORCE ROW LEVEL SECURITY',t);
        SELECT string_agg(format('%I',attname),', ' ORDER BY attnum) INTO cols
        FROM pg_attribute WHERE attrelid=to_regclass('public.'||t) AND attnum>0 AND NOT attisdropped;
        EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE public.%I FROM PUBLIC, anon, authenticated, service_role',t);
        EXECUTE format('REVOKE ALL PRIVILEGES (%s) ON TABLE public.%I FROM PUBLIC, anon, authenticated, service_role',cols,t);
        FOR grantee_name IN
            SELECT DISTINCT r.rolname FROM pg_class c
            CROSS JOIN LATERAL aclexplode(c.relacl) a JOIN pg_roles r ON r.oid=a.grantee
            WHERE c.oid=to_regclass('public.'||t) AND r.rolname<>'postgres'
        LOOP
            EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE public.%I FROM %I',t,grantee_name);
            EXECUTE format('REVOKE ALL PRIVILEGES (%s) ON TABLE public.%I FROM %I',cols,t,grantee_name);
        END LOOP;
        IF EXISTS (SELECT 1 FROM pg_roles r WHERE r.rolname IN ('anon','authenticated','service_role')
            AND (has_table_privilege(r.oid,to_regclass('public.'||t),'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                 OR has_any_column_privilege(r.oid,to_regclass('public.'||t),'SELECT,INSERT,UPDATE,REFERENCES'))) THEN
            RAISE EXCEPTION 'Unexpected effective privilege on %',t;
        END IF;
    END LOOP;
END
$security$;
COMMIT;
