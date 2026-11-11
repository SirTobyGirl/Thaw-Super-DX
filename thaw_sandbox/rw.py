"""RenderWare 3.1 (PS2) as used by Tony Hawk's Pro Skater 3: level worlds (.bsp) and texture dictionaries (.tex).

Chunks are {u32 type, u32 size, u32 version 0x310} + data.

World (0x0B): Struct {u32 root is sector, vec3 -origin, f32 ambient/specular/diffuse, u32 triangles, vertices,
plane sectors, atomic sectors, coll sector size, u32 format}, MaterialList, a tree of PlaneSect (0x0A) /
AtomicSect (0x09). Format flags: 0x01 tristrip, 0x04 textured, 0x08 prelit, 0x10 normals, 0x40 modulate material
colour, 0x80 two UV sets.
AtomicSect Struct: {u32 material base, u32 triangles, u32 vertices, vec3 bbox, vec3 bbox, u32 coll, u32 0} then
vertices (3 f32), normals (4 bytes), prelit colours (r g b a), UV sets (2 f32 each), triangles
{u16 material, u16 a, b, c}. Its Extension holds Neversoft's chunk 0x294AF01: {u32, u16 face flags per triangle,
...} (flags: 0x10 not collidable, 0x80 camera collide - inverted against later games, 0x1000 invisible).
Material: Struct {u32 0, rgba, u32, u32 textured, f32 x3}, Texture {Struct, String name, String mask}.

Texture dictionary (0x16): Struct {u16 count, u16 0}, Rasters (0x15): Struct {'PS2\\0', u32 filter},
String name, String mask, Struct {Struct 64-byte header {w, h, depth, raster format, u64 TEX0, ...,
u32 pixel bytes, u32 palette bytes, ...}, Struct pixels + palette}. THPS3's rasters are linear palettised
images (raster format 0x4000 = 4-bit, 0x2000 = 8-bit; 0x0500 CT32 palette, 0x0100 CT16; 0x8000 mipmaps),
palettes stored as the GS takes them (thug2_tex conventions), so they feed thaw_tex directly.
"""
import struct
from dataclasses import dataclass, field

SECTOR, PLANE, WORLD, MATLIST, MATERIAL, TEXTURE, STRING, STRUCT, EXT = 9, 10, 11, 8, 7, 6, 2, 1, 3
NS_EXT = 0x294AF01


def chunks(b, o, end):
    while o + 12 <= end:
        t, s, _v = struct.unpack_from("<3I", b, o)
        yield t, o + 12, s
        o += 12 + s


def _child(b, o, s, typ):
    return next(((p, n) for t, p, n in chunks(b, o, o + s) if t == typ), (None, 0))


def _string(b, o, s):
    return b[o:o + s].split(b"\0")[0].decode("latin1")


@dataclass
class Material:
    texture: str
    colour: tuple
    ext: bytes = b""


@dataclass
class Sector:
    verts: list
    colours: list
    uvs: list
    tris: list          # (material index, a, b, c)
    flags: list         # per triangle (0 if absent)
    name: int = 0       # sector checksum (LevelGeometry node names)


@dataclass
class World:
    format: int
    materials: list = field(default_factory=list)
    sectors: list = field(default_factory=list)


def read_world(b: bytes) -> World:
    t, o, s = next(chunks(b, 0, len(b)))
    assert t == WORLD, t
    so, _ = _child(b, o, s, STRUCT)
    fmt = struct.unpack_from("<I", b, so + 48)[0]
    w = World(fmt)
    mo, ms = _child(b, o, s, MATLIST)
    for t, p, n in chunks(b, mo, mo + ms):
        if t != MATERIAL:
            continue
        st, _ = _child(b, p, n, STRUCT)
        colour = tuple(b[st + 4:st + 8])
        name = ""
        to, tn = _child(b, p, n, TEXTURE)
        if to is not None:
            strs = [(q, m) for tt, q, m in chunks(b, to, to + tn) if tt == STRING]
            name = _string(b, *strs[0]) if strs else ""
        eo, en = _child(b, p, n, EXT)
        w.materials.append(Material(name, colour, b[eo:eo + en] if eo is not None else b""))

    def tree(o, end):
        for t, p, n in chunks(b, o, end):
            if t == PLANE:
                tree(p, p + n)
            elif t == SECTOR:
                w.sectors.append(_sector(b, p, n, fmt))
    tree(o, o + s)
    return w


