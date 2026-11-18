
# Native Push P2 — APPLIED AND VERIFIED IN DEV

The migration was successfully applied to Supabase Dev on 2026-10-18.
Live postflight checks passed: four tables created with RLS enabled,
no effective table or column privileges for anon/authenticated/service_role,
no RLS policies or publication exposure, 60 valid constraints and
22 valid indexes.

Supabase Prod has NOT been migrated.
Native Push backend and Android integration are NOT implemented yet.


## Authority and scope

Operator verified Render **Dev** uses postgres (superuser false, BYPASSRLS true).
This does not verify Production or the executor selected in SQL Editor.
Repository FK reference: bootstrap/2026-09-30/current_schema.sql:
users integer PK; vehicle_events unique(event_id,user_id,vehicle_id,family_id).
The migration checks actual live column types/non-nullability and non-deferrable
valid unique targets before creating anything. Unexpected objects fail closed.
PostgreSQL 15+ is required (publication namespace catalog). No extension/sequence
is installed; future server code supplies random UUIDs.

Four tables only: installation ownership; pending proof-of-control; vehicle
outbox; per-installation delivery. No application, Companion, Web Push, business
table, Realtime or global default privilege changes. No existing rows modified.

## Security

postgres owns the tables and is the verified runtime role. No additional runtime
GRANT is required. RLS enabled without policies provides defense in depth only:
postgres ownership/BYPASSRLS bypasses it. API ownership checks remain mandatory.
Explicit table AND column REVOKE covers PUBLIC/anon/authenticated/service_role.
Any additional table grants inherited from creation defaults are revoked on only
these four objects. Effective browser/service_role privileges cause rollback.
No SECURITY DEFINER functions or runtime triggers. No broad GRANTs.
All-table/public-schema publications cause preflight failure rather than silently
publishing confidential token material or changing existing publications.

## Schema invariants and runtime obligations

- Installation active token uniqueness is project-scoped. No unique candidate
  token index: an unverified registration must not squat on a victim's token.
- Composite installation/owner FKs prevent cross-owner challenges/deliveries.
- Tokens/nonces are bytea envelopes, never intended plaintext. SQL cannot prove
  ciphertext is encrypted; authenticated encryption and key management come later.
- Positive generations are checked. Monotonic increments, immutable ownership,
  server-selected project/platform, device limits and CAS require future runtime
  transactions; no UPDATE endpoint or ownership-transfer behavior exists here.
- Pending challenges require material and a schedule; terminal states erase
  material and leases. Consumed tombstones retain activated generation. Creation
  starts generation 1; successful activation increments it (including first use).
  Pending challenges may have a lease; the claim query must exclude live leases.
- Delivery leases and acceptance/schedule combinations are checked. Provider
  acceptance is NOT phone delivery. Future code must fence completion by lease
  token, recheck identity/generation and enforce cross-table expiry.
- The composite event FK validates authoritative actor/vehicle/family identity.
  SQL cannot prove copied occurred_at equals the source, that admission is fast,
  or event kind matches the effect. Future atomic producer must derive those from
  source, not client input. TTL CHECK fixes expires_at to occurred_at + 5 minutes.
- Source event deletion cascades to outbox and deliveries. Existing account
  deletion removes owned vehicle events before users; installation user deletion
  cascades to challenges/deliveries. No reverse cascade deletes business data.
- Installation generation is a snapshot, NOT an FK to the current generation:
  rotation must cancel stale work rather than block rotation or rewrite history.
- Recipient family membership and driver exclusion must be rechecked before send.
- Retention, retry limits, clock-skew policy, ambiguous acceptance, event producer,
  worker, FCM and registration API are intentionally not implemented.

## Operator checklist — separate execution approval required

1. Confirm Dev project, backup/schema snapshot and quiet execution window. Do not
   copy credentials into repository or reports. Prod requires independent audit.
2. Run read-only verification SQL in Dev. Save only metadata output. Confirm
   postgres/BYPASSRLS, four tables absent, required FK targets exactly present,
   validated/ready indexes, no automatic public/all-table publication. Review role
   memberships/default grants and existing deletion FK definitions. SQL Editor
   identity alone does not prove Render identity; the operator's check is required.
3. Review this migration and obtain explicit execution approval. No startup runner.
4. Execute the complete transaction once as postgres; stop on any error. Do not
   use IF NOT EXISTS, weaken guards, or continue a partially failed script.
5. Run verification SQL again. Four postgres-owned RLS-enabled tables, no policies,
   no native publication membership, no browser/service_role effective privileges,
   all constraints validated and indexes valid/ready. Compare legacy schema/ACL
   snapshot: push_subscriptions and its sequence must be unchanged.
6. Before runtime activation, test on disposable PostgreSQL: valid inserts; CHECK
   rejection including NULL combinations; duplicate active tokens/pending challenges;
   foreign-owner FK rejection; source/user cascades; rollback; concurrent claims.
   Static review is not a substitute for these tests.

## Rollback and compatibility

No runtime exists yet, so migration alone enables no notifications. Keep future
Native Push feature flags disabled until separately approved. Roll back runtime
by disabling Native Push and retaining tables/data; no automatic DROP rollback.
Schema reruns deliberately fail. No Web Push migration rollback is required.

## Git / CI

Per-flavor real google-services.json stays local and ignored, including Dev.
Service-account filename patterns are ignored; arbitrary names still require
human review. No credential contents were inspected. Ignore rules do not untrack
previously tracked files. Before Google Services plugin integration, agree on CI
config injection and Prod-disabled build behavior. Never substitute Dev for Prod,
create fake config, or package the backend private key in Android.
