-- MANUALLY EXECUTED / OPERATOR-VERIFIED. Schema foundation, NOT a runtime cutover.
-- No legacy state, Shortcut, Realtime, or reservation timestamp conversion.
BEGIN;
SET LOCAL search_path = pg_catalog, public;
SET LOCAL lock_timeout = '5s';

DO $preflight$
DECLARE
    expected record;
    object_name text;
BEGIN
    IF current_user <> 'postgres' THEN
        RAISE EXCEPTION 'Run this manual migration as postgres';
    END IF;
    -- Column-specific SET NULL on composite FKs preserves required bindings.
    IF current_setting('server_version_num')::integer < 150000 THEN
        RAISE EXCEPTION 'PostgreSQL 15 or newer is required';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon')
       OR NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated')
       OR NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'service_role') THEN
        RAISE EXCEPTION 'Expected Supabase roles';
    END IF;
    IF to_regprocedure('pg_catalog.gen_random_uuid()') IS NULL THEN
        RAISE EXCEPTION 'Expected built-in UUID generation; no extension is installed here';
    END IF;
    FOR expected IN SELECT * FROM (VALUES
        ('public.families', 'id', 'integer', true),
        ('public.families', 'created_by_user_id', 'integer', true),
        ('public.users', 'id', 'integer', true),
        ('public.users', 'family_id', 'integer', false),
        ('public.reservations', 'id', 'integer', true),
        ('public.reservations', 'user_id', 'integer', true),
        ('public.reservations', 'start_time', 'text', true),
        ('public.reservations', 'end_time', 'text', true)
    ) AS required(table_name, column_name, type_name, require_not_null)
    LOOP
        IF NOT EXISTS (SELECT FROM pg_class WHERE oid = to_regclass(expected.table_name)
                       AND relkind = 'r')
           OR NOT EXISTS (
               SELECT FROM pg_attribute WHERE attrelid = to_regclass(expected.table_name)
                 AND attname = expected.column_name AND NOT attisdropped
                 AND format_type(atttypid, atttypmod) = expected.type_name
                 AND (NOT expected.require_not_null OR attnotnull)
           ) THEN
            RAISE EXCEPTION 'Unexpected required column: %.%', expected.table_name, expected.column_name;
        END IF;
    END LOOP;
    FOREACH object_name IN ARRAY ARRAY[
        'vehicles', 'registered_devices', 'vehicle_events', 'vehicle_driver_sessions',
        'vehicles_id_seq', 'registered_devices_id_seq', 'vehicle_events_id_seq',
        'vehicle_driver_sessions_id_seq', 'users_vehicle_membership_key',
        'reservations_reservation_ref_key', 'reservations_vehicle_time_idx'
    ] LOOP
        IF to_regclass('public.' || object_name) IS NOT NULL THEN
            RAISE EXCEPTION 'Already applied or conflicting object: %', object_name;
        END IF;
    END LOOP;
    IF EXISTS (
        SELECT FROM pg_attribute WHERE NOT attisdropped AND (
            (attrelid = 'public.families'::regclass AND attname IN
                ('vehicle_reconciliation_generation', 'vehicle_finalized_through'))
            OR (attrelid = 'public.reservations'::regclass AND attname IN
                ('reservation_ref', 'vehicle_id')))
    ) OR to_regprocedure('public.guard_vehicle_checkpoint()') IS NOT NULL
      OR to_regprocedure('public.guard_vehicle_event_evidence()') IS NOT NULL THEN
        RAISE EXCEPTION 'Existing Multi-Car foundation columns/functions';
    END IF;
END
$preflight$;

-- Additive supporting key: an independent user FK would not prove membership.
ALTER TABLE public.users ADD CONSTRAINT users_vehicle_membership_key UNIQUE (id, family_id);

ALTER TABLE public.families
    ADD COLUMN vehicle_reconciliation_generation bigint NOT NULL DEFAULT 0,
    ADD COLUMN vehicle_finalized_through timestamptz,
    ADD CONSTRAINT families_vehicle_checkpoint_check CHECK (
        (vehicle_reconciliation_generation = 0 AND vehicle_finalized_through IS NULL)
        OR (vehicle_reconciliation_generation > 0 AND vehicle_finalized_through IS NOT NULL
            AND isfinite(vehicle_finalized_through))
    );

-- CHECK cannot compare OLD/NEW. This narrow guard enforces monotonic metadata,
-- not replay/deletion logic. Existing family updates do not fire this trigger.
CREATE FUNCTION public.guard_vehicle_checkpoint() RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $function$
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
CREATE TRIGGER families_vehicle_checkpoint_guard
    BEFORE UPDATE OF vehicle_reconciliation_generation, vehicle_finalized_through
    ON public.families FOR EACH ROW EXECUTE FUNCTION public.guard_vehicle_checkpoint();

