# Android account actions and chat following

Settings reads the actual email through the existing authenticated Supabase
`GET /auth/v1/user` endpoint. The returned subject must match the captured owner.
Email is memory-only, unavailable on failure, and masked/cleared on owner or family
change. It is not inferred from a name or an unverified JWT and is never logged.

Account deletion reuses `/api/account/deletion[/preview]` and its durable server
worker. There is no Android-only delete contract, new migration, or cascade rule.
The confirmation explains irreversible personal deletion, automatic management
transfer, and deletion of family data when the user is the last member. The preview
is informational: these rules are evaluated under the existing server locks.
Other members and their family data are not removed by an ordinary member leaving.

The Activity-owned dialog survives recomposition/navigation. POST requires a
successful preview and explicit confirmation. An uncertain response cannot be
dismissed or automatically resubmitted, even if a subsequent GET reports
`not_requested` (the POST could still be in flight). Only read-only status checking
or the existing sign-out/Companion cleanup is offered. Accepted work is not described
as completed until the server reports `completed`. Users can sign out while the
durable server worker finishes. Local push is invalidated at submission and ordinary
resume cannot reactivate it during a protected deletion. Server deletion gates deny
normal API access and push refresh/delivery; hard Auth deletion and FK cleanup are
handled by the existing worker.

After process loss, `/api/me`'s exact `403 ACCOUNT_UNAVAILABLE` response invokes
existing sign-out cleanup and shows a fixed explanation. Generic failures do not
clear sessions. The pending dialog itself is memory-only. An unexpired signed token
can query self-only deletion status, but cannot access normal data after the server
gate closes. Already-delivered notifications cannot be recalled.

No live cloud validation, Auth deletion, deployment, or device installation is
performed by the automated local tests. Dev device QA must exercise confirmation,
cancel, network loss after POST, rotation, restart, sign-out, email availability,
creator/member/last-member cases, and server Auth-worker completion with disposable
test accounts. Existing server migrations and configured Auth admin credentials are
prerequisites; no new credentials are introduced here.

Chat retains its current scroll container and IME/layout handling. Initial measured
history and accepted own sends follow the end; incoming content follows only while
the reader remains within 48dp of the end. User scrolling away disables following.
History prepends are distinguished from appends; there is currently no pagination
endpoint/control. The existing non-admin Vehicles empty state already explains that
only the family manager can add cars; its permission checks remain unchanged.
