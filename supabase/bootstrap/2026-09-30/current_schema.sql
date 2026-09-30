-- FCA CURRENT-STATE CHECKPOINT: 2026-09-30. FRESH ISOLATED SUPABASE ONLY.
-- NEVER apply to existing Production. No application data or sequence counters.
-- Read README.md. Not executed/clean-rebuild validated; historical SQL is not replayed.
BEGIN;
SET LOCAL search_path = public, pg_catalog;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';
DO $checkpoint_guard$
BEGIN
    IF current_setting('fca.allow_empty_checkpoint', true) IS DISTINCT FROM '2026-09-30' THEN
        RAISE EXCEPTION 'Checkpoint disabled: requires explicit isolated empty-environment approval';
    END IF;
    IF current_user <> 'postgres' OR current_setting('server_version_num')::integer < 170000 THEN
        RAISE EXCEPTION 'Requires postgres and PostgreSQL 17+ (including MAINTAIN privilege)';
    END IF;
    IF EXISTS (SELECT 1 FROM (VALUES ('anon'), ('authenticated'), ('service_role')) AS r(name)
               WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=r.name)) THEN
        RAISE EXCEPTION 'Missing Supabase roles';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN ('anon', 'authenticated')
               AND (rolsuper OR rolbypassrls))
       OR EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN ('postgres', 'service_role')
                  AND NOT rolbypassrls)
       OR pg_has_role('anon', 'service_role', 'USAGE')
       OR pg_has_role('authenticated', 'service_role', 'USAGE')
       OR pg_has_role('anon', 'postgres', 'USAGE')
       OR pg_has_role('authenticated', 'postgres', 'USAGE') THEN
        RAISE EXCEPTION 'Unexpected browser/backend role authority';
    END IF;
    IF to_regclass('auth.users') IS NULL OR to_regclass('realtime.messages') IS NULL
       OR to_regprocedure('auth.uid()') IS NULL
       OR to_regprocedure('realtime.topic()') IS NULL
       OR to_regprocedure('realtime.send(jsonb,text,text,boolean)') IS NULL
       OR to_regprocedure('pg_catalog.gen_random_uuid()') IS NULL
       OR NOT EXISTS (SELECT 1 FROM pg_language WHERE lanname='plpgsql') THEN
        RAISE EXCEPTION 'Supabase Auth/Realtime and built-in dependencies must already exist';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_class WHERE oid=to_regclass('realtime.messages')
                   AND relrowsecurity AND NOT relforcerowsecurity) THEN
        RAISE EXCEPTION 'Expected provider-managed Realtime RLS configuration';
    END IF;

    IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
               WHERE n.nspname='public' AND c.relname IN ('account_deletion_jobs', 'car_events', 'carplay_transition_admissions', 'carplay_vehicle_bindings', 'chat_requests', 'chat_tool_actions', 'conversation_messages', 'families', 'family_address_confirmations', 'family_code_history', 'gemini_call_permits', 'gemini_capacity_policies', 'geocoding_attempts', 'geocoding_capacity_policies', 'push_subscriptions', 'pwa_join_sessions', 'registered_device_vehicle_bindings', 'registered_devices', 'reservations', 'users', 'vehicle_driver_sessions', 'vehicle_events', 'vehicles', 'car_events_id_seq', 'chat_requests_id_seq', 'chat_tool_actions_id_seq', 'conversation_messages_id_seq', 'families_id_seq', 'push_subscriptions_id_seq', 'registered_devices_id_seq', 'reservations_id_seq', 'users_id_seq', 'vehicle_driver_sessions_id_seq', 'vehicle_events_id_seq', 'vehicles_id_seq'))
       OR EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                  WHERE n.nspname='public' AND p.proname IN ('broadcast_car_status_changed', 'broadcast_vehicle_member_deleted', 'can_receive_car_status_topic', 'guard_vehicle_checkpoint', 'guard_vehicle_event_evidence'))
       OR EXISTS (SELECT 1 FROM pg_policy WHERE polrelid=to_regclass('realtime.messages')
                  AND polname='family_members_receive_car_status') THEN
        RAISE EXCEPTION 'Existing FCA objects: checkpoint cannot upgrade or replace a database';
    END IF;
END
$checkpoint_guard$;

-- Phase 1: serial sequences, then all tables WITHOUT inter-table constraints.

CREATE SEQUENCE public."car_events_id_seq" AS integer START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 CACHE 1 NO CYCLE;

CREATE SEQUENCE public."chat_requests_id_seq" AS bigint START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 CACHE 1 NO CYCLE;

CREATE SEQUENCE public."chat_tool_actions_id_seq" AS bigint START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 CACHE 1 NO CYCLE;

CREATE SEQUENCE public."conversation_messages_id_seq" AS integer START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 CACHE 1 NO CYCLE;

CREATE SEQUENCE public."families_id_seq" AS integer START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 CACHE 1 NO CYCLE;

CREATE SEQUENCE public."reservations_id_seq" AS integer START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 CACHE 1 NO CYCLE;

CREATE SEQUENCE public."users_id_seq" AS integer START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 CACHE 1 NO CYCLE;

CREATE TABLE public."account_deletion_jobs" (
    "auth_user_id" uuid NOT NULL,
    "phase" text COLLATE pg_catalog."default" DEFAULT 'draining'::text NOT NULL,
    "created_at" timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    "next_attempt_at" timestamp with time zone DEFAULT clock_timestamp() NOT NULL
);

ALTER TABLE public."account_deletion_jobs" OWNER TO postgres;

CREATE TABLE public."car_events" (
    "id" integer DEFAULT nextval('car_events_id_seq'::regclass) NOT NULL,
    "driver_name" text COLLATE pg_catalog."default" NOT NULL,
    "status" text COLLATE pg_catalog."default" NOT NULL,
    "event_time" text COLLATE pg_catalog."default" NOT NULL,
    "family_id" integer,
    "user_id" integer
);

ALTER TABLE public."car_events" OWNER TO postgres;

CREATE TABLE public."carplay_transition_admissions" (
    "admission_id" uuid NOT NULL,
    "user_id" integer NOT NULL,
    "family_id" integer NOT NULL,
    "admitted_at" timestamp with time zone DEFAULT clock_timestamp() NOT NULL
);

ALTER TABLE public."carplay_transition_admissions" OWNER TO postgres;

CREATE TABLE public."carplay_vehicle_bindings" (
    "user_id" integer NOT NULL,
    "family_id" integer NOT NULL,
    "vehicle_id" integer NOT NULL
);

ALTER TABLE public."carplay_vehicle_bindings" OWNER TO postgres;

CREATE TABLE public."chat_requests" (
    "id" bigint DEFAULT nextval('chat_requests_id_seq'::regclass) NOT NULL,
    "request_id" uuid NOT NULL,
    "user_id" integer NOT NULL,
    "family_id" integer NOT NULL,
    "status" text COLLATE pg_catalog."default" DEFAULT 'processing'::text NOT NULL,
    "original_message" text COLLATE pg_catalog."default" NOT NULL,
    "final_response" jsonb,
    "error_http_status" smallint,
    "error_payload" jsonb,
    "lease_token" uuid NOT NULL,
    "lease_expires_at" timestamp with time zone NOT NULL,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now() NOT NULL,
    "completed_at" timestamp with time zone,
    "processing_attempts" smallint DEFAULT 1 NOT NULL
);

ALTER TABLE public."chat_requests" OWNER TO postgres;

CREATE TABLE public."chat_tool_actions" (
    "id" bigint DEFAULT nextval('chat_tool_actions_id_seq'::regclass) NOT NULL,
    "chat_request_id" bigint NOT NULL,
    "action_type" text COLLATE pg_catalog."default" NOT NULL,
    "arguments" jsonb NOT NULL,
    "status" text COLLATE pg_catalog."default" NOT NULL,
    "result" jsonb,
    "error_payload" jsonb,
    "lease_token_at_execution" uuid NOT NULL,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "completed_at" timestamp with time zone
);

ALTER TABLE public."chat_tool_actions" OWNER TO postgres;

CREATE TABLE public."conversation_messages" (
    "id" integer DEFAULT nextval('conversation_messages_id_seq'::regclass) NOT NULL,
    "user_id" integer NOT NULL,
    "role" text COLLATE pg_catalog."default" NOT NULL,
    "content" text COLLATE pg_catalog."default" NOT NULL,
    "created_at" text COLLATE pg_catalog."default" NOT NULL,
    "chat_request_id" bigint
);

ALTER TABLE public."conversation_messages" OWNER TO postgres;

CREATE TABLE public."families" (
    "id" integer DEFAULT nextval('families_id_seq'::regclass) NOT NULL,
    "name" text COLLATE pg_catalog."default" NOT NULL,
    "family_code" text COLLATE pg_catalog."default" NOT NULL,
    "home_address" text COLLATE pg_catalog."default" NOT NULL,
    "home_latitude" double precision,
    "home_longitude" double precision,
    "created_at" text COLLATE pg_catalog."default" NOT NULL,
    "created_by_user_id" integer NOT NULL,
    "vehicle_reconciliation_generation" bigint DEFAULT 0 NOT NULL,
    "vehicle_finalized_through" timestamp with time zone,
    "device_identities_created" bigint DEFAULT 0 NOT NULL
);

ALTER TABLE public."families" OWNER TO postgres;

CREATE TABLE public."family_address_confirmations" (
    "token_digest" bytea NOT NULL,
    "purpose" text COLLATE pg_catalog."default" NOT NULL,
    "auth_user_id" uuid NOT NULL,
    "user_id" integer,
    "family_id" integer,
    "normalized_address" text COLLATE pg_catalog."default" NOT NULL,
    "display_address" text COLLATE pg_catalog."default" NOT NULL,
    "latitude" double precision NOT NULL,
    "longitude" double precision NOT NULL,
    "expires_at" timestamp with time zone DEFAULT (clock_timestamp() + '00:15:00'::interval) NOT NULL
);

