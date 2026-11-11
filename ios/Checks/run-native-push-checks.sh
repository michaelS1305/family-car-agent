#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
swift_bin="${SWIFT_BIN:-/home/micha/.local/share/swiftly/bin/swiftc}"
check_dir=$(mktemp -d /tmp/fca-ios-push.XXXXXX)
"$swift_bin" -swift-version 6 -warnings-as-errors Sources/FamilyCarAgent/Push/NativePushState.swift Checks/NativePushChecks.swift -o "$check_dir/push-check"
"$check_dir/push-check"
python3 Checks/test-native-push.py
python3 Checks/test-app-intents-poc.py
