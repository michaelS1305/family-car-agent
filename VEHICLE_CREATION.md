# Vehicle/device creation bounds (MC-SEC-002)

Internal-only services; no public endpoint, native ingestion activation, Android
or frontend integration. Clients must generate a UUID4 once per logical action
and pass `request_id` to `create_vehicle` / `register_device`. No key means a
422 `INVALID_CREATION_REQUEST_ID`; no server-generated fallback exists.

## Atomicity and bounded state

Creation retains identity fence -> family advisory -> family row locking and
membership revalidation. It uses admission's transaction-local 1s lock/2s
statement limits and 5s checked deadline, preserving stricter caller settings.
Network/commit latency is not a hard wall-clock guarantee. Errors roll back;
caller-owned outer transactions retain final commit ownership.

Within that transaction: validate payload, recover existing key, check quotas,
insert resource and (devices) increment family lifetime usage. All workers share
PostgreSQL locks. Unique constraints arbitrate resource keys as defense in depth.
No other member's identity lock is acquired. Deletion/retirement/revocation retain
their existing lock order and behavior.

Vehicle keys are scoped to family, with original creator checked; device keys
are scoped to owner. Payload SHA-256 fingerprints preserve original-request
comparison across vehicle renames. Conflicting payload/creator fails with
`CREATION_IDEMPOTENCY_CONFLICT`. Retries return the same opaque resource reference
with its **current** metadata/retirement/revocation state, never reactivating it.
Retry recovery precedes quota checks. No internal IDs are added to public views.
Separate users/families may independently use the same random key.

There is no request ledger and failures allocate no idempotency state. Each
successful resource has one UUID and one 32-byte fingerprint. Resource quotas
therefore also bound retry metadata; it survives restarts and independent DB
connections. Account deletion continues deleting personal devices and their keys.
Deleted identities cannot retry through a stale JWT. Family vehicle history is
retained until family deletion; creator deletion nulls its existing creator FK.

## Central policy (`vehicle_creation_policy.py`)

| Resource / scope | Active | Lifetime |
|---|---:|---:|
| Vehicles / family | 10 | 50 |
| Devices / user | 5 | 30 |
| Devices / family | 20 | 100 |

Vehicle/user-device counts use indexed LIMIT 50/30 pages, including retired or
revoked rows. No hot-path unrestricted COUNT is introduced. Family active devices
use a users/devices join with LIMIT 20; statement timeout also bounds DB work.
Revocation/retirement changes only active usage, never lifetime usage.

`families.device_identities_created` is the one necessary cumulative counter:
account deletion removes devices, so remaining rows cannot preserve family
lifetime consumption. Successful registration increments it in the same locked
transaction as insertion; rollback undoes both. Deleting members does not reduce
it. Last-member family deletion removes it with the family. Existing application
membership is not transferable; any future transfer feature must explicitly
preserve this accounting contract. Backend-authorized SQL outside these services
must not insert/delete resources to reset quotas.

Stable 409 errors: `VEHICLE_ACTIVE_LIMIT`, `VEHICLE_LIFETIME_LIMIT`,
`DEVICE_USER_ACTIVE_LIMIT`, `DEVICE_USER_LIFETIME_LIMIT`,
`DEVICE_FAMILY_ACTIVE_LIMIT`, `DEVICE_FAMILY_LIFETIME_LIMIT`, and
`CREATION_IDEMPOTENCY_CONFLICT`. Infrastructure timeouts remain exceptions and
retryable; no terminal receipt is created.

## Operator migration — prepared, NOT applied by this task

Run the **complete unchanged contents** of
`supabase/manual_migrations/2026092501_vehicle_creation_bounds.sql` as postgres.
This adds resource-local nullable metadata, paired-value checks, two scoped UNIQUE
constraints, and the nonnegative family counter. No ACL/RLS/function/trigger or
MC-SEC-001 index changes. Pre-feature rows retain NULL keys; refs are unchanged.
Existing rows over quota remain intact, but new creation is refused.

Read-only preflight:

```sql
SELECT current_user = 'postgres' AS correct_role;
SELECT table_name,column_name,data_type
FROM information_schema.columns
WHERE table_schema='public' AND
 ((table_name='families' AND column_name='id') OR
  (table_name='users' AND column_name='family_id') OR
  (table_name='vehicles' AND column_name IN ('family_id','created_by_user_id')) OR
  (table_name='registered_devices' AND column_name='user_id'));
SELECT count(*) AS conflicting_columns FROM information_schema.columns
WHERE table_schema='public' AND
 ((table_name='families' AND column_name='device_identities_created') OR
  (table_name IN ('vehicles','registered_devices') AND
   column_name IN ('creation_request_id','creation_fingerprint')));
SELECT count(*) AS unmapped_devices
FROM public.registered_devices d JOIN public.users u ON u.id=d.user_id
WHERE u.family_id IS NULL;
```

Expected true; five integer columns; zero conflicts; zero unmapped devices.
The migration repeats compatibility/conflict checks and fails atomically for
unmapped devices. A lock/statement timeout rolls back; retry in a quiet window.

Backfill counts all currently persisted devices (including revoked) by family.
**Historical devices already physically deleted before this feature cannot be
reconstructed from the current schema.** The baseline is surviving pre-feature
identities plus every post-cutover assignment; do not claim a recovered historical
total. If an operator requires accounting for known pre-cutover deletions, resolve
that historical usage before activation rather than fabricate values.

Verification immediately after migration, before enabling new writers:

```sql
SELECT table_name,column_name,data_type,is_nullable,column_default
FROM information_schema.columns WHERE table_schema='public' AND
 ((table_name='families' AND column_name='device_identities_created') OR
  (table_name IN ('vehicles','registered_devices') AND
   column_name IN ('creation_request_id','creation_fingerprint')))
ORDER BY table_name,column_name;
SELECT conname,pg_get_constraintdef(oid)
FROM pg_constraint WHERE conname IN
 ('vehicles_creation_metadata_check','vehicles_creation_request_key',
  'devices_creation_metadata_check','devices_creation_request_key',
  'families_device_identities_created_check') ORDER BY conname;
SELECT count(*) AS mismatches FROM public.families f
WHERE f.device_identities_created <> (
 SELECT count(*) FROM public.registered_devices d JOIN public.users u ON u.id=d.user_id
 WHERE u.family_id=f.id);
```

Expected five columns: nullable UUID/bytea pairs on the resources, NOT NULL bigint
counter with default 0; five named constraints (paired null-or-32-byte metadata,
family/key UNIQUE, owner/key UNIQUE, counter >=0); zero backfill mismatches.
After member deletion, counter > surviving rows is expected, not drift.

**Cutover:** pause all lifecycle creation writers, apply migration, verify, deploy
new backend/callers supplying stable UUID4 keys, then resume. Old workers must not
create resources after backfill. Use a quiet window: table locks block writes.
No whole-PWA downtime is intrinsically necessary while these functions remain
internal-only. Reruns fail closed. Failed migration rolls back completely.
After success, do not revert to old creation writers or drop metadata/counters:
disable creation while investigating a rollback; keep durable keys and quotas.

## Separate activation gates

Existing Gemini/geocoding/CarPlay limiters have different ownership/accounting
and are not reused or coupled to resource creation. Family serialization and
finite waits bound concurrent internal work, but are not a public request-rate
limit. Before exposing creation APIs, add appropriate ingress abuse controls.
MC-SEC-003, public native event-ingestion rate/concurrency controls, and client
integration remain separate. No frontend or native ingestion route is added.
