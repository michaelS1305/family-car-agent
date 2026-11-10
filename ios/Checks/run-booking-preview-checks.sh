#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
out=$(mktemp -d "${TMPDIR:-/tmp}/fca-booking-preview.XXXXXX")
trap 'rm -rf "$out"' EXIT
"${SWIFT_BIN:-/home/micha/.local/share/swiftly/bin/swiftc}" -swift-version 6 -warnings-as-errors -D DEBUG \
 Sources/FamilyCarAgent/Booking/BookingPreviewCalendar.swift Checks/BookingPreviewChecks.swift -o "$out/checks"
"$out/checks"
