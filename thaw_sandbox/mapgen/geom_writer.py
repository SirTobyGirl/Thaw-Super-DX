"""Write THAW PS2 level geometry (.geom zone entry) from triangle strips.

Every leaf is one VU1 batch cloned from a template THAW leaf of the most common textured type
(VIF: OFFSET, STCYCL 1/1, register GIFtag + 5 GS registers, STCYCL 3/1, vertex GIFtag, V2_32 UV, V4_8 colour,
STMOD 1, V4_16 position, STMOD 0, MSCAL 8):
  UV        int32 u, v * 4096
  colour    r, g, b, a bytes (128 = 1.0)
  position  int16 x, y, z = (p - leaf centre) * 16, w = 0x8000 on the first two vertices of a strip (no triangle)
            | 0x20 on odd vertices of a strip (winding parity). Positions must stay within +-2047 of the centre.
  slot count ("field", DMA tag and node w9 bits 16-25) = 3 n + 2 + 5
Leaves hang under one inner node per spatial cell, under a root like Kyoto's. The texture registers are filled
later by geom.bind_textures from the texture dictionary.
"""
import collections
import math
import struct

from thaw_sandbox import geom as GM
from thaw_sandbox.qb_parser import qbcrc as H

SHAPE = (2, 1, 0x6C, 0x68, 1, 0x6C, 0x64, 0x6E, 5, 0x6D, 5, 0x14)
MAX_VERTS = 72
CELL = 1600.0
NONE = 0xFFFFFFFF


class Template:
    """Header, parameter block, root/inner/leaf node words and the leaf GIFtags/registers of a THAW geom file."""

    def __init__(self, b: bytes):
        k = struct.unpack_from("<I", b, 0)[0]
        assert k == 0x10
        self.k = k
        r = struct.unpack_from("<I", b, k)[0]
        self.root = list(struct.unpack_from("<20I", b, k + r))
        leaves, inner = [], []
        for o, n in GM.walk(b):
            (leaves if n[7] & 2 else inner).append(n)
        self.inner = list(next(n for n in inner if n[7] == 5))
        first_chunk = min(n[8] for n in leaves) + k
        self.head = bytearray(b[:first_chunk])  # header + parameter block, copied as is
        for n in leaves:
            if n[7] != 0x103 or n[13] != 0:
                continue
            codes = list(GM.vif_codes(b, k + n[8]))
            sh = tuple((w >> 24) & 0x7F for _, w in codes)
            if sh[:12] != SHAPE or any(sh[12:]):
                continue
            regs = (codes[3][1] >> 16) & 0xFF
            if regs != 5:
                continue
            p_rt, p_rg, p_vt = codes[2][0], codes[3][0], codes[5][0]
            self.leaf = list(n)
            self.reg_tag = b[p_rt + 4:p_rt + 20]
            self.regs = b[p_rg + 4:p_rg + 4 + 12 * regs]
            self.vtx_tag = list(struct.unpack_from("<4I", b, p_vt + 4))
            self.codes = [w for _, w in codes]
            return
        raise ValueError("no template leaf of the expected type")


