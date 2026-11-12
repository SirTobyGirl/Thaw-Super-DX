"""THUG2 PC / Xbox level files (.scn.xbx scenes, .tex.xbx texture dictionaries), as used by THUG Pro custom levels.

Layouts as io_thps_scene reads them (import_thug2.py, material.py, tex.py), little endian:

scene  = 3 x u32, u32 material count, materials, i32 sector count, sectors, i32 hierarchy count
material = u32 checksum, u32 name checksum, u32 passes, u32 alpha cutoff, u8 sorted, f32 draw order, u8 single sided,
           u8 no backface culling, i32 z bias, u8 grassify [f32 height, i32 layers], f32 specular power [3 f32],
           passes: u32 texture checksum, u32 flags, u8 has colour, 3 f32 colour, u32 blend mode, u32 fixed alpha,
           u32 u/v addressing, 2 f32 envmap multiples, u32 filtering, [uv wibble 8 f32], [pass 0 vc wibble],
           [animated texture], mipmap info 4 x u32
sector = u32 checksum, i32 bone, u32 flags (0x01 UVs, 0x02 colours, 0x04 normals, 0x10 weights, 0x800 colour wibble,
         0x800000 billboard), u32 meshes, bbox, sphere, [billboard: u32 type, 9 f32], meshes
mesh   = centre, radius, bbox, u32 flags, u32 material checksum, u32 LODs; per LOD: u32 n + n u16, u16 m + m u16
         (triangle strip), 14 bytes, u8 stride, u16 vertices, u16 buffers, buffers {i32 size; vertices: 3 f32 position,
         [weights], [normal], [b g r a, 128 = 1.0], uv sets 2 f32}, i32, i32, 3 bytes, u8 wibble [vertices bytes],
         i32, i32 pixel shader [i32, i32 n, n bytes]
texture dictionary = i32 version, i32 count; per texture u32 checksum, width, height, levels, texel depth, palette
         depth, DXT version (1, 2 = DXT1, 5), palette size, palette, levels x {u32 size, data}
Positions are THUG2's own frame (as its collision and nodes), which THAW shares.
"""
import struct

from thaw_sandbox import rw


class _R:
    def __init__(self, b):
        self.b, self.o = b, 0

    def __call__(self, fmt):
        v = struct.unpack_from("<" + fmt, self.b, self.o)
        self.o += struct.calcsize("<" + fmt)
        return v if len(v) != 1 else v[0]


def _material(r):
    crc, name, passes, _cut = r("4I")
    r("B"), r("f"), r("B"), r("B"), r("i")
    if r("B"):
        r("fi")
    if r("f") > 0.0:
        r("3f")
    out = []
    for j in range(passes):
        tex, flags = r("2I")
        r("B")
        colour = r("3f")
        blend, fix = r("2I")
        r("2I"), r("2f"), r("I")
        if flags & 0x1:
            r("8f")
        if j == 0 and flags & 0x2:
            for _ in range(r("I")):
                keys = r("I")
                r("i")
                r(f"{2 * keys}i")
        if flags & 0x800:
            keys = r("i")
            r("3i")
            r(f"{2 * keys}I")
        r("4I")
        out.append((tex, flags, blend, fix & 0xFF, colour))
    return crc, out


def read_scene(b: bytes):
    """-> (materials {checksum: [(texture crc, flags, blend mode, fixed alpha, colour)]},
    [(sector checksum, material checksum, [(pos, (u, v), (r, g, b, a))] per triangle)])"""
    r = _R(b)
    r("3I")
    mats = dict(_material(r) for _ in range(r("I")))
    tris = []
    for _ in range(r("i")):
        sec, _bone, flags, meshes = r("IiII")
        r("10f")
        if flags & 0x800000:
            r("I"), r("9f")
        for _ in range(meshes):
            r("4f"), r("6f")
            _mflags, mat, lods = r("3I")
            for k in range(lods):
                r(f"{r('I')}H")
                strip = r(f"{r('H')}H")
                strip = strip if isinstance(strip, tuple) else (strip,)
                r("14x")
                stride, nv, nbuf = r("BHH")
                verts = []
                for bi in range(nbuf):
                    if bi:
                        r.o += 1
                    r("i")
                    for _ in range(nv):
                        start = r.o
                        pos = r("3f")
                        if flags & 0x10:
                            r("I4H")
                            if flags & 0x04:
                                r("I")
                        elif flags & 0x04:
                            r("3f")
                        col = (128, 128, 128, 128)
                        if flags & 0x02:
                            bb, g, rr, a = r("4B")
                            col = (rr, g, bb, a)
                        uv = (0.0, 0.0)
                        if flags & 0x01:
                            n_uv = (stride - (r.o - start)) // 8
                            if n_uv > 0:
                                uv = r("2f")
                                r.o += 8 * (n_uv - 1)
                        r.o = start + stride
                        if bi == 0:
                            verts.append((pos, uv, col))
                r("2i"), r("3B")
                if r("B"):
                    r.o += nv
                r("i")
                if r("i") == 1:  # pixel shader: i32, i32 n, n bytes
                    r("i")
                    n = r("i")  # (not "r.o += r(...)": r.o would be read before the call advances it)
                    r.o += n
                if k:
                    continue  # lower levels of detail
                for i in range(2, len(strip)):
                    a, c1, c2 = strip[i - 2], strip[i - 1], strip[i]
                    if len({a, c1, c2}) < 3 or max(a, c1, c2) >= len(verts):
                        continue
                    t = (a, c1, c2) if i % 2 == 0 else (a, c2, c1)
                    tris.append((sec, mat, [verts[x] for x in t]))
    return mats, tris


