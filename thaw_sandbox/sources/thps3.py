"""Tony Hawk's Pro Skater 3 (PS2, NTSC-U SLUS-20013) as a level source.

THPS3 runs on RenderWare: a level is a world (pre\\<code>bsp.pre: levels\\<code>\\<code>.bsp + .tex dictionary;
the .dff clump of movable objects is not used yet) and a Neversoft node file (pre\\<code>.pre:
levels\\<code>\\<code>.qb, read with the THPS4 QB reader). There is no Neversoft geometry to convert, so the level
is rebuilt like a generated one (thaw_sandbox.mapgen): the world's triangles become a Scene (render + collision
from the same faces, Neversoft face flags kept), its textures go into THAW texture groups, restarts and rails
come from the node file. Node positions have Z mirrored against the world (as in THPS4).
"""
import math
import struct

from thaw_sandbox import iso_manager as I, level_convert as LC, pak, qb_data as QD, qb_parser as Q, rw
from thaw_sandbox import thaw_tex as TT, thps4_qb, thug2_qb, zone
from thaw_sandbox.mapgen import col_writer, geom_writer, nodes as gen_nodes, scene as S
from thaw_sandbox.sources.thps4 import read_pre
from thaw_sandbox.sources.thug2 import _hed

GAME = "THPS3"
GENERATION = 3
SERIALS = ("SLUS_200.13",)
LEVELS = ("foun", "can", "rio", "sub", "si", "ap", "la", "tok", "shp", "ware", "burn", "ros")
NAMES = {"foun": "Foundry", "can": "Canada", "rio": "Rio", "sub": "Suburbia", "si": "Skater Island",
         "ap": "Airport", "la": "Los Angeles", "tok": "Tokyo", "shp": "Cruise Ship", "ware": "Warehouse",
         "burn": "Burnside", "ros": "Roswell"}
ORIGIN = {"ap": "thps3:airport", "can": "thps3:canada", "la": "thps3:los_angeles"}
ZONE_HINTS = {"foun": "z_fo", "can": "z_cn", "rio": "z_ri", "sub": "z_su", "si": "z_si", "ap": "z_a3",
              "la": "z_l3", "tok": "z_tk", "shp": "z_sh", "ware": "z_wa", "burn": "z_bu", "ros": "z_rs"}

# Neversoft face flags (THPS3/THPS4 collision): 0x10 not collidable, 0x80 camera collide (inverted against later
# games, as thps4_col), 0x1000 invisible
NON_COLLIDABLE, CAMERA, INVISIBLE = 0x10, 0x80, 0x1000
MAX_EDGE = 900.0  # render leaves and collision objects store 16-bit offsets: split longer triangles


def detect(iso):
    try:
        cnf = I.read_file(iso, "/SYSTEM.CNF;1")
    except Exception:
        return False
    return any(s.encode() in cnf for s in SERIALS)


def _split(p, uv, col):
    """Split a triangle at its longest edge until every edge is at most MAX_EDGE."""
    e = max(range(3), key=lambda i: math.dist(p[i], p[(i + 1) % 3]))
    if math.dist(p[e], p[(e + 1) % 3]) <= MAX_EDGE:
        return [(p, uv, col)]
    a, b, c = e, (e + 1) % 3, (e + 2) % 3
    mid = lambda x, y: tuple((u + v) / 2 for u, v in zip(x, y))
    mp, mu, mc = mid(p[a], p[b]), mid(uv[a], uv[b]), tuple(int(v) for v in mid(col[a], col[b]))
    out = []
    for t in (((p[a], mp, p[c]), (uv[a], mu, uv[c]), (col[a], mc, col[c])),
              ((mp, p[b], p[c]), (mu, uv[b], uv[c]), (mc, col[b], col[c]))):
        out += _split(*t)
    return out


