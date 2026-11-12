"""Tony Hawk's Pro Skater 3 (PS2, NTSC-U SLUS-20013) as a level source.

THPS3 runs on RenderWare: a level is a world (pre\\<code>bsp.pre: levels\\<code>\\<code>.bsp + .tex dictionary;
the .dff clump of movable objects is not used yet) and a Neversoft .qb holding both the nodes and the level's
scripts (pre\\<code>.pre, read with the THPS4 QB reader).
The world becomes THAW geometry and collision through mapgen's writers (thaw_sandbox.rw reads it):
  * every triangle collides per its Neversoft face flags; materials flagged 0x02 (CR_Collision, CR_TriggerPlane,
    untextured proxies) and invisible faces are not drawn
  * materials keep their GS blend mode (additive / subtractive / fixed: own ALPHA register); decals (0x10) and
    blended materials are drawn after the surfaces they lie on; terrain types (sounds) carry over
  * trigger faces keep their flag only in sectors whose node has a TriggerScript; their collision objects take the
    sector's name, which is how the engine finds the node when the skater touches them
Nodes, rails, restarts, the level scripts (gaps, breakable glass, ...) and the gap list are then converted by
level_convert.convert_level like THPS4's (prebuilt geometry). EnvironmentObject (THPS3's level geometry nodes)
and objects THAW cannot spawn become Waypoints, keeping their TriggerScript. Node Z is mirrored as in THPS4.
"""
import math

from thaw_sandbox import geom as GM, iso_manager as I, level_convert as LC, pak, qb_data as QD, qb_parser as Q, rw
from thaw_sandbox import thaw_tex as TT, thps4_qb, thug2_qb, zone
from thaw_sandbox.mapgen import col_writer, geom_writer, scene as S
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
# 0x40 trigger: the engine then runs the TriggerScript of the node named like the collision object (THPS3: the
# sector's LevelGeometry node). Sectors are merged into generated collision objects and the level scripts are not
# converted yet, so the lookup found no node and read a null struct (FUN_002419a0 -> FUN_002ae260): cleared.
TRIGGER = 0x40
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


def ns_material(m):
    """Neversoft's material chunk -> (flag byte, GS ALPHA blend byte, FIX, terrain). Flag byte: 0x02 collision-only mesh
    (CR_TriggerPlane, CR_Collision, untextured proxies), 0x08 transparent, 0x10 decal. ALPHA as the GS register's
    low byte: 0x00/0x0A/0x44 normal, 0x48/0x68 additive, 0x42/0x62 subtractive, 0x64 fixed blend (FIX = factor).
    Terrain (byte 20) uses Neversoft's standard list (1 CONCSMOOTH ... 38 METALFENCE), as THUG2/THAW collision does.
    Blend offsets as neversoft-multitool reads them (bytes 37 and 41)."""
    for t, o, n in rw.chunks(m.ext, 0, len(m.ext)):
        if t == rw.NS_EXT and n >= 44:
            d = m.ext[o:o + n]
            return d[19], d[37], d[41], d[20] if d[20] < 39 else 0
    return 0, 0, 0, 0


NORMAL_BLENDS = (0x00, 0x0A, 0x44)  # drawn as the template leaf's ALPHA 0x44 + alpha test


def material_key(m):
    """Scene material name: the texture, plus the blend mode when it differs from normal drawing."""
    _, gs, fix, _ = ns_material(m)
    tex = m.texture.lower()
    return tex if gs in NORMAL_BLENDS else f"{tex}#{gs:02x}{fix:02x}"


def world_scene(world, triggers=frozenset()):
    """RenderWare world -> (mapgen Scene, styles {material key: (GS register overrides, leaf flag bits)}).
    Collision comes from the face flags of every triangle; drawing skips collision-only materials, untextured
    ones and invisible faces. triggers: sector names whose node has a TriggerScript: their faces keep the trigger
    flag and their collision objects take the sector's name (other trigger flags are cleared)."""
    sc = S.Scene()
    sc.late = set()
    styles = {}
    info = []
    for m in world.materials:
        mflags, gs, fix, terrain = ns_material(m)
        key = material_key(m)
        draw = bool(m.texture) and not mflags & 0x02
        if draw:
            sc.materials.setdefault(key, S.Material(key))
            if gs not in NORMAL_BLENDS:
                styles[key] = ({0x42: gs | fix << 32}, 0)
            if mflags & 0x10 or gs not in NORMAL_BLENDS:
                sc.late.add(key)  # decals and blended surfaces: drawn after the surfaces they lie on
        info.append((key, draw, terrain))
    for sec in world.sectors:
        trig = sec.name in triggers
        for (mi, a, b, c), fl in zip(sec.tris, sec.flags):
            mat = world.materials[mi] if mi < len(world.materials) else None
            if mat is None:
                continue
            key, draw, terrain = info[mi]
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
            render, collide = draw and not fl & INVISIBLE, not fl & NON_COLLIDABLE
            if not render and not collide:
                continue
            flags = (fl ^ CAMERA) & (0xFFFF if trig else ~TRIGGER & 0xFFFF)
            for pp, uu, cc in _split(p, uv, col):
                t = S.Tri(pp, uu, cc, key, flags, terrain, render=render, collide=collide)
                if trig:
                    t.obj = sec.name
                sc.tris.append(t)
    return sc, styles


