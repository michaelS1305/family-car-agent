# FCA iOS Dev authentication

The repository's `ios/` directory is canonical. The existing WSL run script
copies it to `/home/micha/FamilyCarAgent` and runs `xtool dev run`; that command
builds **and installs/runs** on a device. Neither the script nor the build copy
is the source of truth.

`Sources/FamilyCarAgent/Config/AppEnvironment.swift` defines immutable, public
Dev configuration. Authentication uses `try AppEnvironment.current()`:
unknown or missing bundle identifiers throw instead of falling back to Dev.
There is deliberately no Production case or runtime environment override.
Debug/Release optimization does not change the environment. The static URL
literals are checked by the standalone checks below; their force unwraps do
not parse external input.

The app now has a minimal authentication/onboarding development screen. See
[AUTHENTICATION.md](AUTHENTICATION.md) for the audited flow, security boundaries,
required manual Dev configuration, test coverage and physical QA checklist.
The public Dev publishable key in `Config/Info.Dev.plist` is intentionally empty:
authentication fails closed until the operator supplies it. No private key is needed.

SwiftPM recursively discovers Swift files in `Sources/FamilyCarAgent` because
the existing target has no custom path, source list, or exclusions. `Checks/`
is outside that target; it does not add a product or dependency. The manifest,
xtool bundle ID, deployment target, and existing run workflow are unchanged.
`xtool.yml` now references the Dev Info.plist and Apple entitlement. No dependency
or second session manager was introduced.

## Verify from Windows PowerShell

Open the existing WSL distribution:

```powershell
wsl -d Ubuntu-24.04
```

Then run these commands in its shell:

```bash
cd /mnt/c/Projects/family-bot-agent/ios
swift --version
swift package describe
bash Checks/run-auth-checks.sh
xtool dev build
python3 Checks/check-built-config.py
git diff --check
```

`xtool dev build` without `--sign` builds the iOS app but does not sign or install
it. The existing Swift/Darwin SDK must already be installed. These checks do not
contact FCA/Supabase and do not validate OAuth or physical-device behavior.
For the user's existing signed device workflow, run `/home/micha/fca-ios-run.sh`
only when installation is intended.

Signing keys belong outside the repository. `ios/.gitignore` additionally
excludes common Apple keys, profiles, archives and app artifacts. Ignore rules
do not remove already tracked files or detect credentials under arbitrary names;
review staged files before committing. Only the Dev PUBLIC publishable key belongs
in the application configuration. Never include server/admin or Apple private keys.
