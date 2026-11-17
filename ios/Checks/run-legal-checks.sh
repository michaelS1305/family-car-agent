#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
swift_bin="${SWIFT_BIN:-/home/micha/.local/share/swiftly/bin/swiftc}"
check_dir=$(mktemp -d /tmp/fca-ios-legal.XXXXXX)
"$swift_bin" -swift-version 6 -warnings-as-errors Sources/FamilyCarAgent/EntryLegalDocument.swift \
  Sources/FamilyCarAgent/Auth/OnboardingValidation.swift Checks/LegalLinkCheck.swift -o "$check_dir/legal-check"
"$check_dir/legal-check"
python3 Checks/check-legal-support.py
python3 Checks/check-entry-resources.py
python3 Checks/check-settings-ui.py
python3 Checks/check-appearance-ui.py
"$swift_bin" -frontend -parse Sources/FamilyCarAgent/EntryLegalDocument.swift \
  Sources/FamilyCarAgent/EntryScreens.swift Sources/FamilyCarAgent/OnboardingScreens.swift \
  Sources/FamilyCarAgent/Settings/SettingsScreen.swift
