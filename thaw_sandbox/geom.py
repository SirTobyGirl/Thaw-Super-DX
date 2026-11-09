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


def thug2_to_thaw(b: bytes, groups: list, textures_by_group: dict, set_100: bool = True,
                  strip_extra: bool = True) -> tuple[bytes, dict]:
    """groups: group crcs in the output texture dictionary's order.
    textures_by_group: group crc -> texture crcs in that group's order (as written)."""
    out = bytearray(b)
    gidx = {g: i + 1 for i, g in enumerate(groups)}
    tidx = {g: {t: i + 1 for i, t in enumerate(ts)} for g, ts in textures_by_group.items()}
    stats = {"leaves": 0, "no group": 0, "no texture": 0}
    k = struct.unpack_from("<I", b, 0)[0]
    for o, n in walk(b):
        if not n[7] & LEAF:
            continue
        stats["leaves"] += 1
        g = gidx.get(n[11])
        if g is None:
            stats["no group"] += 1
            g = 1
        t = tidx.get(n[11], {}).get(n[17], 0)
        if t == 0:  # texture not in the dictionary: 0 is not "none" to the engine (it becomes a pointer
            stats["no texture"] += 1  # to the texture before the group), so use the group's first texture
            t = 1
        if strip_extra:
            n_fixed = strip_extra_qwords(out, k + n[8])
            if n_fixed:
                stats["extra qwords stripped"] = stats.get("extra qwords stripped", 0) + 1
                lo = struct.unpack_from("<I", out, k + n[8])[0]
                field = ((lo >> 16) & 0x3FF) - n_fixed  # VU slots used: 3 per vertex + 7, plus the extras
                struct.pack_into("<I", out, k + n[8], (lo & ~(0x3FF << 16)) | (field << 16))
                struct.pack_into("<I", out, o + 9 * 4, (n[9] & 0xFC00FFFF) | (field << 16))
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


def keep_sectors(b: bytes, keep) -> tuple[bytes, int]:
    """Experiment: keep only the root's children (sectors) whose index passes keep(i); relinks siblings."""
    out = bytearray(b)
    k = struct.unpack_from("<I", b, 0)[0]
    r = struct.unpack_from("<I", b, k)[0]
    root = struct.unpack_from("<20I", b, k + r)
    kids, c = [], root[8]
    while c != 0xFFFFFFFF:
        kids.append(c)
        c = struct.unpack_from("<I", b, k + c + 40)[0]
    kept = [c for i, c in enumerate(kids) if keep(i)]
    struct.pack_into("<I", out, k + r + 32, kept[0] if kept else 0xFFFFFFFF)
    for a, nxt in zip(kept, kept[1:] + [0xFFFFFFFF]):
        struct.pack_into("<I", out, k + a + 40, nxt)
    return bytes(out), len(kids)


def prune_leaves(b: bytes, keep) -> tuple[bytes, int]:
    """Experiment: unlink leaves whose index (depth-first order) fails keep(i) from their parent's child chain."""
    out = bytearray(b)
    k = struct.unpack_from("<I", b, 0)[0]
    count = [0]

    def chain(parent_field, first):
        # parent_field: file offset of the word that points at the first child
        prev_field, c = parent_field, first
        while c != 0xFFFFFFFF:
            n = struct.unpack_from("<20I", b, k + c)
            drop = False
            if n[7] & LEAF:
                drop = not keep(count[0])
                count[0] += 1
            elif n[8] != 0xFFFFFFFF:
                chain(k + c + 32, n[8])
            if drop:
                struct.pack_into("<I", out, prev_field, n[10])
            else:
                prev_field = k + c + 40
            c = n[10]

    r = struct.unpack_from("<I", b, k)[0]
    chain(k + r + 32, struct.unpack_from("<I", b, k + r + 32)[0])
    return bytes(out), count[0]


def strip_extra_qwords(b: bytearray, o: int) -> int:
    """THUG2 leaves may carry two extra V4_32 n1 unpacks per batch that THAW's layout does not have: one
    right after the register block (moving the vertex GIFtag/UV/colour/position slots up by one) and one
    just before MSCAL. Blank both to VIF NOPs (same size) and move the following unpacks back down.
    The float in the extra qword moves to word 2 (top 16 bits) of each vertex GIFtag, as THAW stores it,
    and EOP is set on every vertex GIFtag (THAW always has it; a zero parameter hung the microcode).
    Works in place on the leaf chunk at file offset o; returns the number of batches changed."""
    codes = list(vif_codes(bytes(b), o))
    fixed, shift, prev = 0, 0, None
    param = 0  # THUG2 keeps a per-leaf float in the extra qword ({0, 0x4c, 0, f}); THAW puts f's top half
    tags = []  # into word 2 bits 16-31 of each vertex GIFtag (the V4_32 n1 unpacked after STCYCL 0x103)
    for idx, (p, w) in enumerate(codes):
        cmd = (w >> 24) & 0x7F
        nxt = (codes[idx + 1][1] >> 24) & 0x7F if idx + 1 < len(codes) else None
        is_v4_32_n1 = cmd & 0x6F == 0x6C and ((w >> 16) & 0xFF) == 1
        if is_v4_32_n1 and prev == 0x01 and (codes[idx - 1][1] & 0xFFFF) == 0x0103:
            tags.append(p + 4)
        if is_v4_32_n1 and prev is not None and prev & 0x6F == 0x68 and shift == 0:
            param = struct.unpack_from("<I", b, p + 16)[0] & 0xFFFF0000
            b[p:p + 20] = bytes(20)  # extra qword after the register block
            shift = 1
        elif is_v4_32_n1 and (shift or param) and nxt in (0x14, 0x15, 0x17):
            b[p:p + 20] = bytes(20)  # extra qword before MSCAL
            fixed += 1
        elif cmd >= 0x60 and shift:
            struct.pack_into("<I", b, p, (w & ~0x3FF) | ((w & 0x3FF) - 1))
        if cmd in (0x14, 0x15, 0x17):
            shift = 0
        prev = cmd
    for t in tags:
        w0, w2 = struct.unpack_from("<I", b, t)[0], struct.unpack_from("<I", b, t + 8)[0]
        struct.pack_into("<I", b, t, w0 | 0x8000)  # EOP: set on every vertex GIFtag in THAW
        if param:
            struct.pack_into("<I", b, t + 8, (w2 & 0xFFFF) | param)
    return fixed
