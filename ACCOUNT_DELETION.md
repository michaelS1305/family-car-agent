# Account deletion

The self-only API uses verified Supabase JWT subjects, never browser-selected IDs:

- `GET /api/account/deletion/preview`: `consequence` is `personal`,
  `management_transferred`, or `family_deleted`.
- `POST /api/account/deletion`: exact body
  `{"confirmation":"DELETE_MY_ACCOUNT"}` (extra fields rejected). HTTP 202
  returns `status` (`draining`, `auth_pending`, or already `completed`).
- `GET /api/account/deletion`: those statuses, or `not_requested`.

Confirmation inserts the durable job under an exclusive identity advisory lock.
Normal authenticated access checks both Auth existence and absence of a job.
Writes and provider admission take a shared identity lock and recheck the gate
inside their transaction, before other operation locks. Shortcut requests use
the same gate. Stale JWTs cannot recreate an account after Auth deletion.

Every Uvicorn worker runs a recovery pass at startup and approximately every five
seconds. A pass atomically schedules at most ten due jobs sixty seconds ahead;
crashes leave them retryable. Cleanup is serialized by identity, then the existing
family-creation lock, sorted/deduplicated Chat/CarPlay keys, request locks, and the
reservation-family lock. DB lock waits are bounded. No provider/Auth HTTP call
holds a DB connection or transaction. Shutdown stops claiming new work; an abrupt
shutdown leaves a retryable durable job.

Cleanup waits for active/uncertain Gemini and geocoding permits. It locks permit
rows before rechecking expiry to respect concurrent uncertainty extensions. Once
the identity is gated, model continuations cannot mutate/finalize or admit another
call. Chat rows need not wait for an otherwise idle processing lease to expire:
their writes are fenced and no live provider permit may remain. Permit finish
remains allowed so in-flight calls can release/retain capacity normally.

Application data cleanup and `auth_pending` commit atomically. Creator succession
uses the lowest other member ID. Last-member cleanup deletes dependent family
data/Join state before detaching/deleting the family and user in one transaction.
Global capacity policies and `family_code_history` are never deleted.

If the departing user is the current active driver, a null-user, empty-name
`state_reset` car event prevents older unmatched Connects resurfacing. It is a
logical FCA state barrier, not a physical return/disconnect, and is omitted from
the usage-event tools. History does not pair sessions across the barrier. Legacy
null-user events are not matched/deleted by name. Last-family deletion removes
all family events as part of deleting that family.

Auth hard deletion uses HTTPS Admin HTTP with `should_soft_delete=false`, explicit
timeouts, redirects disabled and environment proxies disabled. Only a subsequent
authoritative `auth.users` absence check removes the job—not a 2xx/404 from an
arbitrary proxy. Lost responses, configuration errors and provider failures leave
the identity gated and retryable. Logs contain only constant stage categories.
There is no permanent completed-job record. A later OAuth login is a new identity,
never reconnected by name or email.

## Controlled cutover (not performed by implementation/tests)

1. Verify the reviewed deployment and backup/recovery plan. Pause normal API
   traffic and drain **all old workers**; old workers do not enforce deletion gates
   or understand logical state barriers.
2. Manually apply the already prepared `2026091603_account_deletion_jobs.sql` as
   postgres, and verify it. No other schema migration is introduced here.
3. Configure backend-only `SUPABASE_SERVICE_ROLE_KEY`, alongside the existing
   `SUPABASE_URL` for the same project. Keep `RUN_DB_INIT=false`. Never put the
   Admin secret in frontend/Vite configuration or logs.
4. Start only the matching new backend workers; then release the new frontend.
   Reopen traffic after smoke checks of ordinary/creator/last-member deletion,
   stale JWT rejection, and recovery after an interrupted Auth request.
5. Do not roll back to ungated workers while jobs or `state_reset` events exist.
   Auth/config failures require operational repair; do not remove pending jobs to
   restore access. This is irreversible hard deletion, not a recoverable soft delete.

Supabase Storage ownership can prevent Auth deletion. FCA currently stores no
per-user Storage objects. If external integrations create such objects, repair
that condition through an explicitly reviewed operational procedure; do not
silently broaden this cleanup to unrelated Supabase data.

## Local verification

Use the existing virtual environment and `python -m unittest discover -s tests`.
Set `GEMINI_TEST_DATABASE_URL` only to the disposable localhost `test_gemini`
database for real PostgreSQL tests. Tests create/drop random isolated schemas,
never apply production migrations, and stub Auth Admin HTTP. No live keys needed.
