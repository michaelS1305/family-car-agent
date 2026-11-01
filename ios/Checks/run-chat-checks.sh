#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
swift_bin="${SWIFT_BIN:-/home/micha/.local/share/swiftly/bin/swiftc}"
out=$(mktemp -d "${TMPDIR:-/tmp}/fca-chat-checks.XXXXXX")
trap 'rm -rf "$out"' EXIT
"$swift_bin" -swift-version 6 -warnings-as-errors \
  Sources/FamilyCarAgent/Auth/AuthCore.swift \
  Sources/FamilyCarAgent/Chat/ChatCore.swift \
  Sources/FamilyCarAgent/Chat/ChatModel.swift Checks/ChatChecks.swift -o "$out/chat-checks"
"$out/chat-checks"