ALTER TABLE public."family_address_confirmations" OWNER TO postgres;

CREATE TABLE public."family_code_history" (
    "code" text COLLATE pg_catalog."C" NOT NULL
);

ALTER TABLE public."family_code_history" OWNER TO postgres;

CREATE TABLE public."gemini_call_permits" (
    "permit_id" uuid NOT NULL,
    "chat_request_id" bigint NOT NULL,
    "attempt_token" uuid NOT NULL,
    "capacity_pool" text COLLATE pg_catalog."default" NOT NULL,
    "acquired_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "expires_at" timestamp with time zone NOT NULL
);

ALTER TABLE public."gemini_call_permits" OWNER TO postgres;

CREATE TABLE public."gemini_capacity_policies" (
    "capacity_pool" text COLLATE pg_catalog."default" NOT NULL,
    "max_concurrency" integer NOT NULL,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

ALTER TABLE public."gemini_capacity_policies" OWNER TO postgres;

CREATE TABLE public."geocoding_attempts" (
    "attempt_id" uuid NOT NULL,
    "auth_user_id" uuid NOT NULL,
    "capacity_pool" text COLLATE pg_catalog."default" NOT NULL,
    "admitted_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "permit_expires_at" timestamp with time zone
);

ALTER TABLE public."geocoding_attempts" OWNER TO postgres;

CREATE TABLE public."geocoding_capacity_policies" (
    "capacity_pool" text COLLATE pg_catalog."default" NOT NULL,
    "max_concurrency" integer NOT NULL,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

ALTER TABLE public."geocoding_capacity_policies" OWNER TO postgres;

CREATE TABLE public."push_subscriptions" (
    "id" bigint GENERATED BY DEFAULT AS IDENTITY (SEQUENCE NAME public."push_subscriptions_id_seq" START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 CACHE 1 NO CYCLE) NOT NULL,
    "user_id" integer NOT NULL,
    "endpoint" text COLLATE pg_catalog."default" NOT NULL,
    "p256dh" text COLLATE pg_catalog."default" NOT NULL,
    "auth" text COLLATE pg_catalog."default" NOT NULL,
    "expiration_time" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE public."push_subscriptions" OWNER TO postgres;

CREATE TABLE public."pwa_join_sessions" (
    "auth_user_id" uuid NOT NULL,
    "step" text COLLATE pg_catalog."default" DEFAULT 'family_name'::text NOT NULL,
    "family_name" text COLLATE pg_catalog."default",
    "family_id" integer,
    "normalized_address" text COLLATE pg_catalog."default",
    "resolved_address" text COLLATE pg_catalog."default",
    "family_name_attempts" smallint DEFAULT 0 NOT NULL,
    "address_attempts" smallint DEFAULT 0 NOT NULL,
    "family_code_attempts" smallint DEFAULT 0 NOT NULL,
    "locked_until" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE public."pwa_join_sessions" OWNER TO postgres;

CREATE TABLE public."registered_device_vehicle_bindings" (
    "device_id" integer NOT NULL,
    "vehicle_id" integer NOT NULL
);

ALTER TABLE public."registered_device_vehicle_bindings" OWNER TO postgres;

CREATE TABLE public."registered_devices" (
    "id" integer GENERATED BY DEFAULT AS IDENTITY (SEQUENCE NAME public."registered_devices_id_seq" START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 CACHE 1 NO CYCLE) NOT NULL,
    "device_ref" uuid DEFAULT gen_random_uuid() NOT NULL,
    "user_id" integer NOT NULL,
    "platform" text COLLATE pg_catalog."default" NOT NULL,
    "created_at" timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    "last_seen_at" timestamp with time zone,
    "revoked_at" timestamp with time zone,
    "last_processed_sequence" bigint DEFAULT 0 NOT NULL,
    "creation_request_id" uuid,
    "creation_fingerprint" bytea
);

ALTER TABLE public."registered_devices" OWNER TO postgres;

CREATE TABLE public."reservations" (
    "id" integer DEFAULT nextval('reservations_id_seq'::regclass) NOT NULL,
    "user_id" integer NOT NULL,
    "start_time" text COLLATE pg_catalog."default" NOT NULL,
    "end_time" text COLLATE pg_catalog."default" NOT NULL,
    "status" text COLLATE pg_catalog."default" DEFAULT 'active'::text NOT NULL,
    "created_at" text COLLATE pg_catalog."default" NOT NULL,
    "reservation_ref" uuid DEFAULT gen_random_uuid() NOT NULL,
    "vehicle_id" integer
);

ALTER TABLE public."reservations" OWNER TO postgres;

CREATE TABLE public."users" (
    "id" integer DEFAULT nextval('users_id_seq'::regclass) NOT NULL,
    "name" text COLLATE pg_catalog."default" NOT NULL,
    "shortcut_token" text COLLATE pg_catalog."default",
    "telegram_chat_id" bigint,
    "family_id" integer,
    "auth_user_id" uuid,
    "carplay_setup_status" text COLLATE pg_catalog."default" DEFAULT 'pending'::text NOT NULL,
    "family_role" text COLLATE pg_catalog."default",
    "member_public_id" uuid DEFAULT gen_random_uuid() NOT NULL
);

ALTER TABLE public."users" OWNER TO postgres;

CREATE TABLE public."vehicle_driver_sessions" (
    "id" bigint GENERATED BY DEFAULT AS IDENTITY (SEQUENCE NAME public."vehicle_driver_sessions_id_seq" START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 CACHE 1 NO CYCLE) NOT NULL,
    "session_ref" uuid DEFAULT gen_random_uuid() NOT NULL,
    "family_id" integer NOT NULL,
    "vehicle_id" integer NOT NULL,
    "user_id" integer NOT NULL,
    "started_at" timestamp with time zone NOT NULL,
    "ended_at" timestamp with time zone,
    "start_event_id" uuid,
    "end_event_id" uuid,
    "end_reason" text COLLATE pg_catalog."default",
    "created_at" timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    "checkpoint_generation" bigint
);

ALTER TABLE public."vehicle_driver_sessions" OWNER TO postgres;

CREATE TABLE public."vehicle_events" (
    "id" bigint GENERATED BY DEFAULT AS IDENTITY (SEQUENCE NAME public."vehicle_events_id_seq" START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 CACHE 1 NO CYCLE) NOT NULL,
    "event_id" uuid NOT NULL,
    "family_id" integer NOT NULL,
    "vehicle_id" integer NOT NULL,
    "user_id" integer NOT NULL,
    "device_id" integer,
    "source" text COLLATE pg_catalog."default" NOT NULL,
    "event_type" text COLLATE pg_catalog."default" NOT NULL,
    "device_sequence" bigint,
    "occurred_at" timestamp with time zone NOT NULL,
    "received_at" timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    "admission_outcome" text COLLATE pg_catalog."default" NOT NULL,
    "take_event_id" uuid,
    "projection_take_event_id" uuid
);

ALTER TABLE public."vehicle_events" OWNER TO postgres;

CREATE TABLE public."vehicles" (
    "id" integer GENERATED BY DEFAULT AS IDENTITY (SEQUENCE NAME public."vehicles_id_seq" START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 CACHE 1 NO CYCLE) NOT NULL,
    "vehicle_ref" uuid DEFAULT gen_random_uuid() NOT NULL,
    "family_id" integer NOT NULL,
    "display_name" text COLLATE pg_catalog."default" NOT NULL,
    "created_by_user_id" integer,
    "created_at" timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    "retired_at" timestamp with time zone,
    "creation_request_id" uuid,
    "creation_fingerprint" bytea
);

ALTER TABLE public."vehicles" OWNER TO postgres;

ALTER SEQUENCE public."car_events_id_seq" OWNER TO postgres;

ALTER SEQUENCE public."car_events_id_seq" OWNED BY public."car_events"."id";

ALTER SEQUENCE public."chat_requests_id_seq" OWNER TO postgres;

ALTER SEQUENCE public."chat_requests_id_seq" OWNED BY public."chat_requests"."id";

ALTER SEQUENCE public."chat_tool_actions_id_seq" OWNER TO postgres;

ALTER SEQUENCE public."chat_tool_actions_id_seq" OWNED BY public."chat_tool_actions"."id";

ALTER SEQUENCE public."conversation_messages_id_seq" OWNER TO postgres;

ALTER SEQUENCE public."conversation_messages_id_seq" OWNED BY public."conversation_messages"."id";

ALTER SEQUENCE public."families_id_seq" OWNER TO postgres;

ALTER SEQUENCE public."families_id_seq" OWNED BY public."families"."id";

ALTER SEQUENCE public."push_subscriptions_id_seq" OWNER TO postgres;

ALTER SEQUENCE public."registered_devices_id_seq" OWNER TO postgres;

ALTER SEQUENCE public."reservations_id_seq" OWNER TO postgres;

ALTER SEQUENCE public."reservations_id_seq" OWNED BY public."reservations"."id";

ALTER SEQUENCE public."users_id_seq" OWNER TO postgres;

ALTER SEQUENCE public."users_id_seq" OWNED BY public."users"."id";

ALTER SEQUENCE public."vehicle_driver_sessions_id_seq" OWNER TO postgres;

ALTER SEQUENCE public."vehicle_events_id_seq" OWNER TO postgres;

ALTER SEQUENCE public."vehicles_id_seq" OWNER TO postgres;

-- Phase 2: referenced keys/checks/exclusions BEFORE all foreign keys (including cycles).

ALTER TABLE public."account_deletion_jobs" ADD CONSTRAINT "account_deletion_jobs_check" CHECK ((next_attempt_at >= created_at));

ALTER TABLE public."account_deletion_jobs" ADD CONSTRAINT "account_deletion_jobs_created_at_check" CHECK (isfinite(created_at));

ALTER TABLE public."account_deletion_jobs" ADD CONSTRAINT "account_deletion_jobs_next_attempt_at_check" CHECK (isfinite(next_attempt_at));

ALTER TABLE public."account_deletion_jobs" ADD CONSTRAINT "account_deletion_jobs_phase_check" CHECK ((phase = ANY (ARRAY['draining'::text, 'auth_pending'::text])));

ALTER TABLE public."account_deletion_jobs" ADD CONSTRAINT "account_deletion_jobs_pkey" PRIMARY KEY (auth_user_id);

ALTER TABLE public."car_events" ADD CONSTRAINT "car_events_pkey" PRIMARY KEY (id);

ALTER TABLE public."carplay_transition_admissions" ADD CONSTRAINT "carplay_transition_admissions_admitted_at_check" CHECK (isfinite(admitted_at));

ALTER TABLE public."carplay_transition_admissions" ADD CONSTRAINT "carplay_transition_admissions_pkey" PRIMARY KEY (admission_id);

ALTER TABLE public."carplay_vehicle_bindings" ADD CONSTRAINT "carplay_vehicle_bindings_pkey" PRIMARY KEY (user_id);

ALTER TABLE public."chat_requests" ADD CONSTRAINT "chat_requests_error_status_check" CHECK (((error_http_status IS NULL) OR ((error_http_status >= 400) AND (error_http_status <= 599))));

ALTER TABLE public."chat_requests" ADD CONSTRAINT "chat_requests_message_check" CHECK (((char_length(btrim(original_message)) >= 1) AND (char_length(btrim(original_message)) <= 4000)));

ALTER TABLE public."chat_requests" ADD CONSTRAINT "chat_requests_pkey" PRIMARY KEY (id);

ALTER TABLE public."chat_requests" ADD CONSTRAINT "chat_requests_processing_attempts_check" CHECK (((processing_attempts >= 1) AND (processing_attempts <= 3)));

ALTER TABLE public."chat_requests" ADD CONSTRAINT "chat_requests_state_check" CHECK ((((status = 'processing'::text) AND (final_response IS NULL) AND (error_payload IS NULL) AND (completed_at IS NULL)) OR ((status = 'completed'::text) AND (final_response IS NOT NULL) AND (error_payload IS NULL) AND (error_http_status IS NULL) AND (completed_at IS NOT NULL)) OR ((status = 'failed'::text) AND (final_response IS NULL) AND (error_payload IS NOT NULL) AND (error_http_status IS NOT NULL) AND (completed_at IS NOT NULL))));

ALTER TABLE public."chat_requests" ADD CONSTRAINT "chat_requests_status_check" CHECK ((status = ANY (ARRAY['processing'::text, 'completed'::text, 'failed'::text])));

ALTER TABLE public."chat_requests" ADD CONSTRAINT "chat_requests_user_request_unique" UNIQUE (user_id, request_id);

ALTER TABLE public."chat_tool_actions" ADD CONSTRAINT "chat_tool_actions_pkey" PRIMARY KEY (id);

ALTER TABLE public."chat_tool_actions" ADD CONSTRAINT "chat_tool_actions_request_unique" UNIQUE (chat_request_id);

ALTER TABLE public."chat_tool_actions" ADD CONSTRAINT "chat_tool_actions_state_check" CHECK ((((status = 'processing'::text) AND (result IS NULL) AND (error_payload IS NULL) AND (completed_at IS NULL)) OR ((status = 'completed'::text) AND (result IS NOT NULL) AND (error_payload IS NULL) AND (completed_at IS NOT NULL)) OR ((status = 'failed'::text) AND (result IS NULL) AND (error_payload IS NOT NULL) AND (completed_at IS NOT NULL))));

ALTER TABLE public."chat_tool_actions" ADD CONSTRAINT "chat_tool_actions_status_check" CHECK ((status = ANY (ARRAY['processing'::text, 'completed'::text, 'failed'::text])));

ALTER TABLE public."chat_tool_actions" ADD CONSTRAINT "chat_tool_actions_type_check" CHECK ((action_type = ANY (ARRAY['create_reservation'::text, 'update_reservation'::text, 'cancel_reservation'::text])));

ALTER TABLE public."conversation_messages" ADD CONSTRAINT "conversation_messages_pkey" PRIMARY KEY (id);

ALTER TABLE public."families" ADD CONSTRAINT "families_device_identities_created_check" CHECK ((device_identities_created >= 0));

ALTER TABLE public."families" ADD CONSTRAINT "families_family_code_key" UNIQUE (family_code);

ALTER TABLE public."families" ADD CONSTRAINT "families_pkey" PRIMARY KEY (id);

ALTER TABLE public."families" ADD CONSTRAINT "families_vehicle_checkpoint_check" CHECK ((((vehicle_reconciliation_generation = 0) AND (vehicle_finalized_through IS NULL)) OR ((vehicle_reconciliation_generation > 0) AND (vehicle_finalized_through IS NOT NULL) AND isfinite(vehicle_finalized_through))));

ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_binding_check" CHECK ((((purpose = 'create_family'::text) AND (user_id IS NULL) AND (family_id IS NULL)) OR ((purpose = 'family_address_update'::text) AND (user_id IS NOT NULL) AND (family_id IS NOT NULL))));

ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_display_address_check" CHECK ((btrim(display_address) <> ''::text));

ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_expires_at_check" CHECK (isfinite(expires_at));

ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_latitude_check" CHECK (((latitude >= ('-90'::integer)::double precision) AND (latitude <= (90)::double precision)));

ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_longitude_check" CHECK (((longitude >= ('-180'::integer)::double precision) AND (longitude <= (180)::double precision)));

ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_normalized_address_check" CHECK ((btrim(normalized_address) <> ''::text));

ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_pkey" PRIMARY KEY (token_digest);

ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_purpose_check" CHECK ((purpose = ANY (ARRAY['create_family'::text, 'family_address_update'::text])));

ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_token_digest_check" CHECK ((octet_length(token_digest) = 32));

ALTER TABLE public."family_code_history" ADD CONSTRAINT "family_code_history_code_check" CHECK (((octet_length(code) = 6) AND (code ~ '^[a-z0-9]{6}$'::text)));

ALTER TABLE public."family_code_history" ADD CONSTRAINT "family_code_history_pkey" PRIMARY KEY (code);

ALTER TABLE public."gemini_call_permits" ADD CONSTRAINT "gemini_call_permits_chat_request_id_key" UNIQUE (chat_request_id);

ALTER TABLE public."gemini_call_permits" ADD CONSTRAINT "gemini_call_permits_check" CHECK ((isfinite(acquired_at) AND isfinite(expires_at) AND (expires_at > acquired_at)));

ALTER TABLE public."gemini_call_permits" ADD CONSTRAINT "gemini_call_permits_pkey" PRIMARY KEY (permit_id);

ALTER TABLE public."gemini_capacity_policies" ADD CONSTRAINT "gemini_capacity_policies_capacity_pool_check" CHECK (((capacity_pool <> ''::text) AND (capacity_pool = btrim(capacity_pool))));

ALTER TABLE public."gemini_capacity_policies" ADD CONSTRAINT "gemini_capacity_policies_max_concurrency_check" CHECK ((max_concurrency > 0));

ALTER TABLE public."gemini_capacity_policies" ADD CONSTRAINT "gemini_capacity_policies_pkey" PRIMARY KEY (capacity_pool);

ALTER TABLE public."geocoding_attempts" ADD CONSTRAINT "geocoding_attempts_check" CHECK ((isfinite(admitted_at) AND ((permit_expires_at IS NULL) OR (isfinite(permit_expires_at) AND (permit_expires_at > admitted_at)))));

ALTER TABLE public."geocoding_attempts" ADD CONSTRAINT "geocoding_attempts_pkey" PRIMARY KEY (attempt_id);

ALTER TABLE public."geocoding_capacity_policies" ADD CONSTRAINT "geocoding_capacity_policies_capacity_pool_check" CHECK (((capacity_pool <> ''::text) AND (capacity_pool = btrim(capacity_pool))));

ALTER TABLE public."geocoding_capacity_policies" ADD CONSTRAINT "geocoding_capacity_policies_max_concurrency_check" CHECK ((max_concurrency > 0));

ALTER TABLE public."geocoding_capacity_policies" ADD CONSTRAINT "geocoding_capacity_policies_pkey" PRIMARY KEY (capacity_pool);

ALTER TABLE public."push_subscriptions" ADD CONSTRAINT "push_subscriptions_auth_nonempty_check" CHECK ((length(auth) > 0));

ALTER TABLE public."push_subscriptions" ADD CONSTRAINT "push_subscriptions_endpoint_key" UNIQUE (endpoint);

ALTER TABLE public."push_subscriptions" ADD CONSTRAINT "push_subscriptions_endpoint_nonempty_check" CHECK ((length(btrim(endpoint)) > 0));

ALTER TABLE public."push_subscriptions" ADD CONSTRAINT "push_subscriptions_p256dh_nonempty_check" CHECK ((length(p256dh) > 0));

ALTER TABLE public."push_subscriptions" ADD CONSTRAINT "push_subscriptions_pkey" PRIMARY KEY (id);

ALTER TABLE public."pwa_join_sessions" ADD CONSTRAINT "pwa_join_sessions_address_attempts_check" CHECK (((address_attempts >= 0) AND (address_attempts <= 3)));

ALTER TABLE public."pwa_join_sessions" ADD CONSTRAINT "pwa_join_sessions_family_code_attempts_check" CHECK (((family_code_attempts >= 0) AND (family_code_attempts <= 3)));

ALTER TABLE public."pwa_join_sessions" ADD CONSTRAINT "pwa_join_sessions_family_name_attempts_check" CHECK (((family_name_attempts >= 0) AND (family_name_attempts <= 3)));

ALTER TABLE public."pwa_join_sessions" ADD CONSTRAINT "pwa_join_sessions_pkey" PRIMARY KEY (auth_user_id);

ALTER TABLE public."pwa_join_sessions" ADD CONSTRAINT "pwa_join_sessions_step_check" CHECK ((step = ANY (ARRAY['family_name'::text, 'address'::text, 'address_confirmed'::text, 'family_code'::text, 'user_name'::text, 'locked'::text])));

ALTER TABLE public."registered_device_vehicle_bindings" ADD CONSTRAINT "registered_device_vehicle_bindings_pkey" PRIMARY KEY (device_id, vehicle_id);

ALTER TABLE public."registered_devices" ADD CONSTRAINT "devices_creation_metadata_check" CHECK ((((creation_request_id IS NULL) AND (creation_fingerprint IS NULL)) OR ((creation_request_id IS NOT NULL) AND (creation_fingerprint IS NOT NULL) AND (octet_length(creation_fingerprint) = 32))));

ALTER TABLE public."registered_devices" ADD CONSTRAINT "devices_creation_request_key" UNIQUE (user_id, creation_request_id);

ALTER TABLE public."registered_devices" ADD CONSTRAINT "registered_devices_check" CHECK ((isfinite(last_seen_at) AND (last_seen_at >= created_at)));

ALTER TABLE public."registered_devices" ADD CONSTRAINT "registered_devices_check1" CHECK ((isfinite(revoked_at) AND (revoked_at >= created_at)));

ALTER TABLE public."registered_devices" ADD CONSTRAINT "registered_devices_created_at_check" CHECK (isfinite(created_at));

ALTER TABLE public."registered_devices" ADD CONSTRAINT "registered_devices_device_ref_key" UNIQUE (device_ref);

ALTER TABLE public."registered_devices" ADD CONSTRAINT "registered_devices_last_processed_sequence_check" CHECK ((last_processed_sequence >= 0));

ALTER TABLE public."registered_devices" ADD CONSTRAINT "registered_devices_owner_key" UNIQUE (id, user_id);

ALTER TABLE public."registered_devices" ADD CONSTRAINT "registered_devices_pkey" PRIMARY KEY (id);

ALTER TABLE public."registered_devices" ADD CONSTRAINT "registered_devices_platform_check" CHECK ((platform = ANY (ARRAY['android'::text, 'ios'::text])));

ALTER TABLE public."reservations" ADD CONSTRAINT "reservations_pkey" PRIMARY KEY (id);

ALTER TABLE public."reservations" ADD CONSTRAINT "reservations_reservation_ref_key" UNIQUE (reservation_ref);

ALTER TABLE public."users" ADD CONSTRAINT "users_auth_user_id_unique" UNIQUE (auth_user_id);

ALTER TABLE public."users" ADD CONSTRAINT "users_carplay_setup_status_check" CHECK ((carplay_setup_status = ANY (ARRAY['pending'::text, 'completed'::text, 'skipped'::text])));

ALTER TABLE public."users" ADD CONSTRAINT "users_family_role_check" CHECK (((family_role IS NULL) OR (family_role = ANY (ARRAY['parent'::text, 'child'::text]))));

ALTER TABLE public."users" ADD CONSTRAINT "users_member_public_id_key" UNIQUE (member_public_id);

ALTER TABLE public."users" ADD CONSTRAINT "users_pkey" PRIMARY KEY (id);

ALTER TABLE public."users" ADD CONSTRAINT "users_shortcut_token_key" UNIQUE (shortcut_token);

ALTER TABLE public."users" ADD CONSTRAINT "users_telegram_chat_id_key" UNIQUE (telegram_chat_id);

ALTER TABLE public."users" ADD CONSTRAINT "users_vehicle_membership_key" UNIQUE (id, family_id);

ALTER TABLE public."vehicle_driver_sessions" ADD CONSTRAINT "vehicle_driver_sessions_checkpoint_generation_check" CHECK ((checkpoint_generation > 0));

ALTER TABLE public."vehicle_driver_sessions" ADD CONSTRAINT "vehicle_driver_sessions_created_at_check" CHECK (isfinite(created_at));

ALTER TABLE public."vehicle_driver_sessions" ADD CONSTRAINT "vehicle_driver_sessions_end_reason_check" CHECK ((end_reason = ANY (ARRAY['return'::text, 'handover'::text, 'vehicle_switch'::text, 'account_deletion'::text])));

ALTER TABLE public."vehicle_driver_sessions" ADD CONSTRAINT "vehicle_driver_sessions_ended_at_check" CHECK (isfinite(ended_at));

ALTER TABLE public."vehicle_driver_sessions" ADD CONSTRAINT "vehicle_driver_sessions_pkey" PRIMARY KEY (id);

ALTER TABLE public."vehicle_driver_sessions" ADD CONSTRAINT "vehicle_driver_sessions_session_ref_key" UNIQUE (session_ref);

ALTER TABLE public."vehicle_driver_sessions" ADD CONSTRAINT "vehicle_driver_sessions_start_event_id_key" UNIQUE (start_event_id);

ALTER TABLE public."vehicle_driver_sessions" ADD CONSTRAINT "vehicle_driver_sessions_started_at_check" CHECK (isfinite(started_at));

ALTER TABLE public."vehicle_driver_sessions" ADD CONSTRAINT "vehicle_sessions_end_check" CHECK ((((ended_at IS NULL) AND (end_reason IS NULL) AND (end_event_id IS NULL)) OR ((ended_at IS NOT NULL) AND (ended_at >= started_at) AND (end_reason IS NOT NULL))));

ALTER TABLE public."vehicle_driver_sessions" ADD CONSTRAINT "vehicle_sessions_user_no_overlap" EXCLUDE USING gist (int8range((user_id)::bigint, (user_id)::bigint, '[]'::text) WITH &&, tstzrange(started_at, ended_at, '[)'::text) WITH &&) DEFERRABLE;

ALTER TABLE public."vehicle_driver_sessions" ADD CONSTRAINT "vehicle_sessions_vehicle_no_overlap" EXCLUDE USING gist (int8range((vehicle_id)::bigint, (vehicle_id)::bigint, '[]'::text) WITH &&, tstzrange(started_at, ended_at, '[)'::text) WITH &&) DEFERRABLE;

ALTER TABLE public."vehicle_events" ADD CONSTRAINT "vehicle_events_admission_outcome_check" CHECK ((admission_outcome = ANY (ARRAY['accepted'::text, 'before_finalized_boundary'::text, 'invalid_chronology'::text, 'reconciliation_policy_exceeded'::text, 'causal_conflict'::text, 'vehicle_retired'::text])));

ALTER TABLE public."vehicle_events" ADD CONSTRAINT "vehicle_events_anchor_identity_key" UNIQUE (event_id, user_id, vehicle_id, family_id);

ALTER TABLE public."vehicle_events" ADD CONSTRAINT "vehicle_events_binding_check" CHECK ((((source = 'native'::text) AND (device_id IS NOT NULL) AND (device_sequence IS NOT NULL)) OR ((source = 'legacy_shortcut'::text) AND (device_id IS NULL) AND (device_sequence IS NULL))));

ALTER TABLE public."vehicle_events" ADD CONSTRAINT "vehicle_events_cause_check" CHECK ((((event_type = 'take'::text) AND (take_event_id IS NULL)) OR ((event_type = 'return'::text) AND (take_event_id IS NOT NULL) AND (take_event_id <> event_id))));

ALTER TABLE public."vehicle_events" ADD CONSTRAINT "vehicle_events_device_sequence_check" CHECK ((device_sequence > 0));

ALTER TABLE public."vehicle_events" ADD CONSTRAINT "vehicle_events_device_sequence_key" UNIQUE (device_id, device_sequence);

ALTER TABLE public."vehicle_events" ADD CONSTRAINT "vehicle_events_event_id_key" UNIQUE (event_id);

ALTER TABLE public."vehicle_events" ADD CONSTRAINT "vehicle_events_event_type_check" CHECK ((event_type = ANY (ARRAY['take'::text, 'return'::text])));

ALTER TABLE public."vehicle_events" ADD CONSTRAINT "vehicle_events_family_identity_key" UNIQUE (event_id, family_id);

ALTER TABLE public."vehicle_events" ADD CONSTRAINT "vehicle_events_occurred_at_check" CHECK (isfinite(occurred_at));

ALTER TABLE public."vehicle_events" ADD CONSTRAINT "vehicle_events_pkey" PRIMARY KEY (id);

ALTER TABLE public."vehicle_events" ADD CONSTRAINT "vehicle_events_projection_check" CHECK (((projection_take_event_id IS NULL) OR (admission_outcome = 'accepted'::text)));

ALTER TABLE public."vehicle_events" ADD CONSTRAINT "vehicle_events_received_at_check" CHECK (isfinite(received_at));

ALTER TABLE public."vehicle_events" ADD CONSTRAINT "vehicle_events_source_check" CHECK ((source = ANY (ARRAY['native'::text, 'legacy_shortcut'::text])));

ALTER TABLE public."vehicles" ADD CONSTRAINT "vehicles_check" CHECK ((isfinite(retired_at) AND (retired_at >= created_at)));

ALTER TABLE public."vehicles" ADD CONSTRAINT "vehicles_created_at_check" CHECK (isfinite(created_at));

ALTER TABLE public."vehicles" ADD CONSTRAINT "vehicles_creation_metadata_check" CHECK ((((creation_request_id IS NULL) AND (creation_fingerprint IS NULL)) OR ((creation_request_id IS NOT NULL) AND (creation_fingerprint IS NOT NULL) AND (octet_length(creation_fingerprint) = 32))));

ALTER TABLE public."vehicles" ADD CONSTRAINT "vehicles_creation_request_key" UNIQUE (family_id, creation_request_id);

ALTER TABLE public."vehicles" ADD CONSTRAINT "vehicles_display_name_check" CHECK ((display_name !~ '^[[:space:]]*$'::text));

ALTER TABLE public."vehicles" ADD CONSTRAINT "vehicles_family_identity_key" UNIQUE (id, family_id);

ALTER TABLE public."vehicles" ADD CONSTRAINT "vehicles_pkey" PRIMARY KEY (id);

ALTER TABLE public."vehicles" ADD CONSTRAINT "vehicles_vehicle_ref_key" UNIQUE (vehicle_ref);

ALTER TABLE public."car_events" ADD CONSTRAINT "car_events_family_id_fkey" FOREIGN KEY (family_id) REFERENCES families(id);

ALTER TABLE public."car_events" ADD CONSTRAINT "car_events_user_id_fkey" FOREIGN KEY (user_id) REFERENCES users(id);

ALTER TABLE public."carplay_transition_admissions" ADD CONSTRAINT "carplay_transition_admissions_family_id_fkey" FOREIGN KEY (family_id) REFERENCES families(id) ON DELETE CASCADE;

ALTER TABLE public."carplay_transition_admissions" ADD CONSTRAINT "carplay_transition_admissions_user_id_fkey" FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

ALTER TABLE public."carplay_vehicle_bindings" ADD CONSTRAINT "carplay_binding_user_family_fk" FOREIGN KEY (user_id, family_id) REFERENCES users(id, family_id) ON DELETE CASCADE;

ALTER TABLE public."carplay_vehicle_bindings" ADD CONSTRAINT "carplay_binding_vehicle_family_fk" FOREIGN KEY (vehicle_id, family_id) REFERENCES vehicles(id, family_id) ON DELETE CASCADE;

ALTER TABLE public."chat_requests" ADD CONSTRAINT "chat_requests_family_id_fkey" FOREIGN KEY (family_id) REFERENCES families(id) ON DELETE RESTRICT;

ALTER TABLE public."chat_requests" ADD CONSTRAINT "chat_requests_user_id_fkey" FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT;

ALTER TABLE public."chat_tool_actions" ADD CONSTRAINT "chat_tool_actions_request_id_fkey" FOREIGN KEY (chat_request_id) REFERENCES chat_requests(id) ON DELETE RESTRICT;

ALTER TABLE public."conversation_messages" ADD CONSTRAINT "conversation_messages_chat_request_id_fkey" FOREIGN KEY (chat_request_id) REFERENCES chat_requests(id) ON DELETE RESTRICT;

ALTER TABLE public."conversation_messages" ADD CONSTRAINT "conversation_messages_user_id_fkey" FOREIGN KEY (user_id) REFERENCES users(id);

ALTER TABLE public."families" ADD CONSTRAINT "families_created_by_user_id_fkey" FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT;

ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_auth_user_id_fkey" FOREIGN KEY (auth_user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_family_id_fkey" FOREIGN KEY (family_id) REFERENCES families(id) ON DELETE CASCADE;

ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_user_id_fkey" FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

ALTER TABLE public."gemini_call_permits" ADD CONSTRAINT "gemini_call_permits_capacity_pool_fkey" FOREIGN KEY (capacity_pool) REFERENCES gemini_capacity_policies(capacity_pool) ON DELETE RESTRICT;

ALTER TABLE public."gemini_call_permits" ADD CONSTRAINT "gemini_call_permits_chat_request_id_fkey" FOREIGN KEY (chat_request_id) REFERENCES chat_requests(id) ON DELETE RESTRICT;

ALTER TABLE public."geocoding_attempts" ADD CONSTRAINT "geocoding_attempts_auth_user_id_fkey" FOREIGN KEY (auth_user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

ALTER TABLE public."geocoding_attempts" ADD CONSTRAINT "geocoding_attempts_capacity_pool_fkey" FOREIGN KEY (capacity_pool) REFERENCES geocoding_capacity_policies(capacity_pool) ON DELETE RESTRICT;

ALTER TABLE public."push_subscriptions" ADD CONSTRAINT "push_subscriptions_user_id_fkey" FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

ALTER TABLE public."pwa_join_sessions" ADD CONSTRAINT "pwa_join_sessions_auth_user_id_fkey" FOREIGN KEY (auth_user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

ALTER TABLE public."pwa_join_sessions" ADD CONSTRAINT "pwa_join_sessions_family_id_fkey" FOREIGN KEY (family_id) REFERENCES families(id) ON DELETE SET NULL;

ALTER TABLE public."registered_device_vehicle_bindings" ADD CONSTRAINT "registered_device_vehicle_bindings_device_id_fkey" FOREIGN KEY (device_id) REFERENCES registered_devices(id) ON DELETE CASCADE;

ALTER TABLE public."registered_device_vehicle_bindings" ADD CONSTRAINT "registered_device_vehicle_bindings_vehicle_id_fkey" FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE;

ALTER TABLE public."registered_devices" ADD CONSTRAINT "registered_devices_user_id_fkey" FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

ALTER TABLE public."reservations" ADD CONSTRAINT "reservations_user_id_fkey" FOREIGN KEY (user_id) REFERENCES users(id);

ALTER TABLE public."reservations" ADD CONSTRAINT "reservations_vehicle_id_fkey" FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE RESTRICT;

ALTER TABLE public."users" ADD CONSTRAINT "users_auth_user_id_fkey" FOREIGN KEY (auth_user_id) REFERENCES auth.users(id) ON DELETE SET NULL;

ALTER TABLE public."users" ADD CONSTRAINT "users_family_id_fkey" FOREIGN KEY (family_id) REFERENCES families(id);

ALTER TABLE public."vehicle_driver_sessions" ADD CONSTRAINT "vehicle_sessions_end_event_fkey" FOREIGN KEY (end_event_id, family_id) REFERENCES vehicle_events(event_id, family_id) ON DELETE SET NULL (end_event_id);

ALTER TABLE public."vehicle_driver_sessions" ADD CONSTRAINT "vehicle_sessions_member_fkey" FOREIGN KEY (user_id, family_id) REFERENCES users(id, family_id) ON DELETE CASCADE;

ALTER TABLE public."vehicle_driver_sessions" ADD CONSTRAINT "vehicle_sessions_start_event_fkey" FOREIGN KEY (start_event_id, user_id, vehicle_id, family_id) REFERENCES vehicle_events(event_id, user_id, vehicle_id, family_id) ON DELETE SET NULL (start_event_id);

ALTER TABLE public."vehicle_driver_sessions" ADD CONSTRAINT "vehicle_sessions_vehicle_fkey" FOREIGN KEY (vehicle_id, family_id) REFERENCES vehicles(id, family_id) ON DELETE CASCADE;

ALTER TABLE public."vehicle_events" ADD CONSTRAINT "vehicle_events_device_fkey" FOREIGN KEY (device_id, user_id) REFERENCES registered_devices(id, user_id);

ALTER TABLE public."vehicle_events" ADD CONSTRAINT "vehicle_events_member_fkey" FOREIGN KEY (user_id, family_id) REFERENCES users(id, family_id) ON DELETE CASCADE;

ALTER TABLE public."vehicle_events" ADD CONSTRAINT "vehicle_events_projection_fkey" FOREIGN KEY (projection_take_event_id, user_id, vehicle_id, family_id) REFERENCES vehicle_events(event_id, user_id, vehicle_id, family_id) DEFERRABLE;

ALTER TABLE public."vehicle_events" ADD CONSTRAINT "vehicle_events_vehicle_fkey" FOREIGN KEY (vehicle_id, family_id) REFERENCES vehicles(id, family_id) ON DELETE CASCADE;

ALTER TABLE public."vehicles" ADD CONSTRAINT "vehicles_created_by_user_id_fkey" FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE public."vehicles" ADD CONSTRAINT "vehicles_family_id_fkey" FOREIGN KEY (family_id) REFERENCES families(id) ON DELETE CASCADE;

CREATE INDEX account_deletion_jobs_next_attempt_idx ON public.account_deletion_jobs USING btree (next_attempt_at, auth_user_id);

-- Constraint-backed index: CREATE UNIQUE INDEX account_deletion_jobs_pkey ON public.account_deletion_jobs USING btree (auth_user_id);

-- Constraint-backed index: CREATE UNIQUE INDEX car_events_pkey ON public.car_events USING btree (id);

CREATE INDEX carplay_bindings_vehicle_idx ON public.carplay_vehicle_bindings USING btree (vehicle_id, family_id);

CREATE INDEX carplay_transition_admissions_admitted_idx ON public.carplay_transition_admissions USING btree (admitted_at);

CREATE INDEX carplay_transition_admissions_family_admitted_idx ON public.carplay_transition_admissions USING btree (family_id, admitted_at);

-- Constraint-backed index: CREATE UNIQUE INDEX carplay_transition_admissions_pkey ON public.carplay_transition_admissions USING btree (admission_id);

CREATE INDEX carplay_transition_admissions_user_admitted_idx ON public.carplay_transition_admissions USING btree (user_id, admitted_at);

-- Constraint-backed index: CREATE UNIQUE INDEX carplay_vehicle_bindings_pkey ON public.carplay_vehicle_bindings USING btree (user_id);

CREATE INDEX chat_requests_expired_processing_idx ON public.chat_requests USING btree (lease_expires_at) WHERE (status = 'processing'::text);

-- Constraint-backed index: CREATE UNIQUE INDEX chat_requests_pkey ON public.chat_requests USING btree (id);

CREATE INDEX chat_requests_user_family_created_idx ON public.chat_requests USING btree (user_id, family_id, created_at DESC);

-- Constraint-backed index: CREATE UNIQUE INDEX chat_requests_user_request_unique ON public.chat_requests USING btree (user_id, request_id);

-- Constraint-backed index: CREATE UNIQUE INDEX chat_tool_actions_pkey ON public.chat_tool_actions USING btree (id);

-- Constraint-backed index: CREATE UNIQUE INDEX chat_tool_actions_request_unique ON public.chat_tool_actions USING btree (chat_request_id);

-- Constraint-backed index: CREATE UNIQUE INDEX conversation_messages_pkey ON public.conversation_messages USING btree (id);

CREATE UNIQUE INDEX conversation_messages_request_assistant_unique ON public.conversation_messages USING btree (chat_request_id) WHERE ((chat_request_id IS NOT NULL) AND (role = 'assistant'::text));

CREATE UNIQUE INDEX conversation_messages_request_user_unique ON public.conversation_messages USING btree (chat_request_id) WHERE ((chat_request_id IS NOT NULL) AND (role = 'user'::text));

CREATE INDEX conversation_messages_user_request_history_idx ON public.conversation_messages USING btree (user_id, id DESC) WHERE (chat_request_id IS NOT NULL);

-- Constraint-backed index: CREATE UNIQUE INDEX devices_creation_request_key ON public.registered_devices USING btree (user_id, creation_request_id);

-- Constraint-backed index: CREATE UNIQUE INDEX families_family_code_key ON public.families USING btree (family_code);

-- Constraint-backed index: CREATE UNIQUE INDEX families_pkey ON public.families USING btree (id);

CREATE INDEX family_address_confirmations_auth_idx ON public.family_address_confirmations USING btree (auth_user_id);

CREATE UNIQUE INDEX family_address_confirmations_create_identity_idx ON public.family_address_confirmations USING btree (auth_user_id) WHERE (purpose = 'create_family'::text);

CREATE INDEX family_address_confirmations_expiry_idx ON public.family_address_confirmations USING btree (expires_at);

CREATE INDEX family_address_confirmations_family_idx ON public.family_address_confirmations USING btree (family_id) WHERE (family_id IS NOT NULL);

-- Constraint-backed index: CREATE UNIQUE INDEX family_address_confirmations_pkey ON public.family_address_confirmations USING btree (token_digest);

CREATE UNIQUE INDEX family_address_confirmations_update_identity_idx ON public.family_address_confirmations USING btree (user_id) WHERE (purpose = 'family_address_update'::text);

-- Constraint-backed index: CREATE UNIQUE INDEX family_code_history_pkey ON public.family_code_history USING btree (code);

-- Constraint-backed index: CREATE UNIQUE INDEX gemini_call_permits_chat_request_id_key ON public.gemini_call_permits USING btree (chat_request_id);

-- Constraint-backed index: CREATE UNIQUE INDEX gemini_call_permits_pkey ON public.gemini_call_permits USING btree (permit_id);

CREATE INDEX gemini_call_permits_pool_expiry_idx ON public.gemini_call_permits USING btree (capacity_pool, expires_at);

-- Constraint-backed index: CREATE UNIQUE INDEX gemini_capacity_policies_pkey ON public.gemini_capacity_policies USING btree (capacity_pool);

CREATE INDEX geocoding_attempts_active_expiry_idx ON public.geocoding_attempts USING btree (permit_expires_at) WHERE (permit_expires_at IS NOT NULL);

-- Constraint-backed index: CREATE UNIQUE INDEX geocoding_attempts_pkey ON public.geocoding_attempts USING btree (attempt_id);

CREATE INDEX geocoding_attempts_user_admitted_idx ON public.geocoding_attempts USING btree (auth_user_id, admitted_at);

-- Constraint-backed index: CREATE UNIQUE INDEX geocoding_capacity_policies_pkey ON public.geocoding_capacity_policies USING btree (capacity_pool);

-- Constraint-backed index: CREATE UNIQUE INDEX push_subscriptions_endpoint_key ON public.push_subscriptions USING btree (endpoint);

-- Constraint-backed index: CREATE UNIQUE INDEX push_subscriptions_pkey ON public.push_subscriptions USING btree (id);

CREATE INDEX push_subscriptions_user_id_idx ON public.push_subscriptions USING btree (user_id);

CREATE INDEX pwa_join_sessions_locked_until_idx ON public.pwa_join_sessions USING btree (locked_until) WHERE (locked_until IS NOT NULL);

-- Constraint-backed index: CREATE UNIQUE INDEX pwa_join_sessions_pkey ON public.pwa_join_sessions USING btree (auth_user_id);

-- Constraint-backed index: CREATE UNIQUE INDEX registered_device_vehicle_bindings_pkey ON public.registered_device_vehicle_bindings USING btree (device_id, vehicle_id);

CREATE INDEX registered_device_vehicle_bindings_vehicle_idx ON public.registered_device_vehicle_bindings USING btree (vehicle_id);

-- Constraint-backed index: CREATE UNIQUE INDEX registered_devices_device_ref_key ON public.registered_devices USING btree (device_ref);

-- Constraint-backed index: CREATE UNIQUE INDEX registered_devices_owner_key ON public.registered_devices USING btree (id, user_id);

-- Constraint-backed index: CREATE UNIQUE INDEX registered_devices_pkey ON public.registered_devices USING btree (id);

CREATE INDEX registered_devices_user_idx ON public.registered_devices USING btree (user_id, id);

-- Constraint-backed index: CREATE UNIQUE INDEX reservations_pkey ON public.reservations USING btree (id);

-- Constraint-backed index: CREATE UNIQUE INDEX reservations_reservation_ref_key ON public.reservations USING btree (reservation_ref);

CREATE INDEX reservations_vehicle_time_idx ON public.reservations USING btree (vehicle_id, start_time, end_time) WHERE (status = 'active'::text);

-- Constraint-backed index: CREATE UNIQUE INDEX users_auth_user_id_unique ON public.users USING btree (auth_user_id);

-- Constraint-backed index: CREATE UNIQUE INDEX users_member_public_id_key ON public.users USING btree (member_public_id);

-- Constraint-backed index: CREATE UNIQUE INDEX users_pkey ON public.users USING btree (id);

-- Constraint-backed index: CREATE UNIQUE INDEX users_shortcut_token_key ON public.users USING btree (shortcut_token);

-- Constraint-backed index: CREATE UNIQUE INDEX users_telegram_chat_id_key ON public.users USING btree (telegram_chat_id);

-- Constraint-backed index: CREATE UNIQUE INDEX users_vehicle_membership_key ON public.users USING btree (id, family_id);

-- Constraint-backed index: CREATE UNIQUE INDEX vehicle_driver_sessions_pkey ON public.vehicle_driver_sessions USING btree (id);

-- Constraint-backed index: CREATE UNIQUE INDEX vehicle_driver_sessions_session_ref_key ON public.vehicle_driver_sessions USING btree (session_ref);

-- Constraint-backed index: CREATE UNIQUE INDEX vehicle_driver_sessions_start_event_id_key ON public.vehicle_driver_sessions USING btree (start_event_id);

-- Constraint-backed index: CREATE UNIQUE INDEX vehicle_events_anchor_identity_key ON public.vehicle_events USING btree (event_id, user_id, vehicle_id, family_id);

-- Constraint-backed index: CREATE UNIQUE INDEX vehicle_events_anchor_identity_key ON public.vehicle_events USING btree (event_id, user_id, vehicle_id, family_id);

CREATE INDEX vehicle_events_device_accepted_sequence_idx ON public.vehicle_events USING btree (device_id, device_sequence) WHERE (admission_outcome = 'accepted'::text);

-- Constraint-backed index: CREATE UNIQUE INDEX vehicle_events_device_sequence_key ON public.vehicle_events USING btree (device_id, device_sequence);

-- Constraint-backed index: CREATE UNIQUE INDEX vehicle_events_event_id_key ON public.vehicle_events USING btree (event_id);

CREATE INDEX vehicle_events_family_chronology_idx ON public.vehicle_events USING btree (family_id, occurred_at, event_id) WHERE (admission_outcome = 'accepted'::text);

-- Constraint-backed index: CREATE UNIQUE INDEX vehicle_events_family_identity_key ON public.vehicle_events USING btree (event_id, family_id);

-- Constraint-backed index: CREATE UNIQUE INDEX vehicle_events_pkey ON public.vehicle_events USING btree (id);

CREATE INDEX vehicle_events_projection_idx ON public.vehicle_events USING btree (projection_take_event_id) WHERE (projection_take_event_id IS NOT NULL);

CREATE INDEX vehicle_events_user_chronology_idx ON public.vehicle_events USING btree (user_id, occurred_at, event_id);

CREATE INDEX vehicle_events_vehicle_chronology_idx ON public.vehicle_events USING btree (vehicle_id, occurred_at, event_id);

CREATE UNIQUE INDEX vehicle_sessions_active_user_idx ON public.vehicle_driver_sessions USING btree (user_id) WHERE (ended_at IS NULL);

CREATE UNIQUE INDEX vehicle_sessions_active_vehicle_idx ON public.vehicle_driver_sessions USING btree (vehicle_id) WHERE (ended_at IS NULL);

CREATE INDEX vehicle_sessions_checkpoint_idx ON public.vehicle_driver_sessions USING btree (family_id, checkpoint_generation) WHERE (checkpoint_generation IS NOT NULL);

CREATE INDEX vehicle_sessions_end_event_idx ON public.vehicle_driver_sessions USING btree (end_event_id) WHERE (end_event_id IS NOT NULL);

CREATE INDEX vehicle_sessions_family_active_idx ON public.vehicle_driver_sessions USING btree (family_id, started_at, id) WHERE (ended_at IS NULL);

CREATE INDEX vehicle_sessions_family_time_idx ON public.vehicle_driver_sessions USING btree (family_id, started_at, id);

CREATE INDEX vehicle_sessions_user_idx ON public.vehicle_driver_sessions USING btree (user_id);

-- Constraint-backed index: CREATE INDEX vehicle_sessions_user_no_overlap ON public.vehicle_driver_sessions USING gist (int8range((user_id)::bigint, (user_id)::bigint, '[]'::text), tstzrange(started_at, ended_at, '[)'::text));

CREATE INDEX vehicle_sessions_vehicle_idx ON public.vehicle_driver_sessions USING btree (vehicle_id);

-- Constraint-backed index: CREATE INDEX vehicle_sessions_vehicle_no_overlap ON public.vehicle_driver_sessions USING gist (int8range((vehicle_id)::bigint, (vehicle_id)::bigint, '[]'::text), tstzrange(started_at, ended_at, '[)'::text));

-- Constraint-backed index: CREATE UNIQUE INDEX vehicles_creation_request_key ON public.vehicles USING btree (family_id, creation_request_id);

CREATE INDEX vehicles_creator_idx ON public.vehicles USING btree (created_by_user_id) WHERE (created_by_user_id IS NOT NULL);

CREATE INDEX vehicles_family_active_idx ON public.vehicles USING btree (family_id, id) WHERE (retired_at IS NULL);

-- Constraint-backed index: CREATE UNIQUE INDEX vehicles_family_identity_key ON public.vehicles USING btree (id, family_id);

CREATE INDEX vehicles_family_idx ON public.vehicles USING btree (family_id);

-- Constraint-backed index: CREATE UNIQUE INDEX vehicles_pkey ON public.vehicles USING btree (id);

-- Constraint-backed index: CREATE UNIQUE INDEX vehicles_vehicle_ref_key ON public.vehicles USING btree (vehicle_ref);

-- Phase 3: exact captured functions, triggers and FCA receive policy.

CREATE FUNCTION public.broadcast_car_status_changed()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
BEGIN
  PERFORM realtime.send(
    '{}'::jsonb,
    'car_status_changed',
    'family:' || NEW.family_id::text || ':car-status',
    true
  );

  RETURN NEW;
END;
$function$;

ALTER FUNCTION public.broadcast_car_status_changed() OWNER TO postgres;

CREATE FUNCTION public.broadcast_vehicle_member_deleted()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
BEGIN
    IF OLD.family_id IS NOT NULL AND EXISTS (
        SELECT FROM public.families WHERE id=OLD.family_id
    ) THEN
        PERFORM realtime.send('{}'::jsonb, 'car_status_changed',
            'family:' || OLD.family_id::text || ':car-status', true);
    END IF;
    RETURN OLD;
END;
$function$;

ALTER FUNCTION public.broadcast_vehicle_member_deleted() OWNER TO postgres;

CREATE FUNCTION public.can_receive_car_status_topic(requested_topic text)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
  SELECT EXISTS (
    SELECT 1
    FROM public.users AS u
    WHERE u.auth_user_id = (SELECT auth.uid())
      AND u.family_id IS NOT NULL
      AND requested_topic =
          'family:' || u.family_id::text || ':car-status'
  );
$function$;

ALTER FUNCTION public.can_receive_car_status_topic(requested_topic text) OWNER TO postgres;

CREATE FUNCTION public.guard_vehicle_checkpoint()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
BEGIN
    IF NEW.vehicle_reconciliation_generation < OLD.vehicle_reconciliation_generation
       OR (OLD.vehicle_finalized_through IS NOT NULL AND
           (NEW.vehicle_finalized_through IS NULL
            OR NEW.vehicle_finalized_through < OLD.vehicle_finalized_through))
       OR (NEW.vehicle_finalized_through IS DISTINCT FROM OLD.vehicle_finalized_through
           AND NEW.vehicle_reconciliation_generation <= OLD.vehicle_reconciliation_generation) THEN
        RAISE EXCEPTION 'Vehicle checkpoint cannot move backwards or change without a new generation';
    END IF;
    RETURN NEW;
END;
$function$;

ALTER FUNCTION public.guard_vehicle_checkpoint() OWNER TO postgres;

CREATE FUNCTION public.guard_vehicle_event_evidence()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
BEGIN
    IF ROW(NEW.id, NEW.event_id, NEW.family_id, NEW.vehicle_id, NEW.user_id,
           NEW.device_id, NEW.source, NEW.event_type, NEW.device_sequence,
           NEW.occurred_at, NEW.received_at, NEW.admission_outcome, NEW.take_event_id)
       IS DISTINCT FROM
       ROW(OLD.id, OLD.event_id, OLD.family_id, OLD.vehicle_id, OLD.user_id,
           OLD.device_id, OLD.source, OLD.event_type, OLD.device_sequence,
           OLD.occurred_at, OLD.received_at, OLD.admission_outcome, OLD.take_event_id) THEN
        RAISE EXCEPTION 'Vehicle event evidence and admission outcome are immutable';
    END IF;
    RETURN NEW;
END;
$function$;

ALTER FUNCTION public.guard_vehicle_event_evidence() OWNER TO postgres;

CREATE TRIGGER families_vehicle_checkpoint_guard BEFORE UPDATE OF vehicle_reconciliation_generation, vehicle_finalized_through ON public.families FOR EACH ROW EXECUTE FUNCTION guard_vehicle_checkpoint();

ALTER TABLE public."families" ENABLE TRIGGER "families_vehicle_checkpoint_guard";

CREATE TRIGGER users_broadcast_vehicle_member_deleted AFTER DELETE ON public.users FOR EACH ROW EXECUTE FUNCTION broadcast_vehicle_member_deleted();

ALTER TABLE public."users" ENABLE TRIGGER "users_broadcast_vehicle_member_deleted";

CREATE TRIGGER vehicle_events_broadcast_car_status AFTER INSERT ON public.vehicle_events FOR EACH ROW WHEN ((new.admission_outcome = 'accepted'::text)) EXECUTE FUNCTION broadcast_car_status_changed();

ALTER TABLE public."vehicle_events" ENABLE TRIGGER "vehicle_events_broadcast_car_status";

CREATE TRIGGER vehicle_events_evidence_guard BEFORE UPDATE ON public.vehicle_events FOR EACH ROW EXECUTE FUNCTION guard_vehicle_event_evidence();

ALTER TABLE public."vehicle_events" ENABLE TRIGGER "vehicle_events_evidence_guard";

CREATE POLICY "family_members_receive_car_status" ON realtime.messages AS PERMISSIVE FOR SELECT TO authenticated USING (((extension = 'broadcast'::text) AND can_receive_car_status_topic(( SELECT realtime.topic() AS topic))));

-- Phase 4: captured RLS and explicit ACLs, independent of provider defaults.

ALTER TABLE public."account_deletion_jobs" ENABLE ROW LEVEL SECURITY;

ALTER TABLE public."account_deletion_jobs" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."car_events" DISABLE ROW LEVEL SECURITY;

ALTER TABLE public."car_events" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."carplay_transition_admissions" ENABLE ROW LEVEL SECURITY;

ALTER TABLE public."carplay_transition_admissions" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."carplay_vehicle_bindings" ENABLE ROW LEVEL SECURITY;

ALTER TABLE public."carplay_vehicle_bindings" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."chat_requests" DISABLE ROW LEVEL SECURITY;

ALTER TABLE public."chat_requests" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."chat_tool_actions" DISABLE ROW LEVEL SECURITY;

ALTER TABLE public."chat_tool_actions" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."conversation_messages" DISABLE ROW LEVEL SECURITY;

ALTER TABLE public."conversation_messages" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."families" DISABLE ROW LEVEL SECURITY;

ALTER TABLE public."families" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."family_address_confirmations" ENABLE ROW LEVEL SECURITY;

ALTER TABLE public."family_address_confirmations" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."family_code_history" ENABLE ROW LEVEL SECURITY;

ALTER TABLE public."family_code_history" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."gemini_call_permits" DISABLE ROW LEVEL SECURITY;

ALTER TABLE public."gemini_call_permits" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."gemini_capacity_policies" DISABLE ROW LEVEL SECURITY;

ALTER TABLE public."gemini_capacity_policies" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."geocoding_attempts" ENABLE ROW LEVEL SECURITY;

ALTER TABLE public."geocoding_attempts" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."geocoding_capacity_policies" ENABLE ROW LEVEL SECURITY;

ALTER TABLE public."geocoding_capacity_policies" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."push_subscriptions" DISABLE ROW LEVEL SECURITY;

ALTER TABLE public."push_subscriptions" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."pwa_join_sessions" ENABLE ROW LEVEL SECURITY;

ALTER TABLE public."pwa_join_sessions" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."registered_device_vehicle_bindings" ENABLE ROW LEVEL SECURITY;

ALTER TABLE public."registered_device_vehicle_bindings" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."registered_devices" ENABLE ROW LEVEL SECURITY;

ALTER TABLE public."registered_devices" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."reservations" DISABLE ROW LEVEL SECURITY;

ALTER TABLE public."reservations" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."users" DISABLE ROW LEVEL SECURITY;

ALTER TABLE public."users" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."vehicle_driver_sessions" ENABLE ROW LEVEL SECURITY;

ALTER TABLE public."vehicle_driver_sessions" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."vehicle_events" ENABLE ROW LEVEL SECURITY;

ALTER TABLE public."vehicle_events" NO FORCE ROW LEVEL SECURITY;

ALTER TABLE public."vehicles" ENABLE ROW LEVEL SECURITY;

ALTER TABLE public."vehicles" NO FORCE ROW LEVEL SECURITY;

REVOKE ALL PRIVILEGES ON TABLE public."account_deletion_jobs" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("auth_user_id", "phase", "created_at", "next_attempt_at") ON TABLE public."account_deletion_jobs" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."account_deletion_jobs" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."car_events" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("id", "driver_name", "status", "event_time", "family_id", "user_id") ON TABLE public."car_events" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."car_events" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON SEQUENCE public."car_events_id_seq" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, UPDATE, USAGE ON SEQUENCE public."car_events_id_seq" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."carplay_transition_admissions" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("admission_id", "user_id", "family_id", "admitted_at") ON TABLE public."carplay_transition_admissions" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."carplay_transition_admissions" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."carplay_vehicle_bindings" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("user_id", "family_id", "vehicle_id") ON TABLE public."carplay_vehicle_bindings" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."carplay_vehicle_bindings" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."chat_requests" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("id", "request_id", "user_id", "family_id", "status", "original_message", "final_response", "error_http_status", "error_payload", "lease_token", "lease_expires_at", "created_at", "updated_at", "completed_at", "processing_attempts") ON TABLE public."chat_requests" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."chat_requests" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON SEQUENCE public."chat_requests_id_seq" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, UPDATE, USAGE ON SEQUENCE public."chat_requests_id_seq" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."chat_tool_actions" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("id", "chat_request_id", "action_type", "arguments", "status", "result", "error_payload", "lease_token_at_execution", "created_at", "completed_at") ON TABLE public."chat_tool_actions" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."chat_tool_actions" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON SEQUENCE public."chat_tool_actions_id_seq" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, UPDATE, USAGE ON SEQUENCE public."chat_tool_actions_id_seq" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."conversation_messages" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("id", "user_id", "role", "content", "created_at", "chat_request_id") ON TABLE public."conversation_messages" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."conversation_messages" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON SEQUENCE public."conversation_messages_id_seq" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, UPDATE, USAGE ON SEQUENCE public."conversation_messages_id_seq" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."families" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("id", "name", "family_code", "home_address", "home_latitude", "home_longitude", "created_at", "created_by_user_id", "vehicle_reconciliation_generation", "vehicle_finalized_through", "device_identities_created") ON TABLE public."families" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."families" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON SEQUENCE public."families_id_seq" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, UPDATE, USAGE ON SEQUENCE public."families_id_seq" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."family_address_confirmations" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("token_digest", "purpose", "auth_user_id", "user_id", "family_id", "normalized_address", "display_address", "latitude", "longitude", "expires_at") ON TABLE public."family_address_confirmations" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."family_address_confirmations" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."family_code_history" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("code") ON TABLE public."family_code_history" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."family_code_history" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."gemini_call_permits" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("permit_id", "chat_request_id", "attempt_token", "capacity_pool", "acquired_at", "expires_at") ON TABLE public."gemini_call_permits" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."gemini_call_permits" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."gemini_capacity_policies" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("capacity_pool", "max_concurrency", "updated_at") ON TABLE public."gemini_capacity_policies" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."gemini_capacity_policies" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."geocoding_attempts" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("attempt_id", "auth_user_id", "capacity_pool", "admitted_at", "permit_expires_at") ON TABLE public."geocoding_attempts" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."geocoding_attempts" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."geocoding_capacity_policies" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("capacity_pool", "max_concurrency", "updated_at") ON TABLE public."geocoding_capacity_policies" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."geocoding_capacity_policies" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."push_subscriptions" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("id", "user_id", "endpoint", "p256dh", "auth", "expiration_time", "created_at", "updated_at") ON TABLE public."push_subscriptions" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."push_subscriptions" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON SEQUENCE public."push_subscriptions_id_seq" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, UPDATE, USAGE ON SEQUENCE public."push_subscriptions_id_seq" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."pwa_join_sessions" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("auth_user_id", "step", "family_name", "family_id", "normalized_address", "resolved_address", "family_name_attempts", "address_attempts", "family_code_attempts", "locked_until", "created_at", "updated_at") ON TABLE public."pwa_join_sessions" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."pwa_join_sessions" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."registered_device_vehicle_bindings" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("device_id", "vehicle_id") ON TABLE public."registered_device_vehicle_bindings" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."registered_device_vehicle_bindings" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."registered_devices" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("id", "device_ref", "user_id", "platform", "created_at", "last_seen_at", "revoked_at", "last_processed_sequence", "creation_request_id", "creation_fingerprint") ON TABLE public."registered_devices" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."registered_devices" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON SEQUENCE public."registered_devices_id_seq" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, UPDATE, USAGE ON SEQUENCE public."registered_devices_id_seq" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."reservations" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("id", "user_id", "start_time", "end_time", "status", "created_at", "reservation_ref", "vehicle_id") ON TABLE public."reservations" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."reservations" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON SEQUENCE public."reservations_id_seq" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, UPDATE, USAGE ON SEQUENCE public."reservations_id_seq" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."users" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("id", "name", "shortcut_token", "telegram_chat_id", "family_id", "auth_user_id", "carplay_setup_status", "family_role", "member_public_id") ON TABLE public."users" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."users" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON SEQUENCE public."users_id_seq" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, UPDATE, USAGE ON SEQUENCE public."users_id_seq" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."vehicle_driver_sessions" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("id", "session_ref", "family_id", "vehicle_id", "user_id", "started_at", "ended_at", "start_event_id", "end_event_id", "end_reason", "created_at", "checkpoint_generation") ON TABLE public."vehicle_driver_sessions" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."vehicle_driver_sessions" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON SEQUENCE public."vehicle_driver_sessions_id_seq" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, UPDATE, USAGE ON SEQUENCE public."vehicle_driver_sessions_id_seq" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."vehicle_events" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("id", "event_id", "family_id", "vehicle_id", "user_id", "device_id", "source", "event_type", "device_sequence", "occurred_at", "received_at", "admission_outcome", "take_event_id", "projection_take_event_id") ON TABLE public."vehicle_events" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."vehicle_events" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON SEQUENCE public."vehicle_events_id_seq" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, UPDATE, USAGE ON SEQUENCE public."vehicle_events_id_seq" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON TABLE public."vehicles" FROM PUBLIC, anon, authenticated, postgres, service_role;

REVOKE ALL PRIVILEGES ("id", "vehicle_ref", "family_id", "display_name", "created_by_user_id", "created_at", "retired_at", "creation_request_id", "creation_fingerprint") ON TABLE public."vehicles" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE public."vehicles" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON SEQUENCE public."vehicles_id_seq" FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT SELECT, UPDATE, USAGE ON SEQUENCE public."vehicles_id_seq" TO postgres, service_role;

REVOKE ALL PRIVILEGES ON FUNCTION public.broadcast_car_status_changed() FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT EXECUTE ON FUNCTION public.broadcast_car_status_changed() TO postgres, service_role;

REVOKE ALL PRIVILEGES ON FUNCTION public.broadcast_vehicle_member_deleted() FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT EXECUTE ON FUNCTION public.broadcast_vehicle_member_deleted() TO postgres, service_role;

REVOKE ALL PRIVILEGES ON FUNCTION public.can_receive_car_status_topic(text) FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT EXECUTE ON FUNCTION public.can_receive_car_status_topic(text) TO postgres, service_role, anon, authenticated;

REVOKE ALL PRIVILEGES ON FUNCTION public.guard_vehicle_checkpoint() FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT EXECUTE ON FUNCTION public.guard_vehicle_checkpoint() TO postgres, service_role;

REVOKE ALL PRIVILEGES ON FUNCTION public.guard_vehicle_event_evidence() FROM PUBLIC, anon, authenticated, postgres, service_role;

GRANT EXECUTE ON FUNCTION public.guard_vehicle_event_evidence() TO postgres, service_role;

-- Fail transactionally if unexpected default grantees survived; ACL order is immaterial.

DO $acl_postcondition$
DECLARE actual aclitem[]; expected aclitem[];
BEGIN

    actual := (SELECT relacl FROM pg_class WHERE oid='public."account_deletion_jobs"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."car_events"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."car_events_id_seq"'::regclass); expected := '{postgres=rwU/postgres,service_role=rwU/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."carplay_transition_admissions"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."carplay_vehicle_bindings"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."chat_requests"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."chat_requests_id_seq"'::regclass); expected := '{postgres=rwU/postgres,service_role=rwU/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."chat_tool_actions"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."chat_tool_actions_id_seq"'::regclass); expected := '{postgres=rwU/postgres,service_role=rwU/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."conversation_messages"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."conversation_messages_id_seq"'::regclass); expected := '{postgres=rwU/postgres,service_role=rwU/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."families"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."families_id_seq"'::regclass); expected := '{postgres=rwU/postgres,service_role=rwU/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."family_address_confirmations"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."family_code_history"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."gemini_call_permits"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."gemini_capacity_policies"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."geocoding_attempts"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."geocoding_capacity_policies"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."push_subscriptions"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."push_subscriptions_id_seq"'::regclass); expected := '{postgres=rwU/postgres,service_role=rwU/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."pwa_join_sessions"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."registered_device_vehicle_bindings"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."registered_devices"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."registered_devices_id_seq"'::regclass); expected := '{postgres=rwU/postgres,service_role=rwU/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."reservations"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."reservations_id_seq"'::regclass); expected := '{postgres=rwU/postgres,service_role=rwU/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."users"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."users_id_seq"'::regclass); expected := '{postgres=rwU/postgres,service_role=rwU/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."vehicle_driver_sessions"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."vehicle_driver_sessions_id_seq"'::regclass); expected := '{postgres=rwU/postgres,service_role=rwU/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."vehicle_events"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."vehicle_events_id_seq"'::regclass); expected := '{postgres=rwU/postgres,service_role=rwU/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."vehicles"'::regclass); expected := '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT relacl FROM pg_class WHERE oid='public."vehicles_id_seq"'::regclass); expected := '{postgres=rwU/postgres,service_role=rwU/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT proacl FROM pg_proc WHERE oid='public.broadcast_car_status_changed()'::regprocedure); expected := '{postgres=X/postgres,service_role=X/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT proacl FROM pg_proc WHERE oid='public.broadcast_vehicle_member_deleted()'::regprocedure); expected := '{postgres=X/postgres,service_role=X/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT proacl FROM pg_proc WHERE oid='public.can_receive_car_status_topic(text)'::regprocedure); expected := '{postgres=X/postgres,anon=X/postgres,authenticated=X/postgres,service_role=X/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT proacl FROM pg_proc WHERE oid='public.guard_vehicle_checkpoint()'::regprocedure); expected := '{postgres=X/postgres,service_role=X/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

    actual := (SELECT proacl FROM pg_proc WHERE oid='public.guard_vehicle_event_evidence()'::regprocedure); expected := '{postgres=X/postgres,service_role=X/postgres}'::aclitem[];
    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN
        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';
    END IF;

END
$acl_postcondition$;

-- Phase 5: only environment configuration; no Production application data.

INSERT INTO public.gemini_capacity_policies (capacity_pool, max_concurrency) VALUES ('gemini-default', 50);

INSERT INTO public.geocoding_capacity_policies (capacity_pool, max_concurrency) VALUES ('google-geocoding', 20);

COMMIT;
