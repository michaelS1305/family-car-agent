# Public contact endpoint — Phase 1

`POST /api/contact`, multipart, no FCA authentication. Fields: `name` (1–100
trimmed characters), `email` (single ASCII mailbox, <=254), `subject` (תקלה,
הצעה, חוות דעת), `description` (1–1000 trimmed Unicode code points),
`turnstile_token` (1–2048), and zero to five `attachments` parts. Duplicate or
unknown fields are rejected. No client-controlled recipients or headers.

## Configuration (server only)

Disabled unless `CONTACT_ENABLED=true`. Required:

- `CONTACT_SMTP_HOST`: account/datacenter-specific Zoho hostname.
- `CONTACT_SMTP_PORT`: 465 (implicit TLS) or 587 (mandatory STARTTLS).
- `CONTACT_SMTP_USERNAME`, `CONTACT_SMTP_PASSWORD`: authorized mailbox login;
  use an application password where required. Never put these in frontend env.
- `CONTACT_FROM_EMAIL`: fixed authorized mailbox/alias.
- `CONTACT_TO_EMAIL`: fixed recipient; intended destination is
  `support@familycaragent.com`. Use an approved test inbox in Development.
- `CONTACT_TURNSTILE_SECRET`: server-side secret.
- `CONTACT_SMTP_TIMEOUT`: socket timeout in seconds, default 10, range 1–30.
- `CONTACT_TURNSTILE_HOSTNAME`: optional exact Siteverify hostname match.
  Configure it for the intended website before public exposure.

Missing/invalid configuration disables this endpoint, not application startup.
There is no production bypass or test token accepted by application code.
Automated tests replace SMTP and Turnstile calls with mocks.

## Limits and validation

Decimal bytes: 5,000,000 per file, 10,000,000 combined, 10,100,000 request body,
14,000,000 serialized email. Request data is counted before multipart parsing,
spooled above 256KiB, with a 30-second upload deadline. Multipart permits five
files and five fields with an 8192-byte field cap. All temporary resources close
on completion/error. Tokens are verified after bounded multipart parsing (their
position in the form is arbitrary), before content inspection and MIME creation.

PNG, JPEG, WebP, HEIC and PDF require matching extension, declared MIME and
signature/structure. HEIF/sequence MIME types are not accepted. HEIC requires
HEVC still-image brands plus bounded metadata/item and media boxes; unsupported
BMFF layouts are conservatively rejected. These are format checks, NOT malware
scanning or full image/PDF decoding. No rendering, conversion or execution.
Treat attachments as untrusted when opening them in the support mailbox.

## Abuse protection / deployment prerequisites

Single-process Development limits: five admitted requests per peer IP per ten
minutes, 30 SMTP attempts globally per hour, four concurrent request handlers,
two concurrent SMTP calls. The IP table is capped at 4096 entries; limits reject
new clients when full rather than evicting active limits. All counters reset on
restart and are NOT distributed. Do not claim a Production-grade global quota
across workers or replicas; review this before scaling.

Only `request.client.host` is used. The endpoint does not read X-Forwarded-For.
Configure the ASGI server to trust only actual ingress proxies; never use a
wildcard trusted-proxy setting with a directly reachable server. Without trusted
forwarding all clients may share the proxy's quota. Existing server settings have
not been changed or verified by this patch.

Existing CORS must explicitly allow the website origin. CORS is not bot protection.
Render Free blocks SMTP ports: this phase cannot demonstrate real sending there.
Before real testing, verify paid hosting connectivity, Zoho authorized sender,
message-size/account policies and domain mail authentication. No infrastructure
changes are included here.

## Outcomes and privacy

Every response has `code` and a generated `request_id`. 200 `accepted` means SMTP
accepted the message, not inbox delivery. 422 invalid form/bot verification,
413 size limits, 415 unsupported attachment, 429 quota/concurrency with
`Retry-After`, 503 disabled/unavailable or `delivery_uncertain`.

No automatic retries. Connection loss during sending is uncertain, even if the
server may have accepted the message. A browser losing its response is likewise
uncertain. There is no persistent queue, request storage or exactly-once guarantee.
Do not automatically resubmit. SMTP socket timeouts apply to blocking operations;
they are not an end-to-end delivery guarantee. Sending runs in the threadpool.

Application logs contain only random request ID and fixed result category. Do
not enable HTTP/SMTP wire debugging or request-body logging in hosting tools.
No names, addresses, filenames, tokens, bodies or provider exceptions are logged.
Mail remains subject to Zoho mailbox retention even though FCA stores no request.

## Local checks

From `backend/`, using the project Python environment:

`python -m unittest tests.test_contact tests.test_main_identity tests.test_native_push_api`

Phase 2: website multipart submission, matching limits, Turnstile widget, loading
and honest accepted/uncertain/error states. Phase 3 (separate authorization):
synthetic Development mail, Reply-To, attachments, TLS and inbox/spam verification.
