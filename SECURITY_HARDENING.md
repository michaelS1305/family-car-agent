# Remaining security hardening

No database schema/migration change. Existing JWT identity, deletion gates,
family isolation and Chat request replay remain authoritative.

## Push destinations and work bounds

Registration and each send accept HTTPS, default port only, no credentials,
query/fragment, ambiguous host syntax or escaped paths. Supported destinations:

- one DNS label under `push.apple.com` (for example `web.push.apple.com`);
- `fcm.googleapis.com`, `/wp/` or `/fcm/send/` paths;
- `updates.push.services.mozilla.com`, `/wpush/v1/` or `/wpush/v2/` paths.

Only ASCII provider token paths are accepted. This is deliberately not a generic
HTTPS fetcher; new browser/provider formats require review before allowlisting.
No runtime DNS names come from arbitrary users. Provider DNS/TLS remain trusted.

Sources checked for endpoint formats:
[Apple Web Push](https://developer.apple.com/documentation/usernotifications/sending-web-push-notifications-in-web-apps-and-browsers),
[Chromium FCM constants](https://chromium.googlesource.com/chromium/src/+/refs/tags/141.0.7390.94/components/push_messaging/push_messaging_constants.cc),
[Mozilla endpoint format](https://bugzilla.mozilla.org/show_bug.cgi?id=1486010).
Installed pywebpush 2.5.0 delegates to `requests_session.post`; FCA supplies a
validating Session with redirects disabled and environment proxies disabled.
Web Push encryption/VAPID stay in pywebpush. Invalid legacy rows are skipped,
never fetched. No legacy rows are bulk-deleted.

Five stored subscriptions per user allow phone/tablet/desktop use while bounding
growth. The existing user row serializes count+insert in PostgreSQL. Own-endpoint
updates still work at capacity. Expired/legacy rows count conservatively until
removed; failed delivery's existing 404/410 snapshot cleanup remains unchanged.
Delete/re-register churn can still cause authenticated DB work, but cannot grow
the user's row count beyond five; this is not a new request-rate limiter.

Dispatch selects at most five devices per member and 50 total, first device per
member before extra devices, with per-event hashed ordering to avoid permanently
privileging the same member. Actor/family/expiry filtering is preserved. A ten-second
admission budget stops starting additional sends; the last started call may finish
later. The existing five-second requests timeout is an inactivity timeout, NOT a
hard total deadline. Work/count is bounded, but no hard wall-clock SLA is claimed.

## JWT keys and logging

Each worker has one initialized resolver for its configured Supabase source,
thread-serialized refresh, five-second network timeout, five-minute key-set TTL,
and thirty-second refresh cooldown after success or failure. No per-attacker-kid
cache exists. Rotation can wait up to the cooldown; expired keys fail closed on
outage. JWT signature, ES256, issuer, audience, expiry, subject and role checks
remain unchanged. Each worker's outbound amplification is bounded independently;
this is not a fleet-wide PostgreSQL rate limit. Provider failures become generic
503s; invalid/unknown signing keys become 401s.

Chat exception logging never stringifies provider exceptions. Only allowlisted
stage/class, integer HTTP-range code, configured model and existing request
correlation fields remain. Metadata/logging errors cannot mask processing errors.

## Logout and local Push generation

IndexedDB stores one installation record: revision, enabled flag, subscription
digest and hashed account discriminator. No subscription keys or bearer tokens
are persisted there. The payload carries SHA-256 of endpoint/newline/p256dh/newline/auth,
not user/family IDs. The worker requires an enabled matching digest to display.

Explicit logout commits retirement before best-effort cleanup (three-second
network wait). Web Locks serialize display with retirement; existing visible
notifications are closed where supported. Activation uses a revision ticket so
late work cannot undo retirement. After retirement/account switch it requires a
fresh subscription, rejects reused retired keys, and enables only after backend
registration. Delayed cleanup targets the captured old subscription, not the new
one. Subscription lifecycle operations also share a separate browser lock; a
superseded activation checks its ticket before touching the subscription. Removal
accepts an optional generation digest and compares it under a PostgreSQL row lock,
so delayed cleanup cannot delete a rekeyed same-endpoint registration. Old clients
without that optional field keep their existing owner-scoped removal contract.
Missing/unreadable local state suppresses notifications. If retirement cannot
be persisted, logout does not falsely claim that local privacy was established.

[WebKit supports Web Locks across workers/windows](https://webkit.org/blog/12445/new-webkit-features-in-safari-15-4/),
predating installed-PWA Web Push. Real-device offline/logout/account-switch smoke
testing remains required. Browsers may revoke subscriptions after suppressed
user-visible-only pushes; explicit reactivation creates a fresh subscription.

Cutover: old installed workers cannot enforce this new rule retroactively.
Deploy the matching backend and frontend/worker together under a controlled Push
pause, allow clients to update, then explicitly reactivate Push. The new worker
fails closed for old payloads/no local generation; existing installations must
reactivate. Do not claim old, unopened installations have adopted the protection.
No deployment or configuration changes are performed by this repository patch.

Pending Chat storage retains normal request-id recovery, but explicit logout
retires only the departing account's writer and removes its sessionStorage entry.
Delayed callbacks cannot repopulate it. Unrelated keys are not cleared.
