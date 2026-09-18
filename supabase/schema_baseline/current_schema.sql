-- CURRENT PRODUCTION SCHEMA REFERENCE / EMPTY-DATABASE BOOTSTRAP ONLY.
-- DO NOT APPLY TO THE EXISTING FCA PRODUCTION DATABASE.
-- Source: operator-supplied supabase/schema_audit captures. Read README.md first.
-- No application data or sequence current values are included.
BEGIN;
SET LOCAL search_path = public, pg_catalog;

DO $baseline_guard$
DECLARE object_name text;
BEGIN
    IF current_setting('fca.allow_empty_baseline', true) IS DISTINCT FROM 'yes' THEN
        RAISE EXCEPTION 'Baseline disabled: only an explicitly approved empty disposable/bootstrap database may opt in';
    END IF;
    IF current_user <> 'postgres' THEN
        RAISE EXCEPTION 'Baseline requires postgres ownership';
    END IF;
    FOREACH object_name IN ARRAY ARRAY['account_deletion_jobs', 'car_events', 'carplay_transition_admissions', 'chat_requests', 'chat_tool_actions', 'conversation_messages', 'families', 'family_address_confirmations', 'family_code_history', 'gemini_call_permits', 'gemini_capacity_policies', 'geocoding_attempts', 'geocoding_capacity_policies', 'push_subscriptions', 'pwa_join_sessions', 'reservations', 'users']
    LOOP
        IF to_regclass('public.' || object_name) IS NOT NULL THEN
            RAISE EXCEPTION 'Baseline requires absent FCA objects: %', object_name;
        END IF;
    END LOOP;
    IF to_regprocedure('public.broadcast_car_status_changed()') IS NOT NULL
       OR to_regprocedure('public.can_receive_car_status_topic(text)') IS NOT NULL THEN
        RAISE EXCEPTION 'Existing FCA functions: baseline cannot replace them';
    END IF;
    IF to_regclass('auth.users') IS NULL OR to_regclass('realtime.messages') IS NULL THEN
        RAISE EXCEPTION 'Supabase Auth/Realtime prerequisites must already exist';
    END IF;
END
$baseline_guard$;

-- Seven legacy owned sequences; the eighth is created by IDENTITY below.
CREATE SEQUENCE public."car_events_id_seq" AS integer START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 CACHE 1 NO CYCLE;
ALTER SEQUENCE public."car_events_id_seq" OWNER TO postgres;
CREATE SEQUENCE public."chat_requests_id_seq" AS bigint START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 CACHE 1 NO CYCLE;
ALTER SEQUENCE public."chat_requests_id_seq" OWNER TO postgres;
CREATE SEQUENCE public."chat_tool_actions_id_seq" AS bigint START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 CACHE 1 NO CYCLE;
ALTER SEQUENCE public."chat_tool_actions_id_seq" OWNER TO postgres;
CREATE SEQUENCE public."conversation_messages_id_seq" AS integer START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 CACHE 1 NO CYCLE;
ALTER SEQUENCE public."conversation_messages_id_seq" OWNER TO postgres;
CREATE SEQUENCE public."families_id_seq" AS integer START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 CACHE 1 NO CYCLE;
ALTER SEQUENCE public."families_id_seq" OWNER TO postgres;
CREATE SEQUENCE public."reservations_id_seq" AS integer START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 CACHE 1 NO CYCLE;
ALTER SEQUENCE public."reservations_id_seq" OWNER TO postgres;
CREATE SEQUENCE public."users_id_seq" AS integer START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 CACHE 1 NO CYCLE;
ALTER SEQUENCE public."users_id_seq" OWNER TO postgres;

CREATE TABLE public."account_deletion_jobs" (
    "auth_user_id" uuid NOT NULL,
    "phase" text DEFAULT 'draining'::text NOT NULL,
    "created_at" timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    "next_attempt_at" timestamp with time zone DEFAULT clock_timestamp() NOT NULL
);
ALTER TABLE public."account_deletion_jobs" OWNER TO postgres;