CREATE TABLE public.vehicles (
    id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    vehicle_ref uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    family_id integer NOT NULL REFERENCES public.families(id) ON DELETE CASCADE,
    display_name text NOT NULL CHECK (display_name !~ '^[[:space:]]*$'),
    created_by_user_id integer REFERENCES public.users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK (isfinite(created_at)),
    retired_at timestamptz CHECK (isfinite(retired_at) AND retired_at >= created_at),
    CONSTRAINT vehicles_family_identity_key UNIQUE (id, family_id)
);
CREATE INDEX vehicles_family_active_idx ON public.vehicles (family_id, id)
    WHERE retired_at IS NULL;
-- The composite key starts with id; this also supports whole-family cleanup.
CREATE INDEX vehicles_family_idx ON public.vehicles (family_id);
CREATE INDEX vehicles_creator_idx ON public.vehicles (created_by_user_id)
    WHERE created_by_user_id IS NOT NULL;

CREATE TABLE public.registered_devices (
    id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    device_ref uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    user_id integer NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    platform text NOT NULL CHECK (platform IN ('android', 'ios')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK (isfinite(created_at)),
    last_seen_at timestamptz CHECK (isfinite(last_seen_at) AND last_seen_at >= created_at),
    revoked_at timestamptz CHECK (isfinite(revoked_at) AND revoked_at >= created_at),
    last_processed_sequence bigint NOT NULL DEFAULT 0 CHECK (last_processed_sequence >= 0),
    CONSTRAINT registered_devices_owner_key UNIQUE (id, user_id)
);
CREATE INDEX registered_devices_user_idx ON public.registered_devices (user_id, id);

CREATE TABLE public.vehicle_events (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    event_id uuid NOT NULL UNIQUE,
    family_id integer NOT NULL,
    vehicle_id integer NOT NULL,
    user_id integer NOT NULL,
    device_id integer,
    -- Source is supplied by the future trusted adapter, never client authority.
    source text NOT NULL CHECK (source IN ('native', 'legacy_shortcut')),
    event_type text NOT NULL CHECK (event_type IN ('take', 'return')),
    device_sequence bigint CHECK (device_sequence > 0),
    occurred_at timestamptz NOT NULL CHECK (isfinite(occurred_at)),
    received_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK (isfinite(received_at)),
    admission_outcome text NOT NULL CHECK (admission_outcome IN (
        'accepted', 'before_finalized_boundary', 'invalid_chronology',
        'reconciliation_policy_exceeded', 'causal_conflict', 'vehicle_retired'
    )),
    -- Raw causal UUID, NOT a FK: a terminal causal-conflict receipt must be able
    -- to record a missing/nonexistent TAKE. Future admission checks type/owner/
    -- vehicle/time before accepting; no payload, name or coordinates are stored.
    take_event_id uuid,
    -- Mutable projection association. Points to the logical session's TAKE,
    -- including for redundant accepted TAKE signals. No event -> session FK.
    projection_take_event_id uuid,
    CONSTRAINT vehicle_events_vehicle_fkey FOREIGN KEY (vehicle_id, family_id)
        REFERENCES public.vehicles(id, family_id) ON DELETE CASCADE,
    CONSTRAINT vehicle_events_member_fkey FOREIGN KEY (user_id, family_id)
        REFERENCES public.users(id, family_id) ON DELETE CASCADE,
    CONSTRAINT vehicle_events_device_fkey FOREIGN KEY (device_id, user_id)
        REFERENCES public.registered_devices(id, user_id) ON DELETE NO ACTION,
    CONSTRAINT vehicle_events_device_sequence_key UNIQUE (device_id, device_sequence),
    CONSTRAINT vehicle_events_binding_check CHECK (
        (source = 'native' AND device_id IS NOT NULL AND device_sequence IS NOT NULL)
        OR (source = 'legacy_shortcut' AND device_id IS NULL AND device_sequence IS NULL)
    ),
    CONSTRAINT vehicle_events_cause_check CHECK (
        (event_type = 'take' AND take_event_id IS NULL)
        OR (event_type = 'return' AND take_event_id IS NOT NULL AND take_event_id <> event_id)
    ),
    CONSTRAINT vehicle_events_projection_check CHECK (
        projection_take_event_id IS NULL OR admission_outcome = 'accepted'
    ),
    CONSTRAINT vehicle_events_anchor_identity_key UNIQUE (event_id, user_id, vehicle_id, family_id),
    CONSTRAINT vehicle_events_family_identity_key UNIQUE (event_id, family_id),
    CONSTRAINT vehicle_events_projection_fkey
        FOREIGN KEY (projection_take_event_id, user_id, vehicle_id, family_id)
        REFERENCES public.vehicle_events(event_id, user_id, vehicle_id, family_id)
        ON DELETE NO ACTION DEFERRABLE INITIALLY IMMEDIATE
);
CREATE INDEX vehicle_events_family_chronology_idx
    ON public.vehicle_events (family_id, occurred_at, event_id) WHERE admission_outcome = 'accepted';
CREATE INDEX vehicle_events_vehicle_chronology_idx ON public.vehicle_events (vehicle_id, occurred_at, event_id);
CREATE INDEX vehicle_events_user_chronology_idx ON public.vehicle_events (user_id, occurred_at, event_id);
CREATE INDEX vehicle_events_projection_idx ON public.vehicle_events (projection_take_event_id)
    WHERE projection_take_event_id IS NOT NULL;

-- Evidence/admission fields cannot be overwritten by a conflicting retry.
-- DELETE remains available for the existing privacy lifecycle. Only the derived
-- projection association may change during future transactional reconciliation.
CREATE FUNCTION public.guard_vehicle_event_evidence() RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $function$
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
CREATE TRIGGER vehicle_events_evidence_guard BEFORE UPDATE ON public.vehicle_events
    FOR EACH ROW EXECUTE FUNCTION public.guard_vehicle_event_evidence();

CREATE TABLE public.vehicle_driver_sessions (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    session_ref uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    family_id integer NOT NULL,
    vehicle_id integer NOT NULL,
    user_id integer NOT NULL,
    started_at timestamptz NOT NULL CHECK (isfinite(started_at)),
    ended_at timestamptz CHECK (isfinite(ended_at)),
    -- Nullable links survive privacy deletion; session -> event only. Backend
    -- must check start TAKE ownership/type and match projection_take_event_id.
    start_event_id uuid UNIQUE,
    -- One TAKE can close sessions on DIFFERENT vehicles and for different users.
    end_event_id uuid,
    end_reason text CHECK (end_reason IN ('return', 'handover', 'vehicle_switch', 'account_deletion')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK (isfinite(created_at)),
    checkpoint_generation bigint CHECK (checkpoint_generation > 0),
    CONSTRAINT vehicle_sessions_vehicle_fkey FOREIGN KEY (vehicle_id, family_id)
        REFERENCES public.vehicles(id, family_id) ON DELETE CASCADE,
    CONSTRAINT vehicle_sessions_member_fkey FOREIGN KEY (user_id, family_id)
        REFERENCES public.users(id, family_id) ON DELETE CASCADE,
    CONSTRAINT vehicle_sessions_start_event_fkey
        FOREIGN KEY (start_event_id, user_id, vehicle_id, family_id)
        REFERENCES public.vehicle_events(event_id, user_id, vehicle_id, family_id)
        ON DELETE SET NULL (start_event_id),
    CONSTRAINT vehicle_sessions_end_event_fkey FOREIGN KEY (end_event_id, family_id)
        REFERENCES public.vehicle_events(event_id, family_id)
        ON DELETE SET NULL (end_event_id),
    CONSTRAINT vehicle_sessions_end_check CHECK (
        (ended_at IS NULL AND end_reason IS NULL AND end_event_id IS NULL)
        OR (ended_at IS NOT NULL AND ended_at >= started_at AND end_reason IS NOT NULL)
    ),
    -- Built-in range GiST operator classes avoid requiring btree_gist (absent
    -- from the baseline). Singleton bigint ranges model equality of integer IDs.
    -- [start,end) permits adjacent and zero-duration reconciled sessions, while
    -- preventing overlapping historical as well as active occupancy.
    CONSTRAINT vehicle_sessions_vehicle_no_overlap EXCLUDE USING gist (
        int8range(vehicle_id::bigint, vehicle_id::bigint, '[]') WITH &&,
        tstzrange(started_at, ended_at, '[)') WITH &&
    ) DEFERRABLE INITIALLY IMMEDIATE,
    CONSTRAINT vehicle_sessions_user_no_overlap EXCLUDE USING gist (
        int8range(user_id::bigint, user_id::bigint, '[]') WITH &&,
        tstzrange(started_at, ended_at, '[)') WITH &&
    ) DEFERRABLE INITIALLY IMMEDIATE
);
CREATE UNIQUE INDEX vehicle_sessions_active_vehicle_idx ON public.vehicle_driver_sessions (vehicle_id)
    WHERE ended_at IS NULL;
CREATE UNIQUE INDEX vehicle_sessions_active_user_idx ON public.vehicle_driver_sessions (user_id)
    WHERE ended_at IS NULL;
CREATE INDEX vehicle_sessions_checkpoint_idx ON public.vehicle_driver_sessions (family_id, checkpoint_generation)
    WHERE checkpoint_generation IS NOT NULL;
CREATE INDEX vehicle_sessions_family_time_idx ON public.vehicle_driver_sessions (family_id, started_at, id);
CREATE INDEX vehicle_sessions_user_idx ON public.vehicle_driver_sessions (user_id);
CREATE INDEX vehicle_sessions_vehicle_idx ON public.vehicle_driver_sessions (vehicle_id);
CREATE INDEX vehicle_sessions_end_event_idx ON public.vehicle_driver_sessions (end_event_id)
    WHERE end_event_id IS NOT NULL;

-- Nullable-first UUID backfill avoids adding a volatile DEFAULT to the entire
-- existing table in one ALTER. This still writes every reservation and builds a
-- unique index under transactional DDL locks: schedule a controlled maintenance
-- window. Concurrent old inserts are blocked until COMMIT and then get a UUID.
ALTER TABLE public.reservations
    ADD COLUMN reservation_ref uuid,
    ADD COLUMN vehicle_id integer REFERENCES public.vehicles(id) ON DELETE RESTRICT;
ALTER TABLE public.reservations ALTER COLUMN reservation_ref SET DEFAULT gen_random_uuid();
UPDATE public.reservations SET reservation_ref = gen_random_uuid() WHERE reservation_ref IS NULL;
ALTER TABLE public.reservations
    ALTER COLUMN reservation_ref SET NOT NULL,
    ADD CONSTRAINT reservations_reservation_ref_key UNIQUE (reservation_ref);
CREATE INDEX reservations_vehicle_time_idx ON public.reservations (vehicle_id, start_time, end_time)
    WHERE status = 'active';

-- Match the baseline backend-only object ACL model, independent of provider
-- default ACLs. No new browser policy, RLS change or ALTER DEFAULT PRIVILEGES.
DO $privileges$
DECLARE
    table_name text;
    columns_sql text;
    owned_sequence record;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'vehicles', 'registered_devices', 'vehicle_events', 'vehicle_driver_sessions'
    ] LOOP
        EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE public.%I FROM PUBLIC, anon, authenticated', table_name);
        SELECT string_agg(quote_ident(attname), ', ' ORDER BY attnum) INTO columns_sql
            FROM pg_attribute WHERE attrelid = to_regclass('public.' || table_name)
              AND attnum > 0 AND NOT attisdropped;
        EXECUTE format('REVOKE ALL PRIVILEGES (%s) ON TABLE public.%I FROM PUBLIC, anon, authenticated', columns_sql, table_name);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER, TRUNCATE ON TABLE public.%I TO service_role', table_name);
    END LOOP;
    FOR owned_sequence IN
        SELECT ns.nspname, seq.relname FROM pg_class seq
        JOIN pg_namespace ns ON ns.oid = seq.relnamespace
        JOIN pg_depend d ON d.classid = 'pg_class'::regclass AND d.objid = seq.oid
        WHERE seq.relkind = 'S' AND d.refclassid = 'pg_class'::regclass
          AND d.deptype IN ('a', 'i') AND d.refobjid IN (
              'public.vehicles'::regclass, 'public.registered_devices'::regclass,
              'public.vehicle_events'::regclass, 'public.vehicle_driver_sessions'::regclass)
    LOOP
        EXECUTE format('REVOKE ALL PRIVILEGES ON SEQUENCE %I.%I FROM PUBLIC, anon, authenticated', owned_sequence.nspname, owned_sequence.relname);
        EXECUTE format('GRANT USAGE, SELECT, UPDATE ON SEQUENCE %I.%I TO service_role', owned_sequence.nspname, owned_sequence.relname);
    END LOOP;
END
$privileges$;
REVOKE ALL PRIVILEGES (vehicle_reconciliation_generation, vehicle_finalized_through)
    ON TABLE public.families FROM PUBLIC, anon, authenticated;
REVOKE ALL PRIVILEGES (reservation_ref, vehicle_id)
    ON TABLE public.reservations FROM PUBLIC, anon, authenticated;
REVOKE ALL PRIVILEGES ON FUNCTION public.guard_vehicle_checkpoint(), public.guard_vehicle_event_evidence()
    FROM PUBLIC, anon, authenticated;
-- postgres ownership is intrinsic; service_role remains a backend role.
GRANT EXECUTE ON FUNCTION public.guard_vehicle_checkpoint(), public.guard_vehicle_event_evidence() TO service_role;

-- FUTURE RUNTIME CONTRACT (not implemented here): identity fence -> family
-- transition lock; atomic sequence receipt/progress and bounded family replay.
-- Seed from marked sessions even when now ended. Never replay <= finalized
-- boundary. Deletion finalizes/marks survivors and erases attributable records
-- atomically; last-member cleanup removes reservations before vehicles/family.
-- Preserve seed causal associations before pruning events. Do not enable writes
-- until deletion integration, retirement checks, causal checks, sequence checks,
-- reservation family authorization and legacy authority routing are implemented.
COMMIT;
