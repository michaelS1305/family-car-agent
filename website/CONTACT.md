# Contact form — frontend integration

Build-time public configuration:

- `VITE_CONTACT_API_BASE_URL`: backend base URL, without `/api/contact`.
  HTTPS required, except HTTP loopback (`localhost`, `127.0.0.1`, `[::1]`).
- `VITE_TURNSTILE_SITE_KEY`: public site key for the website hostname.

Missing configuration disables submission and does not load Cloudflare. No SMTP
credentials or Turnstile secret belong in Vite variables. No production URL or
real key is included. Once configured, visiting Contact loads the real Turnstile
script; use mocks/interception for local tests, not real configuration.

The form sends multipart POST `/api/contact`, credentials omitted, no redirects,
and no manually supplied Content-Type. The five fields are `name`, `email`,
`subject`, `description`, `turnstile_token`; files repeat `attachments`.
Only HTTP 200 with `code: accepted` clears the draft/files. It means SMTP
acceptance, not inbox delivery. Timeout (90 seconds), network loss or malformed
responses are uncertain, never automatically retried. Each attempt consumes and
resets the verification token. The form is frozen while submitting.

Limits use decimal MB: five nonempty files, 5,000,000 bytes each, 10,000,000 total.
PNG/JPEG/WebP/HEIC/PDF require the exact MIME accepted by the backend. Empty MIME,
HEIF and sequence types are rejected rather than silently relabeled. Content
signatures are authoritatively checked by the backend, not trusted from the UI.
Text limits count Unicode code points, matching Python; email follows the
backend's conservative ASCII-mailbox validation.

## Existing backend limitations (not changed here)

- Validation responses contain general codes, not field-specific error details.
  Local field errors are shown inline; server validation remains a form message.
- Cross-origin CORS currently does not expose `Retry-After`. Readable headers are
  honored (seconds or HTTP date); when absent/hidden use the server's conservative
  maximum quota window, 3601 seconds. A separate approved backend change to expose
  this header would allow the precise shorter wait across origins.
- CORS must allow the website origin. Do not enable credentials.
- Render Free blocks SMTP; this frontend does not resolve that hosting limitation.

No persistent draft, account session, automatic resubmission or delivery guarantee
is introduced. Navigation away discards this component's local draft/state.

## Validation and next stage

From `website/`: `pnpm test`, `pnpm typecheck`, `pnpm build`.
Tests mock fetch and the Turnstile adapter; they never call Zoho or Cloudflare.
For browser testing with configured values, intercept both the Turnstile script
and contact requests before opening the page. Do not use real credentials.

Separate authorization is required for real Development integration: configure
public site key/API URL, server secret and expected hostname, CORS, SMTP-capable
hosting and an approved test mailbox. Verify widget accessibility/expiry, uploads,
SMTP acceptance, actual receipt and Reply-To. No such integration was performed
as part of this local patch.
