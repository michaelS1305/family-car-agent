"""Lossless PNG navigation crops and verification, using only Python's standard library.
--create writes new derivatives only; originals are never changed. Default is read-only.
"""
import pathlib
import struct
import sys
import zlib

root = pathlib.Path(__file__).resolve().parents[1] / 'Sources/FamilyCarAgent/Resources/AppAssets/icons'


def read_png(path):
    data = path.read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    pos, compressed, metadata = 8, b'', []
    while pos < len(data):
        size = struct.unpack('>I', data[pos:pos+4])[0]
        kind, payload = data[pos+4:pos+8], data[pos+8:pos+8+size]
        if kind == b'IHDR':
            w, h, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', payload)
            assert (depth, color, compression, filtering, interlace) == (8, 6, 0, 0, 0)
        if kind == b'IDAT':
            compressed += payload
        if kind in [b'sRGB', b'gAMA', b'cHRM', b'iCCP', b'pHYs']:
            metadata.append((kind, payload))
        pos += size + 12
    raw = zlib.decompress(compressed)
    stride = w * 4
    assert len(raw) == (stride + 1) * h
    rows, previous = [], bytearray(stride)
    for y in range(h):
        offset = y * (stride + 1)
        mode = raw[offset]
        row = bytearray(raw[offset+1:offset+1+stride])
        assert mode in range(5)
        for x in range(stride):
            a, b, c = (row[x-4] if x >= 4 else 0), previous[x], (previous[x-4] if x >= 4 else 0)
            p = a + b - c
            distances = [abs(p-a), abs(p-b), abs(p-c)]
            paeth = [a, b, c][distances.index(min(distances))]
            predictor = [0, a, b, (a+b)//2, paeth][mode]
            row[x] = (row[x] + predictor) & 255
        rows.append(bytes(row)); previous = row
    return w, h, rows, metadata


def chunk(kind, payload):
    return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))


for name in ['chat', 'dashboard']:
    w, h, rows, metadata = read_png(root / 'archive' / (name + '_icon.png'))
    occupied = [y for y, row in enumerate(rows) if any(row[3::4])]
    groups = []
    for y in occupied:
        if not groups or y > groups[-1][-1] + 3:
            groups.append([])
        groups[-1].append(y)
    # Visually reviewed: first occupied band is the complete icon; second is Hebrew lettering.
    assert len(groups) == 2 and groups[1][0] - groups[0][-1] >= 20
    top, bottom = groups[0][0], groups[0][-1] + 1
    xs = [x for y in range(top, bottom) for x in range(w) if rows[y][4*x+3]]
    left, right = min(xs), max(xs) + 1
    pad = 2
    cw, ch = right-left+2*pad, bottom-top+2*pad
    cropped = [bytes(cw*4)] * pad
    cropped += [bytes(pad*4) + row[left*4:right*4] + bytes(pad*4) for row in rows[top:bottom]]
    cropped += [bytes(cw*4)] * pad
    path = root / 'navigation' / (name + '_nav_icon.png')
    if '--create' in sys.argv:
        if path.exists():
            existing = read_png(path)
            assert existing[:3] == (cw, ch, cropped), 'Refusing to overwrite unrelated artwork'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', cw, ch, 8, 6, 0, 0, 0)) +
                        b''.join(chunk(kind, payload) for kind, payload in metadata) +
                        chunk(b'IDAT', zlib.compress(b''.join(b'\0'+row for row in cropped))) + chunk(b'IEND', b''))
    aw, ah, actual, actual_metadata = read_png(path)
    assert (aw, ah, actual) == (cw, ch, cropped), 'Crop differs from original artwork or contains lettering'
    assert actual_metadata == metadata, 'Original color/density metadata changed'
    assert any(0 < alpha < 255 for row in actual for alpha in row[3::4]), 'Antialias alpha lost'
    print(f'PASS: {path.name}: {cw}x{ch}, artwork {right-left}x{bottom-top}, 2px transparent border; original RGBA preserved')
