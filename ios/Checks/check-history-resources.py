"""Offline integration/resource checks, not a rendering test."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
source = root / "Sources/FamilyCarAgent"
screen = (source / "History/HistoryScreen.swift").read_text(encoding="utf-8")
core = (source / "Vehicles/VehiclesCore.swift").read_text(encoding="utf-8")
assets = source / "Resources/AppAssets"
paths = {"icons/archive/history_icon.png", "icons/archive/single_car_icon.png"}
paths.update(re.findall(r'"(vehicles/[^"\n]+\.png)"', core))
for relative in paths:
    data = (assets / relative).read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n"), relative
assert len(paths) == 7
assert 'HistoryScreen(entry: entry' in (source / "AuthenticatedAppShell.swift").read_text(encoding="utf-8")
assert 'NavigationStack' not in screen
assert 'maxHeight: .infinity' not in screen
assert 'LazyVStack' in screen and 'VehiclesHeader(back: back)' in screen
assert '.rightToLeft' in screen
assert '.copy("Resources/AppAssets")' in (root / "Package.swift").read_text(encoding="utf-8")
print("PASS: History integration and 7 original PNG assets (static checks; no device rendering claim)")
