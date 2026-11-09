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
            field = thaw_field(bytes(out), k + n[8])
            if field is None:  # leaf type the formula does not cover: THUG2 value minus what was removed
                field = ((lo >> 16) & 0x3FF) - (n_fixed + 1 if n_fixed else 0)
            if field != (lo >> 16) & 0x3FF:
                stats["field corrected"] = stats.get("field corrected", 0) + 1
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


def thaw_field(b: bytes, o: int):
    """THAW's VU slot count for a leaf (node w9 bits 16-25 and the leaf DMA tag bits 16-25): the sum over its
    batches (one per MSCAL) of 3 per vertex + 2 + GS registers in that batch, mod 1024. Holds for 96% of all
    THAW leaves when the vertex count is taken from the V2_32 UV unpack, and for all THAW leaves when leaves without
    UVs take it from their V3_16 unpack (normals?). The engine places the next leaf / group SIGNAL packet right after it:
    a value larger than THAW's made the microcode's output overwrite the SIGNAL and the frame never ended."""
    tot, nv, nr, cl = 0, None, 0, 3
    for _, w in vif_codes(b, o):
        cmd = (w >> 24) & 0x7F
        if cmd == 0x01:
            cl = w & 0xFF  # slots per vertex in this batch (3, or 2 without UVs)
        elif cmd & 0x6F == 0x68:
            nr = (w >> 16) & 0xFF
        elif cmd & 0x6F in (0x64, 0x69, 0x6A, 0x6E) and nv is None:  # vertex count: first per-vertex stream
            nv = ((w >> 16) & 0xFF) or 256
        elif cmd in (0x14, 0x15, 0x17):
            if nv is None:
                return None
            tot += cl * nv + 2 + nr
            nv, nr = None, 0
    return tot & 0x3FF


# Vertex GIFtag word 1 bits 0-7 select the VU1 microcode routine (an index into a branch table in VU1 micro
# memory). THAW moved some routines; matching the routine bodies of both games' microcode (THUG2 Training state
# vs THAW state) gives this map; all other selectors used by THUG2 levels are unchanged.
SELECTOR_MAP = {0x52: 0x4E, 0x54: 0x50, 0x56: 0x52, 0x58: 0x54}


def relayout_batches(b: bytearray, o: int):
    """Rewrite every unpack address in a leaf to THAW's contiguous layout. Per batch, starting at s:
    register GIFtag @s, registers @s+1.., vertex GIFtag @s+1+R, then the per-vertex streams (UV or normal,
    colour, position) @s+2+R, s+3+R, s+4+R (stride 3); the next batch starts at s + 3n + 2 + R.
    THUG2 leaves with the extra qwords had later batches one slot further on, so the last vertex overlapped
    the engine's next packet (the group SIGNAL) - verified in VU1 memory with the PCSX2 dev build."""
    s, R, n, k, has_regs = 0, 0, 0, 0, False
    for p, w in vif_codes(bytes(b), o):
        cmd = (w >> 24) & 0x7F
        if cmd >= 0x60:
            num = ((w >> 16) & 0xFF) or 256
            kind = cmd & 0x6F
            if kind == 0x6C and num == 1 and k == 0:          # register GIFtag
                addr = s
            elif kind == 0x68:                                # register block
                R, has_regs = num, True
                addr = s + 1
            elif kind == 0x6C and num == 1:                   # vertex GIFtag
                addr = s + 1 + R
            else:                                             # per-vertex streams, in order
                n = num
                addr = s + 2 + R + (k - 3)
            struct.pack_into("<I", b, p, (w & ~0x3FF) | (addr & 0x3FF))
            k += 1
        elif cmd in (0x14, 0x15, 0x17):
            s += 3 * n + 2 + R
            R, n, k, has_regs = 0, 0, 0, False


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
    if param or fixed:
        relayout_batches(b, o)
    for t in tags:
        w0, w2 = struct.unpack_from("<I", b, t)[0], struct.unpack_from("<I", b, t + 8)[0]
        struct.pack_into("<I", b, t, w0 | 0x8000)  # EOP: set on every vertex GIFtag in THAW
        w1 = struct.unpack_from("<I", b, t + 4)[0]
        if (w1 & 0xFF) in SELECTOR_MAP:
            struct.pack_into("<I", b, t + 4, (w1 & ~0xFF) | SELECTOR_MAP[w1 & 0xFF])
        if param:
            struct.pack_into("<I", b, t + 8, (w2 & 0xFFFF) | param)
    return fixed


