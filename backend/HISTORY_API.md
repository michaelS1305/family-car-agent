# Shared vehicle usage History

`GET /api/car/history` uses the existing Bearer authentication and authenticated
family scope. It is shared by Web/PWA, Android and future clients.

## Optional query parameters

| Parameter | Contract |
| --- | --- |
| `limit` | Integer 1–50; default 50; completed sessions only. |
| `cursor` | UUID `session_ref` of the last returned completed session. Omit on the first page. |
| `vehicle_ref` | Canonical public vehicle UUID. |
| `member_ref` | Public member UUID, matching `/api/family` members. |
| `from_datetime` | Offset-aware ISO date-time, inclusive lower bound on `started_at`. |
| `to_datetime` | Offset-aware ISO date-time, inclusive upper bound on `started_at`. |

All filters combine with AND and apply only to completed usage. Encode query
parameters normally (in particular, percent-encode `+` in timezone offsets).
Naive/date-only/malformed timestamps, reversed ranges, invalid UUIDs and invalid
limits return HTTP 422. Times represent absolute instants; display timezone is
the client's responsibility. Responses retain offset-aware ISO timestamps.

## Additive response

Existing fields remain: `active_usage` (first active item or null),
`active_usages` (all active items), `recent_usage` (completed page).
Every item retains `name`, `started_at`, `vehicle_name`, `vehicle_ref`;
completed items also retain `ended_at`. Every item additionally has:

- `session_ref`: existing public session UUID, never the internal bigint ID.
- `member_ref`: `users.member_public_id`, as exposed by `/api/family`.

Top-level `has_more` is boolean. `next_cursor` is the last returned completed
item's `session_ref` when another row exists, otherwise null. Lookahead is one
row; active sessions never consume the completed page limit and are not filtered.
Existing capacity protection for active sessions remains unchanged.

## Ordering, isolation and refresh

Ordering remains `started_at DESC, id DESC`, including equal start timestamps.
The cursor is resolved only among completed sessions in the authenticated
family; its internal `(started_at, id)` tuple is used for a strict keyset bound.
Neither that tuple nor internal IDs are exposed in response items or cursors.
Missing, active and foreign-family cursors all return the same HTTP 422
`INVALID_HISTORY_CURSOR`; restart from the first page. Vehicle/member filters
are scoped to the same family and return an empty completed page for unknown or
foreign references, without a distinguishing existence lookup.

Keep filters unchanged while paging; reset the cursor when filters change.
This is not a frozen snapshot across requests. Reconciliation/deletion can alter
sessions or remove a cursor between requests. Clients should merge by
`session_ref` and restart on an unavailable cursor; new activity can be retrieved
by refreshing the first page. No usage/reconciliation semantics are changed.

`vehicle_ref` still links to the canonical Vehicle entity. This contract adds no
History-specific vehicle model, metadata, realtime transport or schema objects.