def _regs(t: Template, override):
    """The template leaf's 5 GS register writes (lo, hi, register id) with some replaced: {register id: u64}."""
    if not override:
        return t.regs
    out = bytearray(t.regs)
    for i in range(len(out) // 12):
        r = struct.unpack_from("<I", out, 12 * i + 8)[0] & 0xFF
        if r in override:
            struct.pack_into("<2I", out, 12 * i, override[r] & 0xFFFFFFFF, override[r] >> 32)
    return bytes(out)


def _chunk(t: Template, verts, regs=None):
    """One leaf's DMA/VIF chunk for verts [(pos rel. centre * 16 ints, w flags, (u, v), (r, g, b, a))];
    regs: GS register values replacing the template's ({0x42: ALPHA, 0x47: TEST, ...})."""
    n, R = len(verts), 5
    out = bytearray(8)  # DMA tag lo/hi, filled at the end
    w = lambda x: out.extend(struct.pack("<I", x))
    w(0x02000000)
    w(0x01000101)
    w(0x6C01C000)
    out += t.reg_tag
    w(0x6800C001 | (R << 16))
    out += _regs(t, regs)
    w(0x01000103)
    w(0x6C01C000 | (1 + R))
    v0, v1, v2, _ = t.vtx_tag
    out += struct.pack("<4I", (v0 & ~0x7FFF) | 0x8000 | n, v1, v2, 3 * n)
    w(0x64008000 | (n << 16) | (2 + R))
    for _, _, (u, v), _ in verts:
        out += struct.pack("<2i", int(round(u * 4096)), int(round(v * 4096)))
    w(0x6E00C000 | (n << 16) | (3 + R))
    for _, _, _, c in verts:
        out += bytes(c)
    w(0x05000001)
    w(0x6D008000 | (n << 16) | (4 + R))
    for p, fl, _, _ in verts:
        out += struct.pack("<3hH", *p, fl)
    w(0x05000000)
    w(0x14000008)
    out += bytes(-len(out) % 16)
    field = 3 * n + 2 + R
    qwc = (len(out) - 16) // 16
    struct.pack_into("<2I", out, 0, 0x60000000 | (field << 16) | qwc, 0)
    return bytes(out), field


def _pack_leaves(strips):
    """strips [(material, verts)] -> leaves [(material, [strip verts...])], each <= MAX_VERTS, one cell."""
    by = collections.defaultdict(list)
    for mat, vs in strips:
        c = tuple(sum(v[0][i] for v in vs) / len(vs) for i in range(3))
        # height is part of the bucket too: a leaf's positions are 16-bit offsets from its centre (tall levels)
        by[(mat, math.floor(c[0] / CELL), math.floor(c[2] / CELL), math.floor(c[1] / CELL))].append(vs)
    leaves = []
    for (mat, cx, cz, _cy), group in by.items():
        cur, n = [], 0
        for vs in group:
            if n + len(vs) > MAX_VERTS and cur:
                leaves.append((mat, (cx, cz), cur))
                cur, n = [], 0
            cur.append(vs)
            n += len(vs)
        if cur:
            leaves.append((mat, (cx, cz), cur))
    return leaves


def write(template: bytes, strips, tex_index, name_prefix="gen", styles=None):
    """strips: [(material, [(pos, uv, col)])]; tex_index: material -> (group index, texture index) (1-based,
    as in the zone's texture dictionary) -> geom bytes (texture registers not yet bound).
    styles: material -> (GS register overrides {id: u64}, extra leaf flag bits), e.g. blended materials."""
    styles = styles or {}
    t = Template(template)
    k = t.k
    leaves = _pack_leaves(strips)
    body = bytearray(t.head)
    recs = []  # (cell, leaf node words)
    for i, (mat, cell, group) in enumerate(leaves):
        ps = [v[0] for vs in group for v in vs]
        lo = [min(p[j] for p in ps) for j in range(3)]
        hi = [max(p[j] for p in ps) for j in range(3)]
        c = [(a + b) / 2 for a, b in zip(lo, hi)]
        half = [(b - a) / 2 for a, b in zip(lo, hi)]
        assert max(half) < 2040, f"leaf too large ({half})"
        verts = []
        for vs in group:
            for j, (p, uv, col) in enumerate(vs):
                q = tuple(int(round((p[a] - c[a]) * 16)) for a in range(3))
                fl = (0x8000 if j < 2 else 0) | (0x20 if j & 1 else 0)
                verts.append((q, fl, uv, col))
        # keep UVs small: shift by whole repeats
        du, dv = math.floor(min(v[2][0] for v in verts)), math.floor(min(v[2][1] for v in verts))
        verts = [(q, fl, (u - du, v - dv), col) for q, fl, (u, v), col in verts]
        regs, extra = styles.get(mat, (None, 0))
        chunk, field = _chunk(t, verts, regs)
        off = len(body) - k
        body += chunk
        n = list(t.leaf)
        n[0:7] = [struct.unpack("<I", struct.pack("<f", x))[0] for x in c + [math.sqrt(sum(h * h for h in half))] + half]
        n[7] = 0x103 | extra
        n[8] = off
        n[9] = (t.leaf[9] & 0xFC000000) | (field << 16)
        g, ti = tex_index[mat]
        n[11], n[17] = g, ti
        n[12] = H(f"{name_prefix}_leaf{i}")
        recs.append((cell, n, lo, hi))
    # node area: root, inner nodes (one per cell), leaves
    node_base = len(body) - k
    cells = sorted({r[0] for r in recs})
    root_off = node_base
    inner_off = {c: node_base + 0x50 * (1 + i) for i, c in enumerate(cells)}
    leaf_off = node_base + 0x50 * (1 + len(cells))
    nodes = bytearray()
    root = list(t.root)
    root[8] = inner_off[cells[0]] if cells else NONE
    nodes += struct.pack("<20I", *root)
    by_cell = collections.defaultdict(list)
    for idx, r in enumerate(recs):
        by_cell[r[0]].append(idx)
    order = [i for c in cells for i in by_cell[c]]
    pos_of = {i: leaf_off + 0x50 * j for j, i in enumerate(order)}
    for ci, c in enumerate(cells):
        idxs = by_cell[c]
        lo = [min(recs[i][2][j] for i in idxs) for j in range(3)]
        hi = [max(recs[i][3][j] for i in idxs) for j in range(3)]
        cen = [(a + b) / 2 for a, b in zip(lo, hi)]
        half = [(b - a) / 2 for a, b in zip(lo, hi)]
        n = list(t.inner)
        n[0:7] = [struct.unpack("<I", struct.pack("<f", x))[0] for x in cen + [math.sqrt(sum(h * h for h in half))] + half]
        n[8] = pos_of[idxs[0]]
        n[10] = inner_off[cells[ci + 1]] if ci + 1 < len(cells) else NONE
        n[12] = H(f"{name_prefix}_cell{ci}")
        nodes += struct.pack("<20I", *n)
    for c in cells:
        idxs = by_cell[c]
        for j, i in enumerate(idxs):
            n = recs[i][1]
            n[10] = pos_of[idxs[j + 1]] if j + 1 < len(idxs) else NONE
            nodes += struct.pack("<20I", *n)
    body += nodes
    struct.pack_into("<I", body, k, root_off)
    return bytes(body), {"leaves": len(recs), "cells": len(cells)}
