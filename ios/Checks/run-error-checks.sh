#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
out=$(mktemp -d "${TMPDIR:-/tmp}/fca-error-checks.XXXXXX")
trap 'rm -rf "$out"' EXIT
"${SWIFT_BIN:-/home/micha/.local/share/swiftly/bin/swiftc}" -swift-version 6 -warnings-as-errors \
  Sources/FamilyCarAgent/Errors/AppErrorPresentation.swift Checks/ErrorPresentationChecks.swift -o "$out/checks"
"$out/checks"
python3 Checks/check-error-ui.py
