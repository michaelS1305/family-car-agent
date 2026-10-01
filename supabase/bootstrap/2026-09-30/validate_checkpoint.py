"""Offline, exact checkpoint comparison against local operator evidence; no DB access.

The renderer is deliberately specific to this frozen capture, not a migration engine.
Raw evidence stays ignored. This module never writes files or executes SQL.
"""
import argparse
import difflib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_EVIDENCE = ROOT.parents[1] / "schema_audit" / "2026-09-30-production"
TABLES = tuple(sorted("""account_deletion_jobs car_events carplay_transition_admissions
carplay_vehicle_bindings chat_requests chat_tool_actions conversation_messages families
family_address_confirmations family_code_history gemini_call_permits gemini_capacity_policies
geocoding_attempts geocoding_capacity_policies push_subscriptions pwa_join_sessions
registered_device_vehicle_bindings registered_devices reservations users
vehicle_driver_sessions vehicle_events vehicles""".split()))
FUNCTIONS = tuple(sorted(("broadcast_car_status_changed", "can_receive_car_status_topic",
                          "guard_vehicle_checkpoint", "guard_vehicle_event_evidence",
                          "broadcast_vehicle_member_deleted")))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def ident(value):
    return '"' + value.replace('"', '""') + '"'


def literal(value):
    return "'" + value.replace("'", "''") + "'"


def load_evidence(path):
    def read(filename, key):
        return json.loads((path / filename).read_text(encoding="utf-8-sig"))[0][key]
    return {
        "objects": read("02-object-inventory.json", "object_inventory"),
        "columns": read("03-public-columns.json", "public_columns"),
        "structure": read("04-constraints-indexes.json", "constraints_and_indexes"),
        "sequences": read("05-public-sequences.json", "public_sequences"),
        "routines": read("06-routines-triggers.json", "routines_and_triggers"),
        "rls": read("07-rls-policies.json", "rls_metadata"),
        "acl": read("08-privilege.json", "privilege_metadata"),
        "targeted": read("13-targeted-definitions.json", "targeted_production_evidence"),
        "seeds": json.loads((path / "12-capacity-config.json").read_text(encoding="utf-8-sig")),
    }


def normalize_indexes(rows, constraints):
    """Capture rows are index/constraint associations, not physical indexes.

    This capture is public-only and omits schema. FK associations reference an
    existing index; only p/u/x constraints own and implicitly create indexes.
    """
    grouped = {}
    constraint_map = {(c['table'], c['name']): c for c in constraints}
    owners = {(c['table'], c['name']): c for c in constraints if c['type'] in ('p', 'u', 'x')}
    seen_owners = set()
    for row in rows:
        physical = {k: v for k, v in row.items() if k != 'constraint'}
        physical.setdefault('schema', 'public')
        require(physical['schema'] == 'public', 'Unexpected index schema')
        key = (physical['schema'], physical['name'])
        if key not in grouped:
            grouped[key] = (physical, set())
        previous, associations = grouped[key]
        require(previous == physical, f'Conflicting physical index metadata: {key}')
        associations.add(row['constraint'])
    result = []
    for key, (physical, associations) in sorted(grouped.items()):
        owning = []
        for name in associations - {None}:
            c = constraint_map.get((physical['table'], name))
            require(c is not None, f'Unknown index constraint association: {key}/{name}')
            require(c['type'] in ('p', 'u', 'x', 'f'), 'Unexpected index constraint type')
            if c['type'] in ('p', 'u', 'x'):
                require(c['name'] == physical['name'], 'Unexpected owning index name')
                owning.append(c)
            else:
                require(c['referenced_schema'] == key[0] and
                        c['referenced_table'] == physical['table'], 'Invalid FK index reference')
        require(len(owning) <= 1, 'Multiple owners for physical index')
        owner = owning[0] if owning else None
        require(not (owner and None in associations), 'Conflicting owner/null association')
        require(physical['primary'] == bool(owner and owner['type'] == 'p') and
                physical['exclusion'] == bool(owner and owner['type'] == 'x'),
                'Index flags disagree with owning constraint')
        if owner:
            require(physical['unique'] == (owner['type'] in ('p', 'u')), 'Unexpected owning index uniqueness')
            seen_owners.add((owner['table'], owner['name']))
        result.append({**physical, 'constraint': owner['name'] if owner else None})
    require(seen_owners == set(owners), 'Missing constraint-created physical index')
    return result


