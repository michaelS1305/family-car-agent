"""Faithful solid-path Android Vector rasterization; requires local rsvg-convert."""
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[2]
source = root / "android/app/src/main/res/drawable/illustration_companion.xml"
destination = root / "ios/Sources/FamilyCarAgent/Resources/AppAssets/illustrations/first_vehicle_setup.png"
a = "{http://schemas.android.com/apk/res/android}"
vector = ET.parse(source).getroot()
assert vector.tag == "vector"
assert vector.attrib[a + "viewportWidth"] == "1672" and vector.attrib[a + "viewportHeight"] == "941"
svg = ET.Element("svg", xmlns="http://www.w3.org/2000/svg", width="1672", height="941", viewBox="0 0 1672 941")
# Android renders this autoMirrored drawable in explicit LTR: preserve original coordinates.
for path in vector:
    assert path.tag == "path" and set(path.attrib) == {a + "pathData", a + "fillColor"}
    color = path.attrib[a + "fillColor"]
    assert len(color) == 7 and color.startswith("#")
    ET.SubElement(svg, "path", d=path.attrib[a + "pathData"], fill=color)
assert len(svg) == 78
result = subprocess.run(["rsvg-convert", "--format=png"], input=ET.tostring(svg), capture_output=True, check=True)
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_bytes(result.stdout)
print("Converted 78 original Android paths to transparent 1672 x 941 PNG")
