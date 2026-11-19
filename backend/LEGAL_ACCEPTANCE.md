# Onboarding legal acceptance

Both completion endpoints require `legal_accepted: true` (a JSON boolean),
`terms_version: "1.2"` and `privacy_version: "1.2"`. Missing/invalid values or
extra fields, including client identity/time, are rejected by request validation.
The identity comes from the authenticated JWT; PostgreSQL supplies the time.

The existing create/join transaction inserts `legal_acceptances` before consuming
the address confirmation/join session. Any persistence failure rolls back the
onboarding transaction. The composite key and `ON CONFLICT DO NOTHING` retain the
first timestamp. Existing mapped-user and client bootstrap recovery behavior is
unchanged; recovery does not insert an acknowledgment. There is no backfill.

The table belongs to the trusted postgres Backend connection, has RLS enabled,
and grants no access to public/anon/authenticated clients. Deleting the Auth user
cascades to acceptance records. This follows the existing account deletion
worker's hard Auth deletion; application-user deletion alone does not remove them.

## Manual rollout (separate owner authorization required)

1. Apply `supabase/manual_migrations/2026111901_legal_acceptances.sql` to
   Development, then deploy the updated Development Backend and native clients.
2. Verify registration and failure recovery in Development.
3. Apply the same migration separately to Production, verify schema/permissions,
   then deploy the updated Backend before distributing updated native clients.
4. Verify the real authenticated create/join flows after rollout.

Old clients cannot complete onboarding against the updated Backend because they
do not send acknowledgment. Updated clients must not use the old Backend (create
rejects extra fields; old join can ignore them). Coordinate the rollout; there is
deliberately no legacy-client exemption. Existing registered-user login is unchanged.

The migration is one-time and fails on an existing/conflicting table. Do not
remove the table when rolling back application code: preserve recorded evidence.
No environment selection or credentials are introduced; each Backend uses its
existing environment-specific database connection.

## Focused local checks

From `backend/`, use the existing Python environment:

```text
python -m unittest tests.test_legal_acceptance tests.test_family_models tests.test_family_creation_service tests.test_join_family_service tests.test_main_identity tests.test_database_atomic_creation
```

Opt-in PostgreSQL tests use `GEMINI_TEST_DATABASE_URL`, restricted to loopback
and database `test_gemini`. They create disposable schemas, not Supabase objects:

```text
python -m unittest tests.test_legal_acceptance_postgres tests.test_family_address_confirmations tests.test_family_code_allocator tests.test_account_deletion
```

Android: `gradlew.bat :app:testDevDebugUnitTest --tests il.fca.companion.OnboardingModelTest --tests il.fca.companion.OnboardingFailureTest --offline`.
iOS: `bash ios/Checks/run-auth-checks.sh` (existing Swift tooling).