def render(e):
    """Return deterministic DDL from captured definitions, rejecting contract drift."""
    tables = [o for o in e["objects"] if o["schema"] == "public" and o["kind"] == "table"]
    require(sorted(o["name"] for o in tables) == list(TABLES), "Expected exactly 23 tables")
    require(all(o["owner"] == "postgres" and not o["is_partition"] for o in tables), "Unexpected table ownership/kind")
    columns = e["columns"]
    require(len(columns) == 171 and {c["table"] for c in columns} == set(TABLES), "Column inventory drift")
    require(len({(c["table"], c["column"]) for c in columns}) == 171, "Duplicate column evidence")
    require(all(not c["generated"] for c in columns), "Unexpected generated column")
    constraints = e["structure"]["constraints"]
    indexes = normalize_indexes(e["structure"]["indexes"], constraints)
    require(len(constraints) == 151 and all(c["validated"] for c in constraints), "Constraint contract drift")
    require(len(indexes) == 87 and all(i["valid"] and i["ready"] for i in indexes), "Index contract drift")
    require({kind: sum(c['type'] == kind for c in constraints) for kind in ('p', 'u', 'x')} ==
            {'p': 23, 'u': 23, 'x': 2}, 'Constraint-created index inventory drift')
    require(sum(i["constraint"] is None for i in indexes) == 39, "Standalone index inventory drift")
    sequences = [dict(s) for s in e["sequences"]]
    require(len(sequences) == 12, "Sequence inventory drift")
    lossless = {s["sequence"]: s for s in e["targeted"]["bigint_sequences"]}
    require(len(lossless) == 5, "Missing lossless bigint sequence evidence")
    for s in sequences:
        if s["type"] == "bigint":
            require(s["sequence"] in lossless, "Missing exact sequence settings")
            s.update(lossless[s["sequence"]])  # Earlier JSON maxima are rounded, never authoritative.
        require(s["owner"] == "postgres" and s["owned_by_schema"] == "public", "Sequence ownership drift")
        require(s["owned_by_column"] == "id" and not s["cycle"], "Unexpected sequence contract")
    functions = e["targeted"]["functions"]
    require(sorted(f["name"] for f in functions) == list(FUNCTIONS), "Function inventory drift")
    require(sorted(f["name"] for f in e["routines"]["routines"]) == list(FUNCTIONS), "Routine metadata disagreement")
    triggers = e["targeted"]["triggers"]
    require(len(triggers) == 4 and all(t["enabled"] == "O" for t in triggers), "Trigger contract drift")
    require({t["name"] for t in triggers} == {t["name"] for t in e["routines"]["triggers"]}, "Trigger inventory disagreement")
    require(not e["acl"]["explicit_column_acls"], "Unexpected explicit column ACL")
    require({(s["subsystem"], s["capacity_pool"], s["max_concurrency"]) for s in e["seeds"]} ==
            {("gemini", "gemini-default", 50), ("geocoding", "google-geocoding", 20)}, "Seed drift")
    flags = {t["table"]: t for t in e["rls"]["table_flags"] if t["schema"] == "public"}
    require(set(flags) == set(TABLES) and not any(t["rls_forced"] for t in flags.values()), "RLS inventory drift")
    require(sum(t["rls_enabled"] for t in flags.values()) == 13, "RLS enablement drift")
    for t in tables:
        require(t["rls_enabled"] == flags[t["name"]]["rls_enabled"], "RLS evidence disagreement")
    policies = e["rls"]["policies"]
    require(len(policies) == 1 and policies[0]["schema"] == "realtime" and
            policies[0]["table"] == "messages" and policies[0]["roles"] == ["authenticated"] and
            policies[0]["command"] == "SELECT" and policies[0]["check_expression"] is None,
            "Unexpected policy contract")
    names = ", ".join(literal(t) for t in TABLES)
    seqnames = ", ".join(literal(s["sequence"]) for s in sequences)
    fnnames = ", ".join(literal(f) for f in FUNCTIONS)
    out = ["""-- FCA CURRENT-STATE CHECKPOINT: 2026-09-30. FRESH ISOLATED SUPABASE ONLY.
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
    END IF;""",
        f"""    IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
               WHERE n.nspname='public' AND c.relname IN ({names}, {seqnames}))
       OR EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                  WHERE n.nspname='public' AND p.proname IN ({fnnames}))
       OR EXISTS (SELECT 1 FROM pg_policy WHERE polrelid=to_regclass('realtime.messages')
                  AND polname='family_members_receive_car_status') THEN
        RAISE EXCEPTION 'Existing FCA objects: checkpoint cannot upgrade or replace a database';
    END IF;
END
$checkpoint_guard$;"""]

    def settings(s):
        return (f"START WITH {s['start']} INCREMENT BY {s['increment']} MINVALUE {s['minimum']} "
                f"MAXVALUE {s['maximum']} CACHE {s['cache']} NO CYCLE")

    out.append("-- Phase 1: serial sequences, then all tables WITHOUT inter-table constraints.")
    for s in sequences:
        if not s["column_identity"]:
            require(s["dependency_type"] == "a", "Expected SERIAL ownership")
            out.append(f"CREATE SEQUENCE public.{ident(s['sequence'])} AS {s['type']} {settings(s)};")
    for table in TABLES:
        definitions = []
        for c in sorted((c for c in columns if c["table"] == table), key=lambda c: c["position"]):
            line = f"    {ident(c['column'])} {c['type']}"
            if c["collation"] is not None:
                line += " COLLATE " + c["collation"]
            if c["identity"]:
                require(c["identity"] == "d", "Unexpected identity mode")
                s = next(s for s in sequences if s["owned_by_table"] == table and s["owned_by_column"] == c["column"])
                require(s["dependency_type"] == "i", "Expected identity ownership")
                line += f" GENERATED BY DEFAULT AS IDENTITY (SEQUENCE NAME public.{ident(s['sequence'])} {settings(s)})"
            elif c["default_or_generation_expression"] is not None:
                line += " DEFAULT " + c["default_or_generation_expression"]
            if c["not_null"]:
                line += " NOT NULL"
            definitions.append(line)
        out.append(f"CREATE TABLE public.{ident(table)} (\n" + ",\n".join(definitions) + "\n);")
        out.append(f"ALTER TABLE public.{ident(table)} OWNER TO postgres;")
    for s in sequences:
        out.append(f"ALTER SEQUENCE public.{ident(s['sequence'])} OWNER TO postgres;")
        if not s["column_identity"]:
            out.append(f"ALTER SEQUENCE public.{ident(s['sequence'])} OWNED BY public.{ident(s['owned_by_table'])}.{ident(s['owned_by_column'])};")

    out.append("-- Phase 2: referenced keys/checks/exclusions BEFORE all foreign keys (including cycles).")
    for c in sorted(constraints, key=lambda c: (c["type"] == "f", c["table"], c["name"])):
        require(c["table"] in TABLES, "Unexpected constraint table")
        require(("DEFERRABLE" in c["definition"]) == c["deferrable"], "Deferrability disagreement")
        require(not c["initially_deferred"], "Unexpected deferred default")
        out.append(f"ALTER TABLE public.{ident(c['table'])} ADD CONSTRAINT {ident(c['name'])} {c['definition']};")
    for i in sorted(indexes, key=lambda i: i["name"]):
        if i["constraint"] is None:
            out.append(i["definition"] + ";")
        else:
            out.append("-- Constraint-backed index: " + i["definition"] + ";")

    out.append("-- Phase 3: exact captured functions, triggers and FCA receive policy.")
    for f in sorted(functions, key=lambda f: f["name"]):
        definition = f["definition"].replace("\r\n", "\n").strip()
        # Preflight forbids existing overloads; CREATE makes non-replacement explicit.
        out.append(definition.replace("CREATE OR REPLACE FUNCTION", "CREATE FUNCTION", 1) + ";")
        signature = f"public.{f['name']}({f['identity_arguments']})"
        out.append(f"ALTER FUNCTION {signature} OWNER TO postgres;")
    for t in sorted(triggers, key=lambda t: t["name"]):
        out.append(t["definition"] + ";")
        out.append(f"ALTER TABLE public.{ident(t['table'])} ENABLE TRIGGER {ident(t['name'])};")
    p = policies[0]
    out.append(f"CREATE POLICY {ident(p['name'])} ON realtime.messages AS {p['permissive']} FOR SELECT TO authenticated USING ({p['using_expression']});")

    out.append("-- Phase 4: captured RLS and explicit ACLs, independent of provider defaults.")
    acl_checks = []
    for table in TABLES:
        mode = "ENABLE" if flags[table]["rls_enabled"] else "DISABLE"
        out.extend([f"ALTER TABLE public.{ident(table)} {mode} ROW LEVEL SECURITY;",
                    f"ALTER TABLE public.{ident(table)} NO FORCE ROW LEVEL SECURITY;"])
    for r in e["acl"]["relations"]:
        if r["schema"] != "public":
            continue
        require(r["owner"] == "postgres" and r["kind"] in ("r", "S"), "Unexpected relation ACL")
        seq = r["kind"] == "S"
        expected = "{postgres=rwU/postgres,service_role=rwU/postgres}" if seq else "{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}"
        require(r["acl"] == expected, "Relation ACL differs from approved capture")
        kind = "SEQUENCE" if seq else "TABLE"
        target = f"public.{ident(r['name'])}"
        out.append(f"REVOKE ALL PRIVILEGES ON {kind} {target} FROM PUBLIC, anon, authenticated, postgres, service_role;")
        if not seq:
            colnames = ", ".join(ident(c["column"]) for c in columns if c["table"] == r["name"])
            out.append(f"REVOKE ALL PRIVILEGES ({colnames}) ON TABLE {target} FROM PUBLIC, anon, authenticated, postgres, service_role;")
        grants = "SELECT, UPDATE, USAGE" if seq else "SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN"
        out.append(f"GRANT {grants} ON {kind} {target} TO postgres, service_role;")
        acl_checks.append(f"(SELECT relacl FROM pg_class WHERE oid={literal(target)}::regclass)")
        acl_checks.append(expected)
    require(len(acl_checks) == 70, "Expected 35 relation ACLs")
    for f in sorted(e["acl"]["routine_acls"], key=lambda f: f["name"]):
        helper = f["name"] == "can_receive_car_status_topic"
        expected = "{postgres=X/postgres,anon=X/postgres,authenticated=X/postgres,service_role=X/postgres}" if helper else "{postgres=X/postgres,service_role=X/postgres}"
        require(f["acl"] == expected and f["owner"] == "postgres", "Unexpected function ACL")
        signature = f"public.{f['name']}({'text' if helper else ''})"
        out.append(f"REVOKE ALL PRIVILEGES ON FUNCTION {signature} FROM PUBLIC, anon, authenticated, postgres, service_role;")
        out.append(f"GRANT EXECUTE ON FUNCTION {signature} TO postgres, service_role" + (", anon, authenticated" if helper else "") + ";")
        acl_checks.extend([f"(SELECT proacl FROM pg_proc WHERE oid={literal(signature)}::regprocedure)", expected])
    # Exact final ACL checks also reject unexpected grants inherited from a different
    # fresh project's defaults. Do not silently retain privileges for extra roles.
    out.append("-- Fail transactionally if unexpected default grantees survived; ACL order is immaterial.")
    out.append("DO $acl_postcondition$\nDECLARE actual aclitem[]; expected aclitem[];\nBEGIN")
    for actual, expected in zip(acl_checks[::2], acl_checks[1::2]):
        out.append(f"    actual := {actual}; expected := {literal(expected)}::aclitem[];\n"
                   "    IF actual IS NULL OR NOT (actual @> expected AND actual <@ expected) THEN\n"
                   "        RAISE EXCEPTION 'Checkpoint ACL differs from captured backend-only contract';\n"
                   "    END IF;")
    out.append("END\n$acl_postcondition$;")
    out.append("-- Phase 5: only environment configuration; no Production application data.")
    for s in sorted(e["seeds"], key=lambda s: s["subsystem"]):
        out.append(f"INSERT INTO public.{s['subsystem']}_capacity_policies (capacity_pool, max_concurrency) VALUES ({literal(s['capacity_pool'])}, {s['max_concurrency']});")
    out.append("COMMIT;")
    return "\n\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()
    expected = render(load_evidence(args.evidence))
    actual = (ROOT / "current_schema.sql").read_text(encoding="utf-8")
    if actual != expected:
        print("".join(difflib.unified_diff(expected.splitlines(True), actual.splitlines(True),
                                         fromfile="captured contract", tofile="checkpoint")))
        raise SystemExit("FAIL: checkpoint differs from evidence")
    print("PASS: 23 tables / 171 columns / 151 constraints / 87 physical indexes (48 constraint-created + 39 standalone) / 12 sequences; "
          "5 functions / 4 triggers / 1 policy; RLS, ACLs, 2 seeds. STATIC ONLY; no SQL executed.")


if __name__ == "__main__":
    main()
