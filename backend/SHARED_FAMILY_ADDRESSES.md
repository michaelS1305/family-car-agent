# Shared family addresses and unambiguous joining

Local implementation only; no live migration, deployment, commit or publication.

## Behavior and API compatibility
Four geographic uniqueness checks were removed from create/address-update service
and transaction paths. Independent families may share names, addresses and
coordinates. Family identity remains the primary key plus a unique invitation
code, not a location. Confirmation ownership, expiry, one-time use, geocoding,
legal acceptance, allocation, locks and rollback remain unchanged.

Join address verification checks existence of a matching name within the existing
50m policy but never selects a family. It retains the submitted normalized family
name, server-geocoded coordinates and server timestamps. A unique code selects a
family; that SAME family must match both name and verified location. Completion
locks and revalidates the selected family, fresh evidence and current identity,
then inserts membership, records legal acceptance and deletes the join session in
one transaction. Code rotation continues to invalidate code-verified sessions.

The exact/canonical name matching policy is retained for each selected identity.
A stale geocoder response cannot overwrite a newer join-session context. Network
geocoding stays outside database locks. Existing identity fence and global
family-operation advisory lock order are preserved; family rows are locked before
final decisions. No vehicle/admission/projection/location rules are modified.

Existing mobile recovery is used: expired/missing evidence yields the existing
409 INVALID_JOIN_STEP. Android OnboardingModel.perform and iOS EntryModel.next
fetch join/start, which commits an address-step reset. Completion rejects stale
name/location similarly. Reverification does not clear attempts. Only the existing
15-minute failed-attempt lockout expiration resets those counters.

No endpoints, response keys or screens are changed. Persisted evidence, candidate
IDs and selected family ID are excluded from public session responses. The
existing address-preview response still returns the location the caller submitted
for verification; it never returns a family's stored coordinates or proof fields.

## Additive migration
Full SQL: ../supabase/manual_migrations/2026112601_join_location_verification.sql

Adds four nullable fields to pwa_join_sessions: verified_latitude,
verified_longitude, location_verified_at, location_verification_expires_at.
All are either NULL or present. Coordinate bounds reject infinities/NaN; times
must be finite and exactly 15 minutes apart. A single server clock sample creates
the timestamps. Validity is tested with clock_timestamp after lock acquisition,
and again after the selected-family lock before verification/completion.

Existing rows remain unchanged with NULL evidence. No grants, owners, RLS policies
or family data are modified. New fields inherit the existing Backend-only access
boundary. Tests verify RLS/ACL preservation and denied anon/authenticated reads.

## Expiration, retention and cleanup
Evidence expires after 15 minutes regardless of failed-attempt lockout. Expiration
never grants membership or resets attempts. Legacy sessions must reverify; never
infer their evidence from a family's mutable coordinates. Starting/resuming clears
invalid evidence and identity without clearing counters. Name/address edits and
lockout clear evidence. Completed sessions are deleted atomically. Auth deletion
retains its existing cascade semantics.

join/start also clears at most 100 expired proofs per request, using the expiry
index and FOR UPDATE SKIP LOCKED. It clears address display fields and selected
identity, preserves counters and active lockouts, and retains the session shell.
This is activity-driven cleanup, not a scheduled hard retention guarantee: dormant
expired proofs may remain until subsequent traffic. They are never usable after
expiry and are never exposed through session responses. No worker/cron was added.

## Deployment order and rollback
1. Owner reviews SQL and verifies the actual target schema/access policies.
2. Apply additive migration separately to each environment, before new Backend.
   Old Backend accepts nullable extra columns; existing sessions are preserved.
3. Deploy the new Backend and retire old instances. Do not claim shared-address
   support during mixed-version operation: old code still rejects shared homes
   and does not maintain the new evidence lifecycle. Mobile releases are not needed.
4. Verify independent creation/join and existing client expiry recovery in Dev,
   then repeat the approved checks after separately authorized Production release.

Rollback: keep additive columns/index; never drop family rows, memberships or
history. Restoring old Backend restores its old shared-address/join limitations.
Do not return to a mixed old/new fleet or later reuse evidence touched by an old
Backend without explicit join-session invalidation/reverification planning.
No rollback or deployment is performed by this task.

## Local verification
Final combined run: 244 passed, 0 failed, 0 skipped (62 real PostgreSQL tests;
182 unit/API/mock checks). Python syntax and git diff --check passed.
- 19 new real PostgreSQL join tests: actual migration, legacy preservation,
  ACL/RLS, exact TTL/constraints, duplicate names/coordinates, unrelated codes,
  expiry, counters, lockout, revalidation, concurrent verification/completion,
  replay, rollback, code rotation, identity fencing, stale geocoder responses,
  bounded cleanup, concurrent callbacks and expiry between session loading and cleanup.
  join/start reloads its response after cleanup, preserving the reset flag and counters.
- 15 real shared-home native isolation tests (including inherited regressions):
  vehicles, devices, bindings, events, sessions, independent vehicle state, RETURN
  causality/sequence/500m rule and actual Realtime authorization SQL predicate.
- Existing PostgreSQL address/token tests (15), code allocator/rotation tests (9),
  legal acceptance tests (3), and join/account-deletion race (1).
- Unit/API/mock regression suites for services, identity, family isolation,
  notifications, mobile recovery contract and transactional SQL shape.
- PostgreSQL 17 loopback test_gemini only; migrations adapted to disposable test
  schemas. No Supabase connection or live data was used.

Local tests do not verify live RLS, hosted Realtime delivery, actual notifications
or physical Android/iOS onboarding. Mobile recovery is checked against repository
code and contracts, not a newly installed app. Native RETURN source is unchanged.
