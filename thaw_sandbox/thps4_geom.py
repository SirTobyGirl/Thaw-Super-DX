"""THPS4 and THUG (PS2) level geometry -> THUG2 form, which geom.thug2_to_thaw then takes to THAW.

Same node tree as THUG2 (geom.py). Differences found on School (sch.geom.ps2):
  * UVs are V2_16 unpacks (cmd 0x65); THAW's batch layouts only use V2_32 (0x64). Both hold 12-bit fixed
    point (4096 = 1.0) and the VIF sign-extends 16-bit values into the same 32-bit VU words, so widening the
    data in the file is exact and the VU memory layout (addresses, leaf size field) does not change.
  * leaves do not name their texture (w17 = 0). Textures of a group are uploaded in file order at rising
    TBP, so each leaf's TEX0 (TBP, size, format, palette format) is matched to the group's textures in order.
  * node words: w7 has a top byte 0xff (cleared: THAW gives meaning to high flag bits), w13 = -1 (THUG2: 0),
    w14 cleared to -1 (THAW: relocation list offset; THPS4: other meaning),
    w16 = 0x0000ff00 (THUG2: 0xff00ff00).
Leaf chunks are DMA packets (tag qword: qwc in bits 0-15, VIF codes from byte 8); they are rebuilt with their
new length and laid out again in the original order; node offsets are fixed for the shift.
"""
import collections
import struct

from thaw_sandbox import geom as G

K = 0x10


def _tex0(b, o):
    for p, w in G.vif_codes(b, o):
        if (w >> 24) & 0x6F == 0x68:
            for i in range((w >> 16) & 0xFF):
                lo, hi, r = struct.unpack_from("<3I", b, p + 4 + 12 * i)
                if r & 0xFF == 6:
                    return (hi << 32) | lo
            return None
    return None


def _fits(t, v):
    tw, th, psm, cpsm = 1 << ((v >> 26) & 0xF), 1 << ((v >> 30) & 0xF), (v >> 20) & 0x3F, (v >> 51) & 0xF
    return t.width == tw and t.height == th and t.psm == psm and (psm not in (0x13, 0x14) or t.cpsm == cpsm)


def _clut_blocks(t):
    """GS blocks a texture's palette takes: T4 1, T8 2 (CT16) or 4 (CT32), unpalettised 0."""
    return 1 if t.psm == 0x14 else (4 if t.cpsm == 0 else 2) if t.psm == 0x13 else 0


def _match_textures(b, leaves, textures):
    """{group crc: {tex0: texture crc}}. A group's palettes are uploaded downwards from a top block in file order,
    unused textures included, so TEX0's CBP names the texture exactly: CBP = top - (palette blocks of textures
    0..i). The top is the value most leaves agree on. TEX0 values that fit no slot fall back to walking the
    group's textures in file order against the values in TBP order (unused textures skipped)."""
    use = collections.defaultdict(set)
    for _o, n in leaves:
        t = _tex0(b, K + n[8])
        if t is not None:
            use[n[11]].add(t)
    out = {}
    for g, vals in use.items():
        ts = [x for x in textures if x.group == g]
        cum, c = [], 0
        for x in ts:
            c += _clut_blocks(x)
            cum.append(c)
        votes = collections.Counter(((v >> 37) & 0x3FFF) + cum[i] for v in vals for i, x in enumerate(ts)
                                    if _fits(x, v))
        top = votes.most_common(1)[0][0] if votes else None
        m = {}
        for v in vals:
            i = next((i for i, x in enumerate(ts) if _fits(x, v) and top - cum[i] == (v >> 37) & 0x3FFF), None)
            if i is not None:
                m[v] = ts[i].crc
        i = 0
        for v in sorted(vals, key=lambda v: v & 0x3FFF):
            while i < len(ts) and not _fits(ts[i], v):
                i += 1
            if i == len(ts):
                break
            m.setdefault(v, ts[i].crc)
            i += 1
        out[g] = m
    return out


# THPS4 sets 0x4000 in the flag word of every strip-restart vertex (0xc000); THAW's data never does (Kyoto: 0x8000
# restart, 0x20 odd-vertex parity) and its microcode gives the bit another meaning: THPS4 levels lost surfaces
W_CLEAR = 0x4000

# Vertex GIFtags (PRE, NREG 3, REGS ST RGBAQ XYZ): for microcode selectors 0x3c / 0x3e / 0x48 THPS4 says XYZF2
# without fog (PRIM 0x5c) - its microcode wrote 24-bit Z + fog. THAW's routines behind the same selectors write a
# 32-bit Z for XYZ2 (THAW, THUG, THUG2 all use XYZ2 + PRIM fog bit, 0x7c, with them). Read as XYZF2 the depth
# lost its top byte: walls and floors drew over the skater (torso hidden, invisible at spawn). Every THPS4 level.
XYZF2_SELECTORS = {0x3C, 0x3E, 0x48}
FGE = 1 << 20  # PRIM fog bit, in GIFtag word 1 (PRIM = bits 47-57 of the tag)


def _vertex_tag(q):
    if (q[1] >> 14) & 1 and q[1] >> 28 == 3 and q[2] & 0xFFF == 0x512 and q[1] & 0xFF in XYZF2_SELECTORS:
        q[1] |= FGE
        q[2] = (q[2] & ~0xFFF) | 0x412
    return q


