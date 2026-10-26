#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
swift_bin="${SWIFT_BIN:-/home/micha/.local/share/swiftly/bin/swiftc}"
check_dir=$(mktemp -d /tmp/fca-ios-auth.XXXXXX)
"$swift_bin" -swift-version 6 -warnings-as-errors \
  Sources/FamilyCarAgent/Config/AppEnvironment.swift \
  Sources/FamilyCarAgent/Auth/AuthCore.swift \
  Sources/FamilyCarAgent/Auth/AuthAPI.swift \
  Sources/FamilyCarAgent/Auth/OnboardingValidation.swift \
  Sources/FamilyCarAgent/Auth/EntryModel.swift \
  Checks/EntryChecks.swift Checks/EntryUIChecks.swift Checks/AuthCheck.swift -o "$check_dir/auth-check"
"$check_dir/auth-check"
"$swift_bin" -swift-version 6 -warnings-as-errors \
  Sources/FamilyCarAgent/Config/AppEnvironment.swift Checks/AppEnvironmentCheck.swift -o "$check_dir/environment-check"
"$check_dir/environment-check"
if [[ "$(uname -s)" == "Darwin" ]]; then
  "$swift_bin" -swift-version 6 -warnings-as-errors \
    Sources/FamilyCarAgent/Auth/AuthCore.swift Sources/FamilyCarAgent/Auth/AuthCrypto.swift \
    Checks/CryptoCheck.swift -o "$check_dir/crypto-check"
  "$check_dir/crypto-check"
else
  echo 'NOT RUN: CryptoKit/Security runtime checks require macOS or iPhone.'
fi