def add_objects(sc, styles, objects, nodes):
    """Level objects (.dff, placed by the node of the same name: GameObjects, BouncyObjects) drawn where they start,
    without collision (THPS3 moves, breaks or bounces many of them by script; none of that runs yet).
    Node frame -> world: Z mirrored, so the Y rotation turns the other way."""
    H = Q.qbcrc
    n = 0
    for ob in objects:
        nd = nodes.get(ob.name)
        if nd is None:
            continue
        px, py, pz = nd.get(H("Position")) or (0.0, 0.0, 0.0)
        ax, ay, az = nd.get(H("Angles")) or (0.0, 0.0, 0.0)
        ca, sa = math.cos(-ay), math.sin(-ay)
        place = lambda v: (ca * v[0] + sa * v[2] + px, v[1] + py, -sa * v[0] + ca * v[2] - pz)
        for mi, a, b, c in ob.tris:
            mat = ob.materials[mi] if mi < len(ob.materials) else None
            if mat is None or not mat.texture or ns_material(mat)[0] & 0x02:
                continue
            key = material_key(mat)
            _, gs, fix, _ = ns_material(mat)
            if key not in sc.materials:
                sc.materials[key] = S.Material(key)
                if gs not in NORMAL_BLENDS:
                    styles[key] = ({0x42: gs | fix << 32}, 0)
                    sc.late.add(key)
            idx = (a, b, c)
            p = tuple(place(ob.verts[i]) for i in idx)
            uv = tuple(ob.uvs[i] if ob.uvs else (0.0, 0.0) for i in idx)
            if not all(map(math.isfinite, (x for q in p + uv for x in q))):
                continue
            mc = mat.colour
            col = tuple(tuple(min(255, ob.colours[i][k] * mc[k] // 255) for k in range(3)) + (128,) for i in idx)
            for pp, uu, cc in _split(p, uv, col):
                sc.tris.append(S.Tri(pp, uu, cc, key, 0, 0, render=True, collide=False))
        n += 1
    return n


def node_file(qb):
    """THPS3 level .qb (nodes + scripts) in THUG2 form, the names of nodes that have a TriggerScript, and the
    nodes by name {crc: {key: value}}."""
    H = Q.qbcrc
    t2 = thps4_qb.to_thug2(qb)
    q = thug2_qb.parse(t2)
    na = max((v for v in q.data.values() if isinstance(v, QD.Array)), key=lambda a: len(a.items))
    trig, nodes = set(), {}
    for st in na.items:
        if isinstance(st, QD.Struct):
            d = {k: v for k, v in st.items}
            if d.get(H("Name")) is not None:
                nodes[d[H("Name")].crc] = d
                if H("TriggerScript") in d:
                    trig.add(d[H("Name")].crc)
    return t2, trig, nodes


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

    def level_objects(self, code):
        world = read_pre(self.read(f"\\pre\\{code}bsp.pre"))
        dff = next((v for k, v in world.items() if k.endswith(f"\\{code}.dff")), b"")
        return rw.read_objects(dff)

    def build_zone(self, code, template_zone, zone_name, template, disc=None):
        world, texs, qb = self.level_parts(code)
        nodes_qb, triggers, nodes = node_file(qb)
        sc, styles = world_scene(world, triggers)
        n_objects = add_objects(sc, styles, self.level_objects(code), nodes)
        mats = sorted(sc.materials)
        grey = rw.Texture("grey", 8, 8, 0x14, 0, LC.GREY, [bytes(32)])
        group = Q.qbcrc(f"{zone_name}_thps3")
        new = []
        for m in mats:
            src = texs.get(m.split("#")[0], grey)
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
        strips = sorted(sc.render_items(), key=lambda it: it[0] in sc.late)
        geom, gst = geom_writer.write(template_zone[gp:gp + big[".geom"].size], strips, tex_index,
                                      name_prefix=zone_name, styles=styles)
        geom, _ = GM.bind_textures(geom, tex)
        col = col_writer.write(sc.collision_tris(), name_prefix=zone_name)
        # nodes (restarts, rails, trigger nodes), the level's scripts (gaps, glass, ...) and the gap list are
        # converted like THPS4's; EnvironmentObject (THPS3's level geometry) and objects THAW cannot spawn become
        # Waypoints, which keep their TriggerScript
        files = {"qb": nodes_qb, "scripts": nodes_qb, "scripts_only": True, "flip_z": True,
                 "neutralise": ("ProximNode", "EnvironmentObject", "BouncyObject", "GenericNode"),
                 "trigger_classes": ("RailNode", "Waypoint")}
        zb, st = LC.convert_level(template_zone, files, code, zone_name, lambda t: {}, template,
                                  prebuilt=(tex, geom, col))
        st.update(gst)
        st["textures"] = len(new)
        st["leaves"] = gst.get("leaves", sum(1 for _, n in GM.walk(geom) if n[7] & GM.LEAF))
        st["trigger sectors"] = len({sec.name for sec in world.sectors} & triggers)
        st["missing textures"] = sum(1 for m in mats if m.split("#")[0] not in texs)
        st["blended materials"] = len(styles)
        st["objects"] = n_objects
        return zb, st