def world_scene(world):
    """RenderWare world -> mapgen Scene (materials named by texture) and per-material vertex colour factor."""
    sc = S.Scene()
    for m in world.materials:
        if m.texture:
            sc.materials.setdefault(m.texture.lower(), S.Material(m.texture.lower()))
    for sec in world.sectors:
        for (mi, a, b, c), fl in zip(sec.tris, sec.flags):
            mat = world.materials[mi] if mi < len(world.materials) else None
            if mat is None or not mat.texture:
                continue
            mc = mat.colour
            idx = (a, b, c)  # RenderWare winding = mapgen's front-face rule (checked: floors face up)
            p = tuple(sec.verts[i] for i in idx)
            uv = tuple(sec.uvs[i] if sec.uvs else (0.0, 0.0) for i in idx)
            if not all(map(math.isfinite, (x for q in p + uv for x in q))):
                continue  # Canada has a few NaN vertices / UVs
            if max(abs(x) for q in uv for x in q) > 30000:  # UVs THAW's fixed point (x 4096, 32-bit) cannot hold
                uv = ((0.0, 0.0),) * 3
            # RenderWare prelit colours: 255 = full; THAW vertex colours: 128 = 1.0 (material colours: 128 = 1.0)
            col = tuple(tuple(min(255, sec.colours[i][k] * mc[k] // 255) for k in range(3)) +
                        (min(128, sec.colours[i][3] // 2 + 1),) for i in idx)
            for pp, uu, cc in _split(p, uv, col):
                sc.tris.append(S.Tri(pp, uu, cc, mat.texture.lower(), (fl ^ CAMERA) & 0xFFFF, 0,
                                     render=not fl & INVISIBLE, collide=not fl & NON_COLLIDABLE))
    return sc


def node_scene(sc, qb):
    """Restarts and rails from the THPS3 node file into the scene (Z mirrored to the world's frame)."""
    H = Q.qbcrc
    q = thug2_qb.parse(thps4_qb.to_thug2(qb))
    na = max((v for v in q.data.values() if isinstance(v, QD.Array)), key=lambda a: len(a.items))
    ns = [{k: v for k, v in s.items} for s in na.items if isinstance(s, QD.Struct)]
    cls = lambda d: getattr(d.get(H("Class")), "crc", None)
    pos = lambda d: (lambda p: (p[0], p[1], -p[2]))(d.get(H("Position")) or d.get(H("Pos")) or (0.0, 0.0, 0.0))
    for d in ns:
        if cls(d) == H("Restart"):
            ang = d.get(H("Angles")) or (0.0, 0.0, 0.0)
            sc.starts.append((pos(d), -ang[1] + math.pi))
    rails = {i for i, d in enumerate(ns) if cls(d) == H("RailNode")}
    linked = {}
    for i in rails:
        lk = d.get(H("links")) if (d := ns[i]) else None
        nxt = [j for j in (lk.items if isinstance(lk, QD.Array) else []) if j in rails]
        linked[i] = nxt
    has_prev = {j for v in linked.values() for j in v}
    seen = set()
    for start in sorted(rails, key=lambda i: (i in has_prev, i)):
        if start in seen:
            continue
        chain, i = [], start
        while i is not None and i not in seen:
            seen.add(i)
            chain.append(pos(ns[i]))
            i = linked[i][0] if linked[i] else None
        if i is not None:  # closed loop
            chain.append(pos(ns[i]))
        if len(chain) >= 2:
            sc.rails.append(S.Rail(chain, "TERRAIN_GRINDMETAL"))
    return sc


class Source:
    GAME = GAME
    GENERATION = GENERATION
    ORIGIN = ORIGIN
    ZONE_HINTS = ZONE_HINTS
    PREBUILT = True  # build_zone makes the zone (no Neversoft files to convert)

    def __init__(self, iso, cache_dir):
        self.iso = iso
        self.hed = _hed(I.read_file(iso, "/SKATE3.HED;1"))
        self.wad_off, _ = I.file_extent(iso, "/SKATE3.WAD;1")

    def read(self, name):
        off, size = self.hed[name.lower()]
        with open(self.iso, "rb") as f:
            f.seek(self.wad_off + off)
            return f.read(size)

    def levels(self):
        return [(c, NAMES[c]) for c in LEVELS]

    all_levels = levels

    def level_parts(self, code):
        world = read_pre(self.read(f"\\pre\\{code}bsp.pre"))
        lv = read_pre(self.read(f"\\pre\\{code}.pre"))
        get = lambda files, ext: next(v for k, v in files.items() if k.endswith(f"\\{code}{ext}"))
        return rw.read_world(get(world, ".bsp")), rw.read_textures(get(world, ".tex")), get(lv, ".qb")

    def build_zone(self, code, template_zone, zone_name, template, disc=None):
        world, texs, qb = self.level_parts(code)
        sc = node_scene(world_scene(world), qb)
        mats = sorted(sc.materials)
        grey = rw.Texture("grey", 8, 8, 0x14, 0, LC.GREY, [bytes(32)])
        group = Q.qbcrc(f"{zone_name}_thps3")
        new = []
        for m in mats:
            src = texs.get(m, grey)
            new.append(TT.NewTexture(Q.qbcrc(f"{zone_name}_{m}"), src.width, src.height, src.psm, src.cpsm, src.clut,
                                     src.mips[:4], group=group))
        TT.split_groups(new)
        tex = TT.write(new)
        order = list(dict.fromkeys(t.group for t in new))
        pos_in = {}
        for t in new:
            pos_in.setdefault(t.group, []).append(t.crc)
        tex_index = {m: (order.index(t.group) + 1, pos_in[t.group].index(t.crc) + 1) for m, t in zip(mats, new)}
        tab = zone.entries(template_zone)
        big = LC._biggest(template_zone, tab)
        gp = pak.data_pos(big[".geom"], 0)
        geom, gst = geom_writer.write(template_zone[gp:gp + big[".geom"].size], sc.render_items(), tex_index,
                                      name_prefix=zone_name)
        col = col_writer.write(sc.collision_tris(), name_prefix=zone_name)
        zb, st = LC.assemble_level(template_zone, tex, geom, col, gen_nodes.build(sc, zone_name), zone_name, template)
        st.update(gst)
        st["rails"] = len(sc.rails)
        st["starts"] = len(sc.starts)
        st["missing textures"] = sum(1 for m in mats if m not in texs)
        return zb, st
