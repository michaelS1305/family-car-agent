#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
swift_bin="${SWIFT_BIN:-/home/micha/.local/share/swiftly/bin/swiftc}"
check_dir=$(mktemp -d /tmp/fca-ios-push.XXXXXX)
"$swift_bin" -swift-version 6 -warnings-as-errors Sources/FamilyCarAgent/Push/NativePushState.swift Checks/NativePushChecks.swift -o "$check_dir/push-check"
"$check_dir/push-check"
"$swift_bin" -swift-version 6 -warnings-as-errors \
  Sources/FamilyCarAgent/Config/AppEnvironment.swift Sources/FamilyCarAgent/Auth/AuthCore.swift \
  Sources/FamilyCarAgent/Vehicles/VehiclesCore.swift Sources/FamilyCarAgent/Family/FamilyCore.swift \
  Sources/FamilyCarAgent/Chat/ChatCore.swift Sources/FamilyCarAgent/History/HistoryCore.swift \
  Sources/FamilyCarAgent/Auth/AuthAPI.swift Sources/FamilyCarAgent/Push/NativePushRegistration.swift \
  Checks/NativePushRegistrationChecks.swift -o "$check_dir/registration-check"
"$check_dir/registration-check"
python3 Checks/test-native-push.py
python3 Checks/test-app-intents-poc.py

python3 Checks/test-production-push.py
for mode in development production; do
  flags=(-Onone)
  if [[ "$mode" == production ]]; then flags=(-Onone -D FCA_PRODUCTION); fi
  "$swift_bin" -swift-version 6 -warnings-as-errors "${flags[@]}" \
    Sources/FamilyCarAgent/Config/AppEnvironment.swift Checks/NativePushEnvironmentChecks.swift -o "$check_dir/environment-$mode"
  "$check_dir/environment-$mode"
  "$swift_bin" -swift-version 6 -warnings-as-errors "${flags[@]}" \
    Sources/FamilyCarAgent/Config/AppEnvironment.swift Sources/FamilyCarAgent/Auth/AuthCore.swift \
    Sources/FamilyCarAgent/Vehicles/VehiclesCore.swift Sources/FamilyCarAgent/Family/FamilyCore.swift \
    Sources/FamilyCarAgent/Chat/ChatCore.swift Sources/FamilyCarAgent/History/HistoryCore.swift \
    Sources/FamilyCarAgent/Auth/AuthAPI.swift Sources/FamilyCarAgent/Push/NativePushRegistration.swift \
    Sources/FamilyCarAgent/Auth/SessionComposition.swift Checks/SessionCompositionChecks.swift -o "$check_dir/composition-$mode"
  "$check_dir/composition-$mode"
done
