# Local contact setup — PowerShell 7

Run from the repository root:
`pwsh -NoProfile -File .\tools\contact\start-local.ps1`

Requires existing .venv Python 3.11+, backend dependencies, Node, pnpm and website
dependencies. Installs nothing. Prompts for masked primary Zoho mailbox, App
Password, private Turnstile key, and public site key. Fixed SMTP is
smtppro.zoho.com:465 implicit TLS; sender/recipient support@familycaragent.com.
Owner must verify alias authorization separately.

Only backend receives secrets. Environments are allowlisted. No database or
workers load. Forwarded headers are ignored. Open http://localhost:5173/contact
(not 127.0.0.1). Backend binds 127.0.0.1:8000. Vite's existing dev entry is invoked
directly via Node with strict fixed port for reliable process-tree cleanup.

Ctrl+C stops child process trees in finally. Force-killing the launcher cannot
guarantee cleanup. No in-flight mail draining is promised; do not submit in this
phase. Environment secrets necessarily exist in memory; clearing references is
not guaranteed memory zeroization. No raw child logs are displayed or saved.
Do not enable transcripts/environment dumps or put secrets in VITE variables.
Vite retains its normal .env loading behavior; backend does not load dotenv.

Synthetic startup check (GET/OPTIONS only, no browser or external services):
`pwsh -NoProfile -File .\tools\contact\start-local.ps1 -SelfTest`

Real Turnstile initialization requires owner keys and manual browser inspection.
SMTP connectivity is not tested. Next separately authorized E2E: inspect widget,
submit one synthetic message, verify acceptance, inbox/spam, Reply-To and files.
Never automatically retry an uncertain result. This launcher changes no cloud
settings and writes no credential files.

## Filtered local diagnostics

The local entry point enables only the dedicated Contact diagnostic logger at
INFO. Production entry points do not enable this handler. Launcher stdout is
filtered with an anchored allowlist and 256-character line cap; stderr and all
other stdout are discarded. No raw exceptions/provider bodies are forwarded.

Match `request_id` from the form to `CONTACT_DIAG` in the launcher console:
configuration_invalid; turnstile_communication_failed; turnstile_rejected;
smtp_connect_failed; smtp_auth_failed; smtp_rejected; unexpected_failure;
delivery_uncertain; request_incomplete. The stage distinguishes the operation.
SMTP connectivity errors during login remain connection failures, not proof of
invalid credentials. smtp_rejected does not establish that the alias alone is
wrong. delivery_uncertain must never trigger an automatic resend.

Restart the launcher to load diagnostics. Previous discarded logs cannot be
recovered. Tests: `./tools/contact/test-diagnostics.ps1` and, from backend,
`../.venv/Scripts/python.exe -B -m unittest tests.test_contact tests.test_contact_local tests.test_contact_diagnostics`.
All diagnostic tests use mocks; no real mail or provider request is performed.
