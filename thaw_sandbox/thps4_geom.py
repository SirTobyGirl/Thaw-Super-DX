"""THPS4 (PS2) level geometry -> THUG2 form, which geom.thug2_to_thaw then takes to THAW.

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


def _match_textures(b, leaves, textures):
    """{group crc: {tex0: texture crc}} by walking each group's textures in file order against its leaves'
    distinct TEX0 values in TBP order (unused textures are skipped)."""
    use = collections.defaultdict(set)
    for _o, n in leaves:
        t = _tex0(b, K + n[8])
        if t is not None:
            use[n[11]].add(t)
    out = {}
    for g, vals in use.items():
        ts = [x for x in textures if x.group == g]
        vals = sorted(vals, key=lambda v: v & 0x3FFF)
        m, i = {}, 0
        for v in vals:
            tw, th, psm, cpsm = 1 << ((v >> 26) & 0xF), 1 << ((v >> 30) & 0xF), (v >> 20) & 0x3F, (v >> 51) & 0xF
            while i < len(ts) and not (ts[i].width == tw and ts[i].height == th and ts[i].psm == psm
                                       and (psm not in (0x13, 0x14) or ts[i].cpsm == cpsm)):
                i += 1
            if i == len(ts):
                break
            m[v] = ts[i].crc
            i += 1
        out[g] = m
    return out


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
            w[17] = tex_of.get(n[11], {}).get(t, 0)
            stats["leaves"] += 1
            stats["texture matched"] += bool(w[17])
        else:
            w[8] = moved(n[8])
        w[10] = moved(n[10])
        w[7] = n[7] & 0x00FFFFFF
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
