"""Collision (.col, version 10) conversion THUG2 -> THAW (PS2).

Layout (both games): header 8 x u32 {version 10, objects, verts, large faces, small faces, large verts,
small verts, 0}; object records (64 bytes); align 16; float verts (12 B) then fixed verts (6 B);
intensities (1 B per vert); align 4; large faces (10 B) then small faces (8 B); align 2; one byte per
LARGE face; align 4; u32 BSP node bytes; nodes (8 B, axis 3 = leaf with u16 face count); u16 face indices.
All object fields are offsets relative to their section, so sections can move freely.

THAW inserts a 48-byte supersector block after the header:
  u32 0, u32 0, u32 grid columns (x), u32 grid rows (z), f32 bbox min x,y,z,1, f32 bbox max x,y,z,1
The grid size is not a fixed function of the box in shipped files; cells ~1500 units resemble Kyoto.
Verified layout: Kyoto (THAW) and Berlin (THUG2) both parse to their exact last byte.
"""
import math
import struct


def thug2_to_thaw(b: bytes, cell: float = 1500.0) -> bytes:
    ver, no = struct.unpack_from("<2I", b, 0)
    assert ver == 10, ver
    assert struct.unpack_from("<I", b, 32)[0] != 0, "already has a supersector block"
    mn, mx = [math.inf] * 3, [-math.inf] * 3
    for i in range(no):
        f = struct.unpack_from("<8f", b, 32 + 64 * i + 16)
        for k in range(3):
            mn[k] = min(mn[k], f[k])
            mx[k] = max(mx[k], f[4 + k])
    cols = max(1, min(64, math.ceil((mx[0] - mn[0]) / cell)))
    rows = max(1, min(64, math.ceil((mx[2] - mn[2]) / cell)))
    sup = struct.pack("<4I8f", 0, 0, cols, rows, *mn, 1.0, *mx, 1.0)
    return b[:32] + sup + b[32:]