CREATE TABLE public."car_events" (
    "id" integer DEFAULT nextval('car_events_id_seq'::regclass) NOT NULL,
    "driver_name" text NOT NULL,
    "status" text NOT NULL,
    "event_time" text NOT NULL,
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

CREATE TABLE public."chat_requests" (
    "id" bigint DEFAULT nextval('chat_requests_id_seq'::regclass) NOT NULL,
    "request_id" uuid NOT NULL,
    "user_id" integer NOT NULL,
    "family_id" integer NOT NULL,
    "status" text DEFAULT 'processing'::text NOT NULL,
    "original_message" text NOT NULL,
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
    "action_type" text NOT NULL,
    "arguments" jsonb NOT NULL,
    "status" text NOT NULL,
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
    "role" text NOT NULL,
    "content" text NOT NULL,
    "created_at" text NOT NULL,
    "chat_request_id" bigint
);
ALTER TABLE public."conversation_messages" OWNER TO postgres;

CREATE TABLE public."families" (
    "id" integer DEFAULT nextval('families_id_seq'::regclass) NOT NULL,
    "name" text NOT NULL,
    "family_code" text NOT NULL,
    "home_address" text NOT NULL,
    "home_latitude" double precision,
    "home_longitude" double precision,
    "created_at" text NOT NULL,
    "created_by_user_id" integer NOT NULL
);
ALTER TABLE public."families" OWNER TO postgres;

CREATE TABLE public."family_address_confirmations" (
    "token_digest" bytea NOT NULL,
    "purpose" text NOT NULL,
    "auth_user_id" uuid NOT NULL,
    "user_id" integer,
    "family_id" integer,
    "normalized_address" text NOT NULL,
    "display_address" text NOT NULL,
    "latitude" double precision NOT NULL,
    "longitude" double precision NOT NULL,
    "expires_at" timestamp with time zone DEFAULT (clock_timestamp() + '00:15:00'::interval) NOT NULL
);
ALTER TABLE public."family_address_confirmations" OWNER TO postgres;

CREATE TABLE public."family_code_history" (
    "code" text COLLATE "C" NOT NULL
);
ALTER TABLE public."family_code_history" OWNER TO postgres;

CREATE TABLE public."gemini_call_permits" (
    "permit_id" uuid NOT NULL,
    "chat_request_id" bigint NOT NULL,
    "attempt_token" uuid NOT NULL,
    "capacity_pool" text NOT NULL,
    "acquired_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "expires_at" timestamp with time zone NOT NULL
);
ALTER TABLE public."gemini_call_permits" OWNER TO postgres;

CREATE TABLE public."gemini_capacity_policies" (
    "capacity_pool" text NOT NULL,
    "max_concurrency" integer NOT NULL,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);
ALTER TABLE public."gemini_capacity_policies" OWNER TO postgres;

CREATE TABLE public."geocoding_attempts" (
    "attempt_id" uuid NOT NULL,
    "auth_user_id" uuid NOT NULL,
    "capacity_pool" text NOT NULL,
    "admitted_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "permit_expires_at" timestamp with time zone
);
ALTER TABLE public."geocoding_attempts" OWNER TO postgres;

CREATE TABLE public."geocoding_capacity_policies" (
    "capacity_pool" text NOT NULL,
    "max_concurrency" integer NOT NULL,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);
ALTER TABLE public."geocoding_capacity_policies" OWNER TO postgres;

CREATE TABLE public."push_subscriptions" (
    "id" bigint GENERATED BY DEFAULT AS IDENTITY (SEQUENCE NAME public."push_subscriptions_id_seq" START WITH 1 INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 CACHE 1 NO CYCLE) NOT NULL,
    "user_id" integer NOT NULL,
    "endpoint" text NOT NULL,
    "p256dh" text NOT NULL,
    "auth" text NOT NULL,
    "expiration_time" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
ALTER TABLE public."push_subscriptions" OWNER TO postgres;

CREATE TABLE public."pwa_join_sessions" (
    "auth_user_id" uuid NOT NULL,
    "step" text DEFAULT 'family_name'::text NOT NULL,
    "family_name" text,
    "family_id" integer,
    "normalized_address" text,
    "resolved_address" text,
    "family_name_attempts" smallint DEFAULT 0 NOT NULL,
    "address_attempts" smallint DEFAULT 0 NOT NULL,
    "family_code_attempts" smallint DEFAULT 0 NOT NULL,
    "locked_until" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
ALTER TABLE public."pwa_join_sessions" OWNER TO postgres;

CREATE TABLE public."reservations" (
    "id" integer DEFAULT nextval('reservations_id_seq'::regclass) NOT NULL,
    "user_id" integer NOT NULL,
    "start_time" text NOT NULL,
    "end_time" text NOT NULL,
    "status" text DEFAULT 'active'::text NOT NULL,
    "created_at" text NOT NULL
);
ALTER TABLE public."reservations" OWNER TO postgres;

CREATE TABLE public."users" (
    "id" integer DEFAULT nextval('users_id_seq'::regclass) NOT NULL,
    "name" text NOT NULL,
    "shortcut_token" text,
    "telegram_chat_id" bigint,
    "family_id" integer,
    "auth_user_id" uuid,
    "carplay_setup_status" text DEFAULT 'pending'::text NOT NULL,
    "family_role" text,
    "member_public_id" uuid DEFAULT gen_random_uuid() NOT NULL
);
ALTER TABLE public."users" OWNER TO postgres;

ALTER SEQUENCE public."car_events_id_seq" OWNED BY public."car_events"."id";

ALTER SEQUENCE public."chat_requests_id_seq" OWNED BY public."chat_requests"."id";

ALTER SEQUENCE public."chat_tool_actions_id_seq" OWNED BY public."chat_tool_actions"."id";

ALTER SEQUENCE public."conversation_messages_id_seq" OWNED BY public."conversation_messages"."id";

ALTER SEQUENCE public."families_id_seq" OWNED BY public."families"."id";

ALTER SEQUENCE public."reservations_id_seq" OWNED BY public."reservations"."id";

ALTER SEQUENCE public."users_id_seq" OWNED BY public."users"."id";

-- Exact captured constraints. Add referenced keys before foreign keys.
ALTER TABLE public."account_deletion_jobs" ADD CONSTRAINT "account_deletion_jobs_check" CHECK (next_attempt_at >= created_at);
ALTER TABLE public."account_deletion_jobs" ADD CONSTRAINT "account_deletion_jobs_created_at_check" CHECK (isfinite(created_at));
ALTER TABLE public."account_deletion_jobs" ADD CONSTRAINT "account_deletion_jobs_next_attempt_at_check" CHECK (isfinite(next_attempt_at));
ALTER TABLE public."account_deletion_jobs" ADD CONSTRAINT "account_deletion_jobs_phase_check" CHECK (phase = ANY (ARRAY['draining'::text, 'auth_pending'::text]));
ALTER TABLE public."account_deletion_jobs" ADD CONSTRAINT "account_deletion_jobs_pkey" PRIMARY KEY (auth_user_id);
ALTER TABLE public."car_events" ADD CONSTRAINT "car_events_pkey" PRIMARY KEY (id);
ALTER TABLE public."carplay_transition_admissions" ADD CONSTRAINT "carplay_transition_admissions_admitted_at_check" CHECK (isfinite(admitted_at));
ALTER TABLE public."carplay_transition_admissions" ADD CONSTRAINT "carplay_transition_admissions_pkey" PRIMARY KEY (admission_id);
ALTER TABLE public."chat_requests" ADD CONSTRAINT "chat_requests_error_status_check" CHECK (error_http_status IS NULL OR error_http_status >= 400 AND error_http_status <= 599);
ALTER TABLE public."chat_requests" ADD CONSTRAINT "chat_requests_message_check" CHECK (char_length(btrim(original_message)) >= 1 AND char_length(btrim(original_message)) <= 4000);
ALTER TABLE public."chat_requests" ADD CONSTRAINT "chat_requests_processing_attempts_check" CHECK (processing_attempts >= 1 AND processing_attempts <= 3);
ALTER TABLE public."chat_requests" ADD CONSTRAINT "chat_requests_state_check" CHECK (status = 'processing'::text AND final_response IS NULL AND error_payload IS NULL AND completed_at IS NULL OR status = 'completed'::text AND final_response IS NOT NULL AND error_payload IS NULL AND error_http_status IS NULL AND completed_at IS NOT NULL OR status = 'failed'::text AND final_response IS NULL AND error_payload IS NOT NULL AND error_http_status IS NOT NULL AND completed_at IS NOT NULL);
ALTER TABLE public."chat_requests" ADD CONSTRAINT "chat_requests_status_check" CHECK (status = ANY (ARRAY['processing'::text, 'completed'::text, 'failed'::text]));
ALTER TABLE public."chat_requests" ADD CONSTRAINT "chat_requests_pkey" PRIMARY KEY (id);
ALTER TABLE public."chat_requests" ADD CONSTRAINT "chat_requests_user_request_unique" UNIQUE (user_id, request_id);
ALTER TABLE public."chat_tool_actions" ADD CONSTRAINT "chat_tool_actions_state_check" CHECK (status = 'processing'::text AND result IS NULL AND error_payload IS NULL AND completed_at IS NULL OR status = 'completed'::text AND result IS NOT NULL AND error_payload IS NULL AND completed_at IS NOT NULL OR status = 'failed'::text AND result IS NULL AND error_payload IS NOT NULL AND completed_at IS NOT NULL);
ALTER TABLE public."chat_tool_actions" ADD CONSTRAINT "chat_tool_actions_status_check" CHECK (status = ANY (ARRAY['processing'::text, 'completed'::text, 'failed'::text]));
ALTER TABLE public."chat_tool_actions" ADD CONSTRAINT "chat_tool_actions_type_check" CHECK (action_type = ANY (ARRAY['create_reservation'::text, 'update_reservation'::text, 'cancel_reservation'::text]));
ALTER TABLE public."chat_tool_actions" ADD CONSTRAINT "chat_tool_actions_pkey" PRIMARY KEY (id);
ALTER TABLE public."chat_tool_actions" ADD CONSTRAINT "chat_tool_actions_request_unique" UNIQUE (chat_request_id);
ALTER TABLE public."conversation_messages" ADD CONSTRAINT "conversation_messages_pkey" PRIMARY KEY (id);
ALTER TABLE public."families" ADD CONSTRAINT "families_pkey" PRIMARY KEY (id);
ALTER TABLE public."families" ADD CONSTRAINT "families_family_code_key" UNIQUE (family_code);
ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_binding_check" CHECK (purpose = 'create_family'::text AND user_id IS NULL AND family_id IS NULL OR purpose = 'family_address_update'::text AND user_id IS NOT NULL AND family_id IS NOT NULL);
ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_display_address_check" CHECK (btrim(display_address) <> ''::text);
ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_expires_at_check" CHECK (isfinite(expires_at));
ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_latitude_check" CHECK (latitude >= '-90'::integer::double precision AND latitude <= 90::double precision);
ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_longitude_check" CHECK (longitude >= '-180'::integer::double precision AND longitude <= 180::double precision);
ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_normalized_address_check" CHECK (btrim(normalized_address) <> ''::text);
ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_purpose_check" CHECK (purpose = ANY (ARRAY['create_family'::text, 'family_address_update'::text]));
ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_token_digest_check" CHECK (octet_length(token_digest) = 32);
ALTER TABLE public."family_address_confirmations" ADD CONSTRAINT "family_address_confirmations_pkey" PRIMARY KEY (token_digest);
ALTER TABLE public."family_code_history" ADD CONSTRAINT "family_code_history_code_check" CHECK (octet_length(code) = 6 AND code ~ '^[a-z0-9]{6}$'::text);
ALTER TABLE public."family_code_history" ADD CONSTRAINT "family_code_history_pkey" PRIMARY KEY (code);
ALTER TABLE public."gemini_call_permits" ADD CONSTRAINT "gemini_call_permits_check" CHECK (isfinite(acquired_at) AND isfinite(expires_at) AND expires_at > acquired_at);
ALTER TABLE public."gemini_call_permits" ADD CONSTRAINT "gemini_call_permits_pkey" PRIMARY KEY (permit_id);
ALTER TABLE public."gemini_call_permits" ADD CONSTRAINT "gemini_call_permits_chat_request_id_key" UNIQUE (chat_request_id);
ALTER TABLE public."gemini_capacity_policies" ADD CONSTRAINT "gemini_capacity_policies_capacity_pool_check" CHECK (capacity_pool <> ''::text AND capacity_pool = btrim(capacity_pool));
ALTER TABLE public."gemini_capacity_policies" ADD CONSTRAINT "gemini_capacity_policies_max_concurrency_check" CHECK (max_concurrency > 0);
ALTER TABLE public."gemini_capacity_policies" ADD CONSTRAINT "gemini_capacity_policies_pkey" PRIMARY KEY (capacity_pool);
ALTER TABLE public."geocoding_attempts" ADD CONSTRAINT "geocoding_attempts_check" CHECK (isfinite(admitted_at) AND (permit_expires_at IS NULL OR isfinite(permit_expires_at) AND permit_expires_at > admitted_at));
ALTER TABLE public."geocoding_attempts" ADD CONSTRAINT "geocoding_attempts_pkey" PRIMARY KEY (attempt_id);
ALTER TABLE public."geocoding_capacity_policies" ADD CONSTRAINT "geocoding_capacity_policies_capacity_pool_check" CHECK (capacity_pool <> ''::text AND capacity_pool = btrim(capacity_pool));
ALTER TABLE public."geocoding_capacity_policies" ADD CONSTRAINT "geocoding_capacity_policies_max_concurrency_check" CHECK (max_concurrency > 0);
ALTER TABLE public."geocoding_capacity_policies" ADD CONSTRAINT "geocoding_capacity_policies_pkey" PRIMARY KEY (capacity_pool);
ALTER TABLE public."push_subscriptions" ADD CONSTRAINT "push_subscriptions_auth_nonempty_check" CHECK (length(auth) > 0);
ALTER TABLE public."push_subscriptions" ADD CONSTRAINT "push_subscriptions_endpoint_nonempty_check" CHECK (length(btrim(endpoint)) > 0);
ALTER TABLE public."push_subscriptions" ADD CONSTRAINT "push_subscriptions_p256dh_nonempty_check" CHECK (length(p256dh) > 0);
ALTER TABLE public."push_subscriptions" ADD CONSTRAINT "push_subscriptions_pkey" PRIMARY KEY (id);
ALTER TABLE public."push_subscriptions" ADD CONSTRAINT "push_subscriptions_endpoint_key" UNIQUE (endpoint);
ALTER TABLE public."pwa_join_sessions" ADD CONSTRAINT "pwa_join_sessions_address_attempts_check" CHECK (address_attempts >= 0 AND address_attempts <= 3);
ALTER TABLE public."pwa_join_sessions" ADD CONSTRAINT "pwa_join_sessions_family_code_attempts_check" CHECK (family_code_attempts >= 0 AND family_code_attempts <= 3);
ALTER TABLE public."pwa_join_sessions" ADD CONSTRAINT "pwa_join_sessions_family_name_attempts_check" CHECK (family_name_attempts >= 0 AND family_name_attempts <= 3);
ALTER TABLE public."pwa_join_sessions" ADD CONSTRAINT "pwa_join_sessions_step_check" CHECK (step = ANY (ARRAY['family_name'::text, 'address'::text, 'address_confirmed'::text, 'family_code'::text, 'user_name'::text, 'locked'::text]));
ALTER TABLE public."pwa_join_sessions" ADD CONSTRAINT "pwa_join_sessions_pkey" PRIMARY KEY (auth_user_id);
ALTER TABLE public."reservations" ADD CONSTRAINT "reservations_pkey" PRIMARY KEY (id);
ALTER TABLE public."users" ADD CONSTRAINT "users_carplay_setup_status_check" CHECK (carplay_setup_status = ANY (ARRAY['pending'::text, 'completed'::text, 'skipped'::text]));
ALTER TABLE public."users" ADD CONSTRAINT "users_family_role_check" CHECK (family_role IS NULL OR (family_role = ANY (ARRAY['parent'::text, 'child'::text])));
ALTER TABLE public."users" ADD CONSTRAINT "users_pkey" PRIMARY KEY (id);
ALTER TABLE public."users" ADD CONSTRAINT "users_auth_user_id_unique" UNIQUE (auth_user_id);
ALTER TABLE public."users" ADD CONSTRAINT "users_member_public_id_key" UNIQUE (member_public_id);
ALTER TABLE public."users" ADD CONSTRAINT "users_shortcut_token_key" UNIQUE (shortcut_token);
ALTER TABLE public."users" ADD CONSTRAINT "users_telegram_chat_id_key" UNIQUE (telegram_chat_id);
ALTER TABLE public."car_events" ADD CONSTRAINT "car_events_family_id_fkey" FOREIGN KEY (family_id) REFERENCES families(id);
ALTER TABLE public."car_events" ADD CONSTRAINT "car_events_user_id_fkey" FOREIGN KEY (user_id) REFERENCES users(id);
ALTER TABLE public."carplay_transition_admissions" ADD CONSTRAINT "carplay_transition_admissions_family_id_fkey" FOREIGN KEY (family_id) REFERENCES families(id) ON DELETE CASCADE;
ALTER TABLE public."carplay_transition_admissions" ADD CONSTRAINT "carplay_transition_admissions_user_id_fkey" FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
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
ALTER TABLE public."reservations" ADD CONSTRAINT "reservations_user_id_fkey" FOREIGN KEY (user_id) REFERENCES users(id);
ALTER TABLE public."users" ADD CONSTRAINT "users_auth_user_id_fkey" FOREIGN KEY (auth_user_id) REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE public."users" ADD CONSTRAINT "users_family_id_fkey" FOREIGN KEY (family_id) REFERENCES families(id);

-- Constraint-backed indexes are created by their named PK/UNIQUE constraints.
CREATE INDEX account_deletion_jobs_next_attempt_idx ON public.account_deletion_jobs USING btree (next_attempt_at, auth_user_id);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX account_deletion_jobs_pkey ON public.account_deletion_jobs USING btree (auth_user_id);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX car_events_pkey ON public.car_events USING btree (id);
CREATE INDEX carplay_transition_admissions_admitted_idx ON public.carplay_transition_admissions USING btree (admitted_at);
CREATE INDEX carplay_transition_admissions_family_admitted_idx ON public.carplay_transition_admissions USING btree (family_id, admitted_at);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX carplay_transition_admissions_pkey ON public.carplay_transition_admissions USING btree (admission_id);
CREATE INDEX carplay_transition_admissions_user_admitted_idx ON public.carplay_transition_admissions USING btree (user_id, admitted_at);
CREATE INDEX chat_requests_expired_processing_idx ON public.chat_requests USING btree (lease_expires_at) WHERE (status = 'processing'::text);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX chat_requests_pkey ON public.chat_requests USING btree (id);
CREATE INDEX chat_requests_user_family_created_idx ON public.chat_requests USING btree (user_id, family_id, created_at DESC);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX chat_requests_user_request_unique ON public.chat_requests USING btree (user_id, request_id);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX chat_tool_actions_pkey ON public.chat_tool_actions USING btree (id);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX chat_tool_actions_request_unique ON public.chat_tool_actions USING btree (chat_request_id);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX conversation_messages_pkey ON public.conversation_messages USING btree (id);
CREATE UNIQUE INDEX conversation_messages_request_assistant_unique ON public.conversation_messages USING btree (chat_request_id) WHERE ((chat_request_id IS NOT NULL) AND (role = 'assistant'::text));
CREATE UNIQUE INDEX conversation_messages_request_user_unique ON public.conversation_messages USING btree (chat_request_id) WHERE ((chat_request_id IS NOT NULL) AND (role = 'user'::text));
CREATE INDEX conversation_messages_user_request_history_idx ON public.conversation_messages USING btree (user_id, id DESC) WHERE (chat_request_id IS NOT NULL);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX families_family_code_key ON public.families USING btree (family_code);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX families_pkey ON public.families USING btree (id);
CREATE INDEX family_address_confirmations_auth_idx ON public.family_address_confirmations USING btree (auth_user_id);
CREATE UNIQUE INDEX family_address_confirmations_create_identity_idx ON public.family_address_confirmations USING btree (auth_user_id) WHERE (purpose = 'create_family'::text);
CREATE INDEX family_address_confirmations_expiry_idx ON public.family_address_confirmations USING btree (expires_at);
CREATE INDEX family_address_confirmations_family_idx ON public.family_address_confirmations USING btree (family_id) WHERE (family_id IS NOT NULL);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX family_address_confirmations_pkey ON public.family_address_confirmations USING btree (token_digest);
CREATE UNIQUE INDEX family_address_confirmations_update_identity_idx ON public.family_address_confirmations USING btree (user_id) WHERE (purpose = 'family_address_update'::text);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX family_code_history_pkey ON public.family_code_history USING btree (code);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX gemini_call_permits_chat_request_id_key ON public.gemini_call_permits USING btree (chat_request_id);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX gemini_call_permits_pkey ON public.gemini_call_permits USING btree (permit_id);
CREATE INDEX gemini_call_permits_pool_expiry_idx ON public.gemini_call_permits USING btree (capacity_pool, expires_at);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX gemini_capacity_policies_pkey ON public.gemini_capacity_policies USING btree (capacity_pool);
CREATE INDEX geocoding_attempts_active_expiry_idx ON public.geocoding_attempts USING btree (permit_expires_at) WHERE (permit_expires_at IS NOT NULL);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX geocoding_attempts_pkey ON public.geocoding_attempts USING btree (attempt_id);
CREATE INDEX geocoding_attempts_user_admitted_idx ON public.geocoding_attempts USING btree (auth_user_id, admitted_at);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX geocoding_capacity_policies_pkey ON public.geocoding_capacity_policies USING btree (capacity_pool);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX push_subscriptions_endpoint_key ON public.push_subscriptions USING btree (endpoint);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX push_subscriptions_pkey ON public.push_subscriptions USING btree (id);
CREATE INDEX push_subscriptions_user_id_idx ON public.push_subscriptions USING btree (user_id);
CREATE INDEX pwa_join_sessions_locked_until_idx ON public.pwa_join_sessions USING btree (locked_until) WHERE (locked_until IS NOT NULL);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX pwa_join_sessions_pkey ON public.pwa_join_sessions USING btree (auth_user_id);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX reservations_pkey ON public.reservations USING btree (id);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX users_auth_user_id_unique ON public.users USING btree (auth_user_id);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX users_member_public_id_key ON public.users USING btree (member_public_id);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX users_pkey ON public.users USING btree (id);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX users_shortcut_token_key ON public.users USING btree (shortcut_token);
-- Constraint-backed captured definition: CREATE UNIQUE INDEX users_telegram_chat_id_key ON public.users USING btree (telegram_chat_id);

-- Exact captured RLS flags; no public-table policies are created.
ALTER TABLE public."account_deletion_jobs" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."account_deletion_jobs" NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public."car_events" DISABLE ROW LEVEL SECURITY;
ALTER TABLE public."car_events" NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public."carplay_transition_admissions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."carplay_transition_admissions" NO FORCE ROW LEVEL SECURITY;
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
ALTER TABLE public."reservations" DISABLE ROW LEVEL SECURITY;
ALTER TABLE public."reservations" NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public."users" DISABLE ROW LEVEL SECURITY;
ALTER TABLE public."users" NO FORCE ROW LEVEL SECURITY;

-- Remove inherited creation defaults, then reproduce captured object access.
-- Owner grant authority is intrinsic; table capture reports postgres grantable.
REVOKE ALL PRIVILEGES ON TABLE public."account_deletion_jobs" FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."account_deletion_jobs" TO postgres WITH GRANT OPTION;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."account_deletion_jobs" TO service_role;
REVOKE ALL PRIVILEGES ON TABLE public."car_events" FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."car_events" TO postgres WITH GRANT OPTION;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."car_events" TO service_role;
REVOKE ALL PRIVILEGES ON TABLE public."carplay_transition_admissions" FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."carplay_transition_admissions" TO postgres WITH GRANT OPTION;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."carplay_transition_admissions" TO service_role;
REVOKE ALL PRIVILEGES ON TABLE public."chat_requests" FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."chat_requests" TO postgres WITH GRANT OPTION;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."chat_requests" TO service_role;
REVOKE ALL PRIVILEGES ON TABLE public."chat_tool_actions" FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."chat_tool_actions" TO postgres WITH GRANT OPTION;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."chat_tool_actions" TO service_role;
REVOKE ALL PRIVILEGES ON TABLE public."conversation_messages" FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."conversation_messages" TO postgres WITH GRANT OPTION;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."conversation_messages" TO service_role;
REVOKE ALL PRIVILEGES ON TABLE public."families" FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."families" TO postgres WITH GRANT OPTION;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."families" TO service_role;
REVOKE ALL PRIVILEGES ON TABLE public."family_address_confirmations" FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."family_address_confirmations" TO postgres WITH GRANT OPTION;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."family_address_confirmations" TO service_role;
REVOKE ALL PRIVILEGES ON TABLE public."family_code_history" FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."family_code_history" TO postgres WITH GRANT OPTION;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."family_code_history" TO service_role;
REVOKE ALL PRIVILEGES ON TABLE public."gemini_call_permits" FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."gemini_call_permits" TO postgres WITH GRANT OPTION;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."gemini_call_permits" TO service_role;
REVOKE ALL PRIVILEGES ON TABLE public."gemini_capacity_policies" FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."gemini_capacity_policies" TO postgres WITH GRANT OPTION;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."gemini_capacity_policies" TO service_role;
REVOKE ALL PRIVILEGES ON TABLE public."geocoding_attempts" FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."geocoding_attempts" TO postgres WITH GRANT OPTION;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."geocoding_attempts" TO service_role;
REVOKE ALL PRIVILEGES ON TABLE public."geocoding_capacity_policies" FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."geocoding_capacity_policies" TO postgres WITH GRANT OPTION;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."geocoding_capacity_policies" TO service_role;
REVOKE ALL PRIVILEGES ON TABLE public."push_subscriptions" FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."push_subscriptions" TO postgres WITH GRANT OPTION;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."push_subscriptions" TO service_role;
REVOKE ALL PRIVILEGES ON TABLE public."pwa_join_sessions" FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."pwa_join_sessions" TO postgres WITH GRANT OPTION;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."pwa_join_sessions" TO service_role;
REVOKE ALL PRIVILEGES ON TABLE public."reservations" FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."reservations" TO postgres WITH GRANT OPTION;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."reservations" TO service_role;
REVOKE ALL PRIVILEGES ON TABLE public."users" FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."users" TO postgres WITH GRANT OPTION;
GRANT DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE public."users" TO service_role;
-- No explicit column ACLs exist in the capture; none are added.
REVOKE ALL PRIVILEGES ON SEQUENCE public."car_events_id_seq" FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, UPDATE, USAGE ON SEQUENCE public."car_events_id_seq" TO postgres, service_role;
REVOKE ALL PRIVILEGES ON SEQUENCE public."chat_requests_id_seq" FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, UPDATE, USAGE ON SEQUENCE public."chat_requests_id_seq" TO postgres, service_role;
REVOKE ALL PRIVILEGES ON SEQUENCE public."chat_tool_actions_id_seq" FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, UPDATE, USAGE ON SEQUENCE public."chat_tool_actions_id_seq" TO postgres, service_role;
REVOKE ALL PRIVILEGES ON SEQUENCE public."conversation_messages_id_seq" FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, UPDATE, USAGE ON SEQUENCE public."conversation_messages_id_seq" TO postgres, service_role;
REVOKE ALL PRIVILEGES ON SEQUENCE public."families_id_seq" FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, UPDATE, USAGE ON SEQUENCE public."families_id_seq" TO postgres, service_role;
REVOKE ALL PRIVILEGES ON SEQUENCE public."push_subscriptions_id_seq" FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, UPDATE, USAGE ON SEQUENCE public."push_subscriptions_id_seq" TO postgres, service_role;
REVOKE ALL PRIVILEGES ON SEQUENCE public."reservations_id_seq" FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, UPDATE, USAGE ON SEQUENCE public."reservations_id_seq" TO postgres, service_role;
REVOKE ALL PRIVILEGES ON SEQUENCE public."users_id_seq" FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, UPDATE, USAGE ON SEQUENCE public."users_id_seq" TO postgres, service_role;

-- Exact captured function bodies (Markdown line breaks decoded).
CREATE OR REPLACE FUNCTION public.broadcast_car_status_changed()
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
REVOKE ALL PRIVILEGES ON FUNCTION public.broadcast_car_status_changed() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.broadcast_car_status_changed() TO postgres, service_role;
CREATE OR REPLACE FUNCTION public.can_receive_car_status_topic(requested_topic text)
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
ALTER FUNCTION public.can_receive_car_status_topic(text) OWNER TO postgres;
REVOKE ALL PRIVILEGES ON FUNCTION public.can_receive_car_status_topic(text) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.can_receive_car_status_topic(text) TO postgres, service_role, anon, authenticated;

CREATE TRIGGER car_events_broadcast_car_status AFTER INSERT ON car_events FOR EACH ROW WHEN (new.family_id IS NOT NULL) EXECUTE FUNCTION broadcast_car_status_changed();
CREATE POLICY "family_members_receive_car_status" ON realtime.messages AS PERMISSIVE FOR SELECT TO authenticated USING (((extension = 'broadcast'::text) AND can_receive_car_status_topic(( SELECT realtime.topic() AS topic))));

-- Only intentional bootstrap configuration, never captured runtime timestamps.
INSERT INTO public.gemini_capacity_policies (capacity_pool, max_concurrency) VALUES ('gemini-default', 50);
INSERT INTO public.geocoding_capacity_policies (capacity_pool, max_concurrency) VALUES ('google-geocoding', 20);
COMMIT;
