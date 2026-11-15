"""Read-only validation of the approved dark wordmark; does not activate it."""
import pathlib
import runpy
import xml.etree.ElementTree as ET

ios = pathlib.Path(__file__).resolve().parents[1]
repo = ios.parent
# Reuse the existing standard-library RGBA decoder and its resource checks.
read_png = runpy.run_path(str(ios / 'Checks/check-navigation-assets.py'))['read_png']
relative = 'branding/in-app-brand/fca-wordmark-dark.png'
assets = ios / 'Sources/FamilyCarAgent/Resources/AppAssets'
w, h, rows, _ = read_png(assets / relative)
assert (w, h) == (2170, 725)
assert not any(rows[0][3::4]) and not any(rows[-1][3::4])
assert all(row[3] == row[-1] == 0 for row in rows), 'Artwork reaches canvas edge'
assert any(0 < a < 255 for row in rows for a in row[3::4]), 'Missing antialiasing'
opaque = {tuple(row[x:x+3]) for row in rows for x in range(0, w*4, 4) if row[x+3] == 255}
assert opaque == {(254, 254, 254), (255, 255, 255)}, opaque
source = ET.parse(repo / 'assets/branding/in-app-brand/Family Car Agent Road Logo(1)_dark.svg').getroot()
assert source.get('viewBox') == '0 0 2170 725'
assert (source.get('width'), source.get('height')) == ('2170', '725')
assert [node.tag.rsplit('}', 1)[-1] for node in source] == ['title', 'path', 'path', 'path']
assert [node.get('fill') for node in source if node.tag.endswith('path')] == ['#FEFEFE', '#FEFEFE', '#FFFFFF']
assert not any('href' in key or 'url(' in value for node in source.iter() for key, value in node.attrib.items())
package = (ios / 'Package.swift').read_text(encoding='utf-8')
assert '.copy("Resources/AppAssets")' in package
loader = (ios / 'Sources/FamilyCarAgent/AppAsset.swift').read_text(encoding='utf-8')
assert 'Bundle.module.url(' in loader and 'subdirectory: "AppAssets"' in loader
assert (assets / 'branding/in-app-brand/Family Car Agent Road Logo(1).png').is_file()
palette = (ios / 'Sources/FamilyCarAgent/Appearance/FCAColors.swift').read_text(encoding='utf-8')
assert relative in palette
assert 'FCABranding.wordmark(dark: colorScheme == .dark)' in loader
assert 'colorScheme == .dark ? .normal : .multiply' in loader
print('PASS: dark wordmark 2170x725 RGBA, transparent edges, original colors, no clipping; packaged and selected by effective appearance')
