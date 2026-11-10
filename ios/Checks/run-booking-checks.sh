#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
out=$(mktemp -d "${TMPDIR:-/tmp}/fca-booking-checks.XXXXXX")
trap 'rm -rf "$out"' EXIT
"${SWIFT_BIN:-/home/micha/.local/share/swiftly/bin/swiftc}" -swift-version 6 -warnings-as-errors \
 Sources/FamilyCarAgent/Config/AppEnvironment.swift Sources/FamilyCarAgent/Auth/AuthAPI.swift \
 Sources/FamilyCarAgent/Auth/AuthCore.swift Sources/FamilyCarAgent/Chat/ChatCore.swift \
 Sources/FamilyCarAgent/Family/FamilyCore.swift Sources/FamilyCarAgent/Vehicles/VehiclesCore.swift \
 Sources/FamilyCarAgent/History/HistoryCore.swift Sources/FamilyCarAgent/Booking/BookingPreviewCalendar.swift \
 Sources/FamilyCarAgent/Booking/BookingCore.swift Sources/FamilyCarAgent/Booking/BookingModel.swift \
 Checks/BookingChecks.swift -o "$out/checks"
"$out/checks"
