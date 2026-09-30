# FCA authoritative database checkpoint — 2026-09-30

**FRESH, ISOLATED SUPABASE ONLY. NEVER APPLY TO EXISTING PRODUCTION.**

This is the authoritative current-state starting point for a new FCA database,
prepared from the operator's reconciled 2026-09-30 Production metadata, including
the final `13-targeted-definitions.json`. It is not an upgrade or a cleanup.
**No SQL has been executed as part of preparation. Runtime clean-rebuild validation
is still required in a separately authorized isolated Dev project.**

## Boundary and files

- `current_schema.sql`: one guarded transaction, encoding current state directly.
- `validate_checkpoint.py`: standard-library-only, read-only static comparison
  against the local dated JSON capture. It never connects to a database or writes
  files. It deliberately rejects changes to the frozen capture contract.
- Focused tests: repository-root `tests/test_database_checkpoint.py`.

The older `../../schema_baseline/` and `../../manual_migrations/` remain historical
evidence. All effects through `2026092701` are incorporated here. **Do not run the
older baseline or replay those migrations after this checkpoint.** Future schema
changes follow this boundary as separately reviewed migrations; record their
execution per environment without inferring execution from equivalent state.

Raw evidence remains ignored under `../../schema_audit/2026-09-30-production/`.
It is operator-local metadata, not a distributed runtime dependency. The complete
SQL and focused structural tests are tracked; evidence comparison additionally
requires those local JSON files. The actual ACL filename is `08-privilege.json`.

## Represented contract

23 public tables, 171 visible columns, 151 named constraints, 88 indexes (49
constraint-backed, 39 standalone), 12 owned sequences, five functions, four
triggers and one FCA policy on provider-owned `realtime.messages`.

Tables are created before keys and CHECK/exclusion constraints; all FKs are added
after referenced keys. This preserves the families/users cycle, self-referencing
VehicleEvent projection FK and composite authority bindings without weakening them.
The three deferrable constraints remain initially immediate. No application rows
or sequence counters are copied. The historical dropped column slot in `users`
is not recreated; visible column order and names/types remain intact.

Identity sequences are explicitly named/configured. The five bigint maxima use
the lossless string values from capture 13, overriding only the rounded sequence
settings from capture 05. The exact maximum is `9223372036854775807`.

Legacy `car_events`, `users.telegram_chat_id` and Join `address_attempts` remain.
`onboarding_sessions` is absent. No legacy car-events broadcast trigger is created.
The accepted VehicleEvent INSERT and surviving-family member DELETE triggers are
the current invalidation wiring. Guards and helper bodies preserve captured
behavior; converting deparsed CREATE OR REPLACE to CREATE prevents replacement.

## Security and provider prerequisites

Use a separately approved empty Supabase environment, PostgreSQL **17+**, with
`postgres` as executor/owner. PostgreSQL 17 is required to reproduce `MAINTAIN`.
The operator must explicitly opt in with session setting
`fca.allow_empty_checkpoint = '2026-09-30'` before the transaction. This is an
accident guard, not proof of environment identity. Verify the selected project
independently; **never opt in on existing Production**.

Supabase must already supply:

- `public`, `auth`, `realtime` schemas and roles `postgres`, `anon`,
  `authenticated`, `service_role`;
- `auth.users`, `auth.uid()`, `realtime.messages`, `realtime.topic()`,
  `realtime.send(jsonb,text,text,boolean)`;
- provider-managed Realtime RLS, runtime/publication/partition management and
  schema USAGE needed by authenticated Realtime and backend roles;
- backend roles with the normal captured BYPASSRLS capabilities; browser roles
  must not have superuser/BYPASSRLS or inherited backend authority.

FCA needs built-in UUID/range/GiST support and PL/pgSQL. No extension is installed:
the captured pgcrypto, uuid-ossp, pg_stat_statements and Vault are environment
inventory, not additional dependencies of this SQL. In particular, no btree_gist
dependency is introduced. No provider roles, tables, partitions, publications,
schema ACLs or provider default privileges are recreated or modified.

All FCA objects are postgres-owned. RLS matches the capture exactly: 13 tables
enabled, 10 disabled, none forced; no public-table policies. This includes five
newer table flags absent from their historical creation SQL. Disabled RLS does
not grant access: PUBLIC/anon/authenticated table, column and sequence privileges
are explicitly revoked. Backend table ACLs include MAINTAIN; sequence ACLs include
SELECT/UPDATE/USAGE. Only the receive helper permits browser-role EXECUTE; all
four trigger functions are backend-only. No grants use WITH GRANT OPTION.

Known Supabase default grants are cleared before explicit grants. Final exact ACL
postconditions reject unexpected additional default grantees rather than silently
retaining them. Object collisions and any failure roll back the transaction. Do
not use IF NOT EXISTS, relax guards or rerun historical SQL to overcome a failure.
On a nonstandard provider environment, stop and review its prerequisites/ACLs.

## Only configuration is seeded

- `gemini_capacity_policies`: `gemini-default`, concurrency **50**.
- `geocoding_capacity_policies`: `google-geocoding`, concurrency **20**.

All other FCA tables start empty, including code history. No Production developer/
test data, Auth users, registrations, bindings or location records are imported.
Policy timestamps are generated locally from their captured defaults.

## Offline validation now

From repository root:

```text
python -B -m unittest discover -s tests -p test_database_checkpoint.py
python -B supabase/bootstrap/2026-09-30/validate_checkpoint.py
git diff --check
```

The validator accepts `--evidence PATH` for an explicitly selected copy of the
same dated JSON capture. It compares complete deterministic SQL, not only counts.
It is not a PostgreSQL parser, execution test or proof of clean rebuild success.

## Required later, with separate authorization

Create isolated Dev with provider prerequisites and Dev-only configuration. Apply
this checkpoint once; compare catalogs, ACL/effective privileges, RLS, sequences,
guards, policy and trigger definitions against this contract. Verify fail-closed
rerun/rollback behavior, both capacity seeds, backend flows and private Realtime
authorization/cross-family denial. Test future migrations in Dev, then apply the
same approved artifacts to Production through a controlled rollout. Production
data need not be preserved for this fresh-environment bootstrap, but no Production
reset is authorized or performed by this checkpoint.
