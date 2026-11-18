# iOS CI

`.github/workflows/ios.yml` validates the canonical `ios/` package on macOS 15
with Xcode 26.2. It uses only checkout and installed Apple/Python tools, with
read-only repository permissions and no signing credentials or deployments.

All pushes and pull requests targeting develop/main run the stable
`iOS validation` job. There are deliberately no path filters: a required check
must not remain pending because an unrelated file changed. Concurrency cancels
superseded runs. Actual GitHub branch protection is not defined by workflow YAML;
select this check only after its first successful runner execution.

Checks:
- SwiftPM dependency resolution (currently no external package dependencies).
- Existing standalone auth, route and environment executables, plus macOS-only
  CryptoKit/Security checks. There is no SwiftPM test target; `swift test` is not used.
- Google and Apple diagnostic checks in DEBUG and Release; synthetic secret-output
  and Release binary marker guards. These are not a complete Release app audit.
- DEBUG auth/route checks and canonical entry image/legal/resource validation.
- Xcode compilation of the Swift package for generic iOS Simulator, signing disabled.
  This compiles UIKit/SwiftUI and SwiftPM resource accessors; it does not launch an app.

The package advertises macOS but its UIKit imports prevent a normal host
`swift build`; use an iOS destination. No xtool, Linux SDK, Assets.car processing,
provisioning, provider calls or physical-device tests are part of this CI.

Local checks: `SWIFT_BIN=/path/to/swiftc bash ios/Checks/run-ci-checks.sh`.
Linux can run the portable subset; the existing script explicitly skips Apple
crypto runtime checks there. Xcode compilation requires the macOS runner.

## First-push prerequisites and limitations

The canonical ios directory is currently untracked. Include the complete reviewed
package, Checks and referenced EntryAssets in the eventual commit, after a secrets
review. CI cannot validate files left only on a workstation.

The WSL Dev package currently also has AppAsset.swift and Resources/AppAssets,
uses a different resource manifest and resource-check script, and no longer matches
the canonical excluded PDF catalog. Authentication sources match. No synchronization
was performed for CI. Resolve this asset-workstream divergence separately before
claiming CI covers the entire WSL application. The workflow builds exactly Git's
canonical package, not the WSL working copy.

The first GitHub run must verify Xcode's package scheme discovery and Simulator
compilation; these cannot be executed on the Windows/Linux host. A green local
portable check is not evidence of a successful Apple build. Keep Xcode selection
explicit and update it deliberately when runner image support changes.