def _rebuild_chunk(b, o):
    """Leaf chunk at file offset o -> new chunk bytes with V2_16 UV unpacks widened to V2_32."""
    lo = struct.unpack_from("<I", b, o)[0]
    end = o + 16 + (lo & 0xFFFF) * 16
    body = bytearray()
    codes = list(G.vif_codes(b, o))
    for idx, (p, w) in enumerate(codes):
        nxt = codes[idx + 1][0] if idx + 1 < len(codes) else end
        cmd = (w >> 24) & 0x7F
        if cmd >= 0x60 and cmd & 0x0F == 0x05:  # V2_16 -> V2_32
            num = ((w >> 16) & 0xFF) or 256
            usn = (w >> 14) & 1
            vals = struct.unpack_from(f"<{2 * num}{'H' if usn else 'h'}", b, p + 4)
            body += struct.pack("<I", (w & ~0x0F000000) | (0x04 << 24))
            body += struct.pack(f"<{2 * num}{'I' if usn else 'i'}", *vals)
        elif cmd >= 0x60 and cmd & 0x6F == 0x6C:  # V4_32: GIFtags among them
            num = ((w >> 16) & 0xFF) or 256
            body += struct.pack("<I", w)
            for i in range(num):
                q = list(struct.unpack_from("<4I", b, p + 4 + 16 * i))
                body += struct.pack("<4I", *_vertex_tag(q))
            body += b[p + 4 + 16 * num:nxt]
        elif cmd >= 0x60 and cmd & 0x6F == 0x6D:  # V4_16 positions: x, y, z, flags
            num = ((w >> 16) & 0xFF) or 256
            vals = list(struct.unpack_from(f"<{4 * num}H", b, p + 4))
            for i in range(3, 4 * num, 4):
                vals[i] &= ~W_CLEAR & 0xFFFF
            body += struct.pack("<I", w) + struct.pack(f"<{4 * num}H", *vals)
            body += b[p + 4 + 8 * num:nxt]
        else:
            body += b[p:nxt]
    body += bytes(-(8 + len(body)) % 16)  # VIF NOPs up to the qword
    qwc = (8 + len(body)) // 16 - 1
    tag = struct.pack("<II", (lo & ~0xFFFF) | qwc, struct.unpack_from("<I", b, o + 4)[0])
    return tag + bytes(body)


def to_thug2(b: bytes, textures) -> tuple[bytes, dict]:
    """b: THPS4 .geom.ps2; textures: thug2_tex.parse(...)[1] of the level's (version 4) dictionary."""
    assert struct.unpack_from("<I", b, 0)[0] == K
    nodes = list(G.walk(b))
    leaves = [(o, n) for o, n in nodes if n[7] & G.LEAF]
    tex_of = _match_textures(b, leaves, textures)
    root = struct.unpack_from("<I", b, K)[0]
    chunks = sorted({n[8] for _o, n in leaves})
    first, node_start = K + chunks[0], K + root
    # the node records: everything from the root's region to the end; chunks: from the first chunk up to there
    assert all(K + c < node_start for c in chunks)
    new_chunks, pos, where = [], K + chunks[0], {}
    for c in chunks:
        nb = _rebuild_chunk(b, K + c)
        where[c] = pos - K
        new_chunks.append(nb)
        pos += len(nb)
    tail_start = node_start
    shift = pos - tail_start  # node region moves by this much
    out = bytearray(b[:first]) + b"".join(new_chunks) + bytearray(b[tail_start:])
    struct.pack_into("<I", out, K, root + shift)
    stats = collections.Counter()

    def moved(off):
        return off if off == 0xFFFFFFFF else off + shift
    for o, n in nodes:
        w = list(n)
        no = o + shift
        if n[7] & G.LEAF:
            w[8] = where[n[8]]
            t = _tex0(b, K + n[8])
            w[17] = n[17] or tex_of.get(n[11], {}).get(t, 0)  # THUG leaves already name their texture
            stats["leaves"] += 1
            stats["texture matched"] += bool(w[17])
        else:
            w[8] = moved(n[8])
        w[10] = moved(n[10])
        # flag 0x400 = vertex colour animation, list at w14 (FUN_001d6138 interpolates keys and writes them through
        # the list's pointers). The THPS4/THUG list format differs and w14 is cleared below, so the flag goes too
        # (static colours); left set, the renderer read a null list when such a leaf came into view (THUG Hawaii,
        # Vancouver, Slam City Jam froze; 0x1d6138 load from 0)
        w[7] = n[7] & 0x00FFFBFF
        w[13] = 0
        # w14: THAW treats it as an offset to a relocation list ({count, entries}) unless -1; THPS4 uses it for
        # something else (Carnival: 90 nodes) and the loader (FUN_001cfb58) walked past the end of RAM
        if w[14] != 0xFFFFFFFF:
            stats["w14 cleared"] += 1
        w[14] = 0xFFFFFFFF
        w[16] = 0xFF00FF00
        struct.pack_into("<20I", out, no, *w)
    stats["bytes"] = len(out) - len(b)
    return bytes(out), dict(stats)