def _sector(b, o, s, fmt):
    so, _ = _child(b, o, s, STRUCT)
    base, nt, nv = struct.unpack_from("<3I", b, so)
    p = so + 44
    verts = [struct.unpack_from("<3f", b, p + 12 * i) for i in range(nv)]
    p += 12 * nv
    if fmt & 0x10:
        p += 4 * nv
    colours = [tuple(b[p + 4 * i:p + 4 * i + 4]) for i in range(nv)] if fmt & 0x08 else [(128, 128, 128, 255)] * nv
    if fmt & 0x08:
        p += 4 * nv
    uvs = []
    if fmt & 0x84:
        uvs = [struct.unpack_from("<2f", b, p + 8 * i) for i in range(nv)]
        p += 8 * nv * (2 if fmt & 0x80 else 1)
    tris = []
    for i in range(nt):
        m, a, bb, c = struct.unpack_from("<4H", b, p + 8 * i)
        tris.append((base + m, a, bb, c))
    flags, name = [0] * nt, 0
    eo, en = _child(b, o, s, EXT)
    if eo is not None:
        no, nn = _child(b, eo, en, NS_EXT)
        if no is not None and nn >= 4 + 2 * nt:
            flags = list(struct.unpack_from(f"<{nt}H", b, no + 4))
            q = no + 4 + 2 * nt
            if nn >= 4 + 2 * nt + 8:
                name = struct.unpack_from("<I", b, q + 4)[0]
    return Sector(verts, colours, uvs, tris, flags, name)


@dataclass
class Texture:
    """Linear palettised texture in thug2_tex.Texture form (what thaw_tex / mapgen.texlib take)."""
    name: str
    width: int
    height: int
    psm: int
    cpsm: int
    clut: bytes
    mips: list
    crc: int = 0
    group: int = 0
    flags: int = 0


def read_textures(b: bytes) -> dict:
    """{lower-case texture name: Texture}; rasters this reader does not handle are left out."""
    t, o, s = next(chunks(b, 0, len(b)))
    assert t == 0x16, t
    out = {}
    for t, p, n in chunks(b, o, o + s):
        if t != 0x15:
            continue
        parts = list(chunks(b, p, p + n))
        strs = [(q, m) for tt, q, m in parts if tt == STRING]
        name = _string(b, *strs[0]).lower()
        outer = [(q, m) for tt, q, m in parts if tt == STRUCT][1]
        (_, ho, hs), (_, do, ds) = list(chunks(b, outer[0], outer[0] + outer[1]))[:2]
        w, h, depth, rf = struct.unpack_from("<4I", b, ho)
        pix, pal = struct.unpack_from("<2I", b, ho + 48)
        if depth not in (4, 8) or pix + pal > ds:
            continue
        psm = 0x14 if depth == 4 else 0x13
        cpsm = 0x00 if rf & 0xF00 == 0x500 else 0x02
        data = b[do:do + ds]
        mips, q, mw, mh = [], 0, w, h
        while q + max(1, mw * mh * depth // 8) <= pix and mw >= 1 and mh >= 1 and len(mips) < 7:
            nb = mw * mh * depth // 8
            mips.append(data[q:q + nb])
            q += nb
            if not rf & 0x8000:
                break
            mw, mh = mw // 2, mh // 2
        clut = data[pix:pix + pal]
        if not mips or len(clut) != (16 if depth == 4 else 256) * (4 if cpsm == 0 else 2):
            continue
        out[name] = Texture(name, w, h, psm, cpsm, clut, mips)
    return out
