# MC-SEC-003: one vehicle-state authority

Prepared implementation; activation requires `2026092502_carplay_vehicle_authority.sql`
and coordinated external Shortcut updates. No hosted Shortcut was changed/tested
by this repository work. This is not iOS multi-vehicle identification.

## Contract and binding

An authenticated member sets their own temporary detector binding with
`PATCH /api/carplay/vehicle`, bearer JWT, body `{"vehicle_ref":"<opaque UUID>"}`.
The server derives the user/family, verifies a non-retired same-family vehicle,
and stores one binding. Extra fields are rejected. This does not limit native
devices/users to one vehicle. Missing/stale/retired binding fails closed. No
automatic first-car/latest-car selection exists. Binding setup is an API operation,
not a redesigned onboarding screen; the rollout operator must arrange it before use.

External CONNECT: `POST /car/connect` with `shortcut_token` and `acquisition_id`.
External DISCONNECT: `POST /car/disconnect` with the same `shortcut_token`,
`acquisition_id`, and existing numeric `latitude`/`longitude`.
Generate a fresh opaque UUID4 once per logical CarPlay acquisition, persist it
locally across its connect/disconnect automations, and reuse it for every retry.
Do not generate a fresh acquisition on HTTP timeout/retry. If the association is
lost, do not substitute the newest acquisition; fail safely. No vehicle, family,
user, device sequence or event timestamp comes from these requests.

Server UUID5 operation IDs are scoped by authenticated Auth identity, UUID4
acquisition and action. Server PostgreSQL time is persisted once and reused on
retry. `source=legacy_shortcut` legitimately has no native device/sequence;
native validation and sequencing are unchanged. RETURN names the exact TAKE ID,
never a latest TAKE. Rebinding cannot redirect an old acquisition's RETURN.
The engine may alias redundant TAKEs to one session; the adapter rejects an old
Shortcut RETURN while a newer Shortcut acquisition aliases that active session.
Missing TAKE fails closed; a later CONNECT does not revive a rejected RETURN.

The existing 500m home RETURN gate and CarPlay abuse admission remain. Valid
disconnect retries now also pass rate admission; all mutation/replay decisions
are made under the authoritative family lock, not a stale pre-lock driver read.
No address/coordinates/token/acquisition are added to logs or vehicle evidence.

## Authority, serialization, side effects

Shared deletion identity fence -> family advisory lock -> family row -> binding/
vehicle validation -> existing bounded admission/checkpoint/reconciliation ->
vehicle_events + vehicle_driver_sessions, one transaction. Rollback includes the
receipt/projection. Native device sequence rules are unchanged; MC001 bounds and
MC002 creation rules remain. DB/deadline failures roll back and permit stable-ID retry.

Status uses open vehicle sessions. History displays all bounded active sessions
separately from the latest 50 ended sessions, with opaque vehicle refs/names and
Asia/Jerusalem display. AI status enumerates vehicles instead of guessing one car.
Legacy SQL mutation helpers fail closed. `car_events` is dormant except existing
initialization and privacy deletion of attributable rows; no backfill is performed.

Push is dispatched only after a committed newly opened/returned Shortcut effect;
duplicates and already-ended effects do not push. It remains best effort: a crash
after commit and before push can lose a notification, not replay a mutation.
Realtime uses the existing empty family invalidation from accepted vehicle-event
inserts, not legacy inserts. One committed accepted operation produces one
invalidation; receipt retries do not insert. User deletion additionally invalidates
the surviving family after session cleanup, without a fake physical RETURN.
Topic authorization and receiver function grants are unchanged.

## Controlled activation (operator only)

1. Confirm foundation, MC001 index and MC002 prerequisites; inspect current
   trigger/function and backend role. This migration expects postgres and fails
   transactionally on missing/conflicting objects. It is not a rerunnable repair.
2. Pause Shortcut and native/lifecycle writers and drain old backend workers.
   Do not run old/new authorities together; old code must never resume writes.
3. Operator applies the prepared migration once in the controlled window. It
   adds bindings/lookup index, moves the broadcast trigger and adds deletion
   invalidation. It does not import legacy test history or change topic policies.
4. Deploy matching backend/frontend, configure concrete per-user bindings, and
   update hosted Shortcuts to the acquisition contract before resuming traffic.
5. Verify browser roles cannot access bindings, old car_events trigger is absent,
   new triggers exist, two-user handover/stale disconnect/retry are safe, and
   status/History/push/Realtime use one authority. Test external automations on iPhone.
6. On failure pause traffic; do not roll back to dual/legacy writers. Diagnose or
   forward-fix under the quiet window. Do not delete family/member/configuration data.

Future proper iOS identification, Android/public native ingestion and native
aggregate ingress controls are separate work. No production SQL is run by this task.
