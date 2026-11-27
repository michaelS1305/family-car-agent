# Persistent-reference deletion recovery regression

The individual lookup selects by persistent reference only, with return-data,
return-attributes and one-match controls. Service/account/environment checks happen
on the returned record before credentials are used. Enumeration remains scoped to
the existing non-synchronizable environment service. No stored format, operation ID,
secret, accessibility or service name changes; no migration or reset is needed.

`run-account-deletion-checks.sh` runs the actual macOS Keychain/SQLite orchestration,
then separately attempts Data Protection Keychain mode. Only missing entitlement
(-34018) at the initial disposable probe is reported as NOT RUN. All other probe
errors and all failures after a successful probe fail the suite. No fallback is
reported as Data Protection success. The unsigned macOS runner may lack the
required provisioned entitlements. Xcode compilation is not runtime verification.
HTTP and the background daemon are composition fakes; storage is real. Explicit
storage failure injection and returned-attribute validation tests supplement it.

Coverage: exact production query keys; zero/one/multiple records; enumeration and
individual read errors; service/account/environment mismatch; old-format submitted
record restart with absent JWT and identical operation/secret; 401/500/malformed
responses preserving records; authoritative completion followed by durable cleanup.

Physical acceptance (owner, after approved merge/build): install the corrected
Development IPA over the existing app with the same bundle/signing identity. Do not
uninstall, log out, reset storage or initiate another deletion. Press status check;
verify the existing operation is confirmed and cleanup finishes. Do not capture
Authorization headers, secrets or Keychain contents. Confirm another account and
Production remain untouched. This acceptance remains required even if CI is green.
