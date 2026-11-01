"""Static integration/asset checks; no claim of actual SwiftUI rendering."""
from pathlib import Path
import hashlib
import struct
import sys

root = Path(__file__).resolve().parents[1]
source = root / "Sources/FamilyCarAgent"
core = (source / "Vehicles/VehiclesCore.swift").read_text(encoding="utf-8")
view = (source / "Vehicles/VehiclesScreen.swift").read_text(encoding="utf-8")
add = (source / "Vehicles/AddVehicleScreen.swift").read_text(encoding="utf-8")
shell = (source / "AuthenticatedAppShell.swift").read_text(encoding="utf-8")
assert "VehiclesScreen(model: vehicles" in shell and "destination == .vehicles" in shell
assert "if !path.contains(.vehicles) { vehicles.stop() }" in shell
assert "vehicles.stop(); navigation.synchronize(identity)" in shell
assert "if !keyboardVisible && navigation.isRoot" in shell
assert "NavigationStack" not in view + add and "Form {" not in add
assert "LazyVStack" in view and "navigationDestination(item:" in view
assert "case .details(let id): VehicleDetailsScreen(list: model, vehicleID: id)" in view
assert "VehiclesHeader(back: back)" in view and "ScrollView {" in view
for text in ("אין עדיין רכבים", "רק מנהל המשפחה יכול להוסיף רכבים", "הרכבים שלנו", "רכבים לא פעילים"):
    assert text in view
assert "VehicleCategory.illustration(vehicle.category)" in view
assert ".frame(width: 112, height: 64)" in view and "vehicle.retired ? 0.5 : 1" in view
assert "model.pop()" in add and "model.editable" in add and "@FocusState" in add
assert ".disabled(!model.maySubmit)" in add and ".disabled(!model.draft.valid" not in add
assert "ScrollViewReader" in add and "proxy.scrollTo(first" in add
assert "accessibilityFocused($errorFocus" in add and "יש לבחור יצרן מתוך הרשימה" in add
for forbidden in ("print(", "Logger(", "NSLog(", "UserDefaults", "URLSession(", "CLGeocoder", "CBCentralManager"):
    for path in (source / "Vehicles").glob("*.swift"):
        assert forbidden not in path.read_text(encoding="utf-8"), (path.name, forbidden)
assets = ["icons/archive/vehicles_icon.png", "icons/archive/no_cars_icon.png", "icons/archive/single_car_icon.png",
          "icons/archive/phone_icon.png", "icons/archive/maintenance_icon.png", "icons/archive/trash_icon.png", "icons/archive/info_icon.png",
          "icons/archive/manufacturer_icon.png", "icons/archive/license_plate.png",
          "vehicles/hatchback/vehicle_hatchback.png", "vehicles/sedan/vehicle_sedan.png",
          "vehicles/crossover/vehicle_crossover.png", "vehicles/van/modern_silver_minivan.png", "vehicles/suv/suv_silver.png"]
for relative in assets:
    original = source / "Resources/AppAssets" / relative
    data = original.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", data[16:24])
    assert width > 0 and height > 0
    if len(sys.argv) > 1:
        candidates = list(Path(sys.argv[1]).rglob(original.name))
        assert candidates and any(hashlib.sha256(p.read_bytes()).digest() == hashlib.sha256(data).digest() for p in candidates)
details = (source / "Vehicles/VehicleDetailsScreen.swift").read_text(encoding="utf-8")
assert "NavigationStack" not in details and "Form {" not in details
assert "VehicleDay.calendar" in details and "TimeZone(secondsFromGMT: 0)" in details
assert "model.stop(); list.pop()" in details and ".onDisappear { model.stop() }" in details
assert "frame(height: 200)" in details and "vehicle.retired ? 0.55 : 1" in details
assert "הגדרת החיבור והזיהוי האוטומטי לרכב זה עדיין אינה זמינה" in details
assert "action: model.confirmDelete" in details and "if model.canManage" in details
print("PASS: fourteen original Vehicles assets and static Details/list wiring (not a device rendering test)")