def bind_textures(b: bytes, tex: bytes) -> tuple[bytes, dict]:
    """Write each leaf's GS texture registers from the THAW texture dictionary it will be loaded with.
    THAW never patches these for ordinary leaves (only flag 0x8000000 ones, in the load walker FUN_001cfb58),
    so the file must carry them: in Kyoto all 3049 ordinary leaves have TEX0 == their texture record's TEX0
    and MIPTBP1 == its MIPTBP1; TEX1 carries the mip count (MXL, bits 2-4) and register 0x34 only exists
    for mip-mapped textures. Leaves without a MIPTBP slot are drawn from the base level only."""
    from thaw_sandbox import thaw_tex as TT
    offs, texs = TT.parse(tex)
    ng = struct.unpack_from("<H", tex, 2)[0]
    groups = [struct.unpack_from("<20I", tex, 0x10 + 80 * g) for g in range(ng)]
    out = bytearray(b)
    k = struct.unpack_from("<I", b, 0)[0]
    st = {"bound": 0, "skipped": 0}
    for o, n in walk(b):
        if not n[7] & LEAF:
            continue
        if n[7] & 0x8100000 or not (1 <= n[11] <= ng) or not (1 <= n[17] <= groups[n[11] - 1][15]):
            st["skipped"] += 1
            continue
        t = texs[groups[n[11] - 1][16] + n[17] - 1]
        w = t.words
        levels = w[2] + 1
        for p, code in vif_codes(bytes(out), k + n[8]):
            if (code >> 24) & 0x6F != 0x68:  # V3_32 unpack = register block (lo, hi, reg) triplets
                continue
            nregs = (code >> 16) & 0xFF
            regs = [struct.unpack_from("<I", out, p + 4 + 12 * i + 8)[0] & 0xFF for i in range(nregs)]
            has_mip = 0x34 in regs
            for i, r in enumerate(regs):
                q = p + 4 + 12 * i
                if r == 0x06:
                    struct.pack_into("<2I", out, q, w[4], w[5])
                elif r == 0x34:
                    struct.pack_into("<2I", out, q, w[6], w[7])
                elif r == 0x36:
                    struct.pack_into("<2I", out, q, w[8], w[9])
                elif r == 0x14:
                    lo = struct.unpack_from("<I", out, q)[0]
                    mxl = min(levels - 1, 6) if has_mip else 0
                    struct.pack_into("<I", out, q, (lo & ~0x1C) | (mxl << 2))
        st["bound"] += 1
    return bytes(out), st


def leaf_regs(b: bytes, o: int) -> list:
    """GS register ids in the leaf's first register block (V3_32 unpack of lo/hi/reg triplets)."""
    for p, w in vif_codes(b, o):
        if (w >> 24) & 0x6F == 0x68:
            return [struct.unpack_from("<I", b, p + 4 + 12 * i + 8)[0] & 0xFF for i in range((w >> 16) & 0xFF)]
    return []


def drop_untextured(b: bytes) -> tuple[bytes, int]:
    """Unlink leaves without a TEX0 register (THUG2 testlevel has an untextured lit leaf type, microcode tag 0x44,
    that THAW never uses; it froze the renderer)."""
    k = struct.unpack_from("<I", b, 0)[0]
    bad = {o for o, n in walk(b) if n[7] & LEAF and 0x06 not in leaf_regs(b, k + n[8])}
    if not bad:
        return b, 0
    order = []
    stack = [struct.unpack_from("<I", b, k)[0]]
    idx = {}

    def dfs(off):
        while off != 0xFFFFFFFF:
            n = struct.unpack_from("<20I", b, k + off)
            if n[7] & LEAF:
                idx[k + off] = len(idx)
            elif n[8] != 0xFFFFFFFF:
                dfs(n[8])
            off = n[10]
    r = struct.unpack_from("<I", b, k)[0]
    dfs(struct.unpack_from("<I", b, k + r + 32)[0])
    drop_ids = {idx[o] for o in bad if o in idx}
    out, _ = prune_leaves(b, lambda i: i not in drop_ids)
    return out, len(drop_ids)
