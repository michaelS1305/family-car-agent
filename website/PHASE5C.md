# Phase 5C — legacy frontend retirement

## Verification and classification

Inspected tracked references repository-wide using git grep, plus prior focused
runtime/build audit: .github/workflows, package manifests, Vite configuration,
README execution commands, backend imports, Android build/source and iOS checks.
No package workspace or Render/Docker configuration referencing web was found.

A: legacy React screens/routing/CSS, API client wrappers, Workbox source/config,
UI tests, public images and package/build files. Removed 108 tracked originals;
web/.gitignore and web/README.md are replaced with retirement-only information.
The generated web/dist was removed after verifying its absolute path.
B: backend services/contracts and native apps untouched. The legal document source
web/src/legal/legalDocuments.ts is retained because Android LegalCopy.kt explicitly
names it as its source. Existing shared branding outside web remains untouched.
C: Render's actual deployed version/headers, origin and cache contents are not
verified. Unknown registrations/caches are preserved. Ignored local dependencies
and .env.local remain, without reading credentials. iOS AUTHENTICATION.md's old
source references are historical, not build-time imports; it was not changed.

CI exception explicitly approved: .github/workflows/web.yml still runs in web.
It will fail until Phase 5D migrates it. No CI settings/workflow changes made.

## Verified legacy identity

Before deletion, web/dist/registerSW.js registered /sw.js with scope /.
web/vite.config.ts selected injectManifest, sw.ts and autoUpdate; root manifest
id/start_url were /. Source sw.ts used precacheAndRoute and a NavigationRoute
bound to index.html, skipWaiting and clientsClaim. Built Workbox cache name:
workbox-precache-v2-<registration.scope>, e.g. workbox-precache-v2-https://host/.
No custom runtime cache was configured in the inspected worker.

## Migration

website/public/sw.js is a temporary replacement at the exact old script URL.
Browser worker update requests can reach this even when the old navigation is
served from precache. A page-only cleanup cannot guarantee this.

The worker checks its own exact /sw.js URL and root scope. On install it requests
skipWaiting. On activation it considers only the exact precache-v2 root-origin
name, then requires cached index, registration script, original FCA logo, FCA icon
and manifest keys. The cached manifest must identify Family Car Agent with root
id/start_url. Only that positively fingerprinted cache is deleted. Unknown cache
versions, missing fingerprints or unreadable manifests are retained.

It unregisters its own verified registration only. It has no fetch or push handler,
no clients.claim and no forced navigation. Page startup asks update() only for
registrations whose root scope and all active/waiting/installing scripts match.
It never registers a worker for a new visitor. Errors do not block site loading.

No cookies, localStorage, sessionStorage or IndexedDB are cleared. Other caches
and registrations remain untouched. Repeated activation/helper runs are safe.
Open documents are intentionally not force-reloaded (to avoid losing form input).
Already displayed PWA content may remain until next navigation/reload. Offline
clients must reconnect and receive the update. Instant migration of every installed
client cannot be guaranteed from repository code. Cache access failures leave data
in place; the replacement still does not serve it.

## Deployment requirements (NOT applied)

On each original origin separately, serve the real website/dist/sw.js at /sw.js
with 200 and a JavaScript MIME type; never rewrite it to HTML, redirect it or cache
it immutably. Use Cache-Control: no-cache, max-age=0, must-revalidate on this path.
Keep it available throughout a migration observation window; no end date is assumed.
Root script location supplies root scope; do not broaden scope. Serve new page HTML
and assets normally, and verify the existing SPA/404 policy separately.

Before changing Render, verify deployed old worker URL/scope actually match the
local evidence. If different, stop and map that version rather than expanding cleanup.
Test first in Render Development with a previously installed PWA, an unrelated
cache/registration, offline/online transitions, repeated loads, navigation and a
form draft. Do not promote to main until Development and Phase 5D CI are approved.

## Local validation

Website tests include mocks executing the actual replacement worker and page helper:
exact identity, positive cache fingerprint, unrelated caches, foreign scope/script,
repeated execution, missing caches and unavailable browser APIs. Existing website
route/content/SEO/404 tests remain in the suite. Production build copies sw.js.
No isolated browser-profile migration test was performed; mocks do not establish
real browser update timing. No external requests, SMTP or database operations.