# ---------------------------------------------------------------- textures

def _c565(v):
    return ((v >> 11 & 31) * 255 // 31, (v >> 5 & 63) * 255 // 63, (v & 31) * 255 // 31)


def _dxt(data, w, h, version):
    """DXT1 / DXT5 -> RGBA bytes rows (alpha 0..255)."""
    out = bytearray(w * h * 4)
    bs = 8 if version == 1 else 16
    o = 0
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            alpha = None
            if version == 5:
                a0, a1 = data[o], data[o + 1]
                bits = int.from_bytes(data[o + 2:o + 8], "little")
                if a0 > a1:
                    pal = [a0, a1] + [((6 - i) * a0 + (1 + i) * a1) // 7 for i in range(6)]
                else:
                    pal = [a0, a1] + [((4 - i) * a0 + (1 + i) * a1) // 5 for i in range(4)] + [0, 255]
                alpha = [pal[bits >> (3 * i) & 7] for i in range(16)]
                c = o + 8
            else:
                c = o
            v0, v1, idx = struct.unpack_from("<HHI", data, c)
            c0, c1 = _c565(v0), _c565(v1)
            if v0 > v1 or version == 5:
                cols = [c0 + (255,), c1 + (255,), tuple((2 * x + y) // 3 for x, y in zip(c0, c1)) + (255,),
                        tuple((x + 2 * y) // 3 for x, y in zip(c0, c1)) + (255,)]
            else:
                cols = [c0 + (255,), c1 + (255,), tuple((x + y) // 2 for x, y in zip(c0, c1)) + (255,), (0, 0, 0, 0)]
            for i in range(16):
                x, y = bx + (i & 3), by + (i >> 2)
                if x < w and y < h:
                    px = cols[idx >> (2 * i) & 3]
                    if alpha is not None:
                        px = px[:3] + (alpha[i],)
                    out[4 * (y * w + x):4 * (y * w + x) + 4] = bytes(px)
            o += bs
    return out


def _halve(px, w, h):
    out = bytearray((w // 2) * (h // 2) * 4)
    for y in range(h // 2):
        for x in range(w // 2):
            for ch in range(4):
                s = sum(px[4 * ((2 * y + dy) * w + 2 * x + dx) + ch] for dy in (0, 1) for dx in (0, 1))
                out[4 * (y * (w // 2) + x) + ch] = s // 4
    return out, w // 2, h // 2


def read_textures(b: bytes, max_size=256) -> dict:
    """{texture checksum: rw.Texture (8-bit palettised, GS-ready palette)}; DXT1/DXT5 only, larger than
    max_size scaled down by halving."""
    r = _R(b)
    _ver, n = r("2i")
    out = {}
    for _ in range(n):
        crc, w, h, levels, _td, _pd, dxt, psize = r("8I")
        r.o += psize
        first = None
        for j in range(levels):
            size = r("I")
            if j == 0:
                first = b[r.o:r.o + size]
            r.o += size
        dxt = 1 if dxt == 2 else dxt
        if dxt not in (1, 5) or psize or first is None:
            continue
        px = _dxt(first, w, h, dxt)
        while max(w, h) > max_size:
            px, w, h = _halve(px, w, h)
        rgba = [(px[i], px[i + 1], px[i + 2], (px[i + 3] + 1) // 2) for i in range(0, len(px), 4)]
        out[crc] = rw.palettise(w, h, rgba, f"{crc:08x}")
    return out
