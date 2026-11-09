"""PS2 level geometry (.geom.ps2 in THUG2, type '.geom' entries in THAW zone PAKs).

Both games share the layout: u32 data offset K (0x10), then at K a u32 offset to the root node, and a tree
of 0x50-byte CGeomNode records linked by K-relative offsets:
  w7  flags (bit 1 = leaf)          w8  leaf: VIF chunk offset / node: first child
  w10 next sibling (-1 = none)      w11 texture group                w17 texture
The VIF leaf streams are identical between the games (same microcode entry, same unpack mix).

The difference: THUG2 stores w11 = texture group checksum and w17 = texture checksum; THAW stores
w11 = 1-based index of the group in the zone's texture dictionary and w17 = 1-based index of the texture
within that group (0 = none). Leaves with flag 0x100000 use w17 for something else in THAW.
Format notes cross-checked with neversoft-multitool (MIT), docs/formats/thaw-worldzone-mdl.md.
"""
import struct

K = 0x10
LEAF = 0x2


def walk(b: bytes):
    """Yield (file offset, words) for every node in the tree."""
    k = struct.unpack_from("<I", b, 0)[0]
    stack = [struct.unpack_from("<I", b, k)[0]]
    while stack:
        o = stack.pop()
        if o == 0xFFFFFFFF:
            continue
        n = struct.unpack_from("<20I", b, k + o)
        yield k + o, n
        if n[10] != 0xFFFFFFFF:
            stack.append(n[10])
        if not n[7] & LEAF and n[8] != 0xFFFFFFFF:
            stack.append(n[8])


def thug2_to_thaw(b: bytes, groups: list, textures_by_group: dict, set_100: bool = True) -> tuple[bytes, dict]:
    """groups: group crcs in the output texture dictionary's order.
    textures_by_group: group crc -> texture crcs in that group's order (as written)."""
    out = bytearray(b)
    gidx = {g: i + 1 for i, g in enumerate(groups)}
    tidx = {g: {t: i + 1 for i, t in enumerate(ts)} for g, ts in textures_by_group.items()}
    stats = {"leaves": 0, "no group": 0, "no texture": 0}
    for o, n in walk(b):
        if not n[7] & LEAF:
            continue
        stats["leaves"] += 1
        g = gidx.get(n[11])
        if g is None:
            stats["no group"] += 1
            g = 1
        t = tidx.get(n[11], {}).get(n[17], 0)
        if t == 0:
            stats["no texture"] += 1
        if set_100:
            struct.pack_into("<I", out, o + 7 * 4, n[7] | 0x100)  # every THAW leaf carries flag 0x100
        struct.pack_into("<I", out, o + 11 * 4, g)
        struct.pack_into("<I", out, o + 17 * 4, t)
    return bytes(out), stats


def set_active(b: bytes, keep) -> bytes:
    """Experiment: clear flag bit 0 (active) on leaves whose index (walk order) fails keep(i)."""
    out = bytearray(b)
    i = 0
    for o, n in walk(b):
        if n[7] & LEAF:
            if not keep(i):
                struct.pack_into("<I", out, o + 7 * 4, n[7] & ~1)
            i += 1
    return bytes(out)


def vif_codes(b: bytes, o: int):
    """Yield (file offset, code word) for the VIF codes of the leaf chunk at file offset o (K applied)."""
    lo = struct.unpack_from("<I", b, o)[0]
    i, end = o + 8, o + 16 + (lo & 0xFFFF) * 16
    while i < end:
        w = struct.unpack_from("<I", b, i)[0]
        cmd = (w >> 24) & 0x7F
        yield i, w
        i += 4
        if cmd >= 0x60:
            vn, vl, num = (cmd >> 2) & 3, cmd & 3, ((w >> 16) & 0xFF) or 256
            i += ((32 >> vl) * (vn + 1) * num + 31) // 32 * 4
        elif cmd in (0x50, 0x51):
            i += ((w & 0xFFFF) or 65536) * 16
        elif cmd == 0x20:
            i += 4
        elif cmd in (0x30, 0x31):
            i += 16
        elif cmd == 0x4A:
            i += (((w >> 16) & 0xFF) or 256) * 8


def mute_leaves(b: bytes, keep) -> bytes:
    """Experiment: replace MSCAL codes with NOP in leaves whose index (walk order) fails keep(i)."""
    out = bytearray(b)
    k = struct.unpack_from("<I", b, 0)[0]
    i = 0
    for o, n in walk(b):
        if n[7] & LEAF:
            if not keep(i):
                for p, w in vif_codes(b, k + n[8]):
                    if (w >> 24) & 0x7F in (0x14, 0x15, 0x17):
                        struct.pack_into("<I", out, p, w & 0x80000000)
            i += 1
    return bytes(out)
