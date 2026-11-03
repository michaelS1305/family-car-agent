#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
out=$(mktemp -d "${TMPDIR:-/tmp}/fca-queue-checks.XXXXXX")
trap 'rm -rf "$out"' EXIT
flags=(-swift-version 6 -warnings-as-errors)
if [[ "$(uname -s)" == Linux ]]; then
  include="${SQLITE_INCLUDE_DIR:-/usr/include}"
  test -f "$include/sqlite3.h" || { echo 'SQLite development headers required (SQLITE_INCLUDE_DIR)'; exit 1; }
  printf 'module SQLite3 [system] { header "%s/sqlite3.h" export * }\n' "$include" > "$out/module.modulemap"
  flags+=(-I "$out" -Xlinker -l:libsqlite3.so.0)
else
  flags+=(-lsqlite3)
fi
"${SWIFT_BIN:-$(command -v swiftc)}" "${flags[@]}" \
 Sources/FamilyCarAgent/Config/AppEnvironment.swift Sources/FamilyCarAgent/Auth/AuthCore.swift \
 Sources/FamilyCarAgent/Chat/ChatCore.swift Sources/FamilyCarAgent/Auth/AuthAPI.swift \
 Sources/FamilyCarAgent/Family/FamilyCore.swift Sources/FamilyCarAgent/Vehicles/VehiclesCore.swift \
 Sources/FamilyCarAgent/History/HistoryCore.swift Sources/FamilyCarAgent/OfflineEvents/VehicleEventQueue.swift \
 Checks/VehicleEventQueueChecks.swift -o "$out/checks"
"$out/checks"
