"""Convert a THUG2 level (its .geom/.col/.tex/.qb/_scripts.qb) into a THAW zone PAK, using a THAW zone
(Kyoto, z_ja) as the template. Everything here was proven in game; see thaw_sandbox/geom.py, col.py,
thaw_tex.py for the per-format rules.

    zone = convert_level(template_zone, files, code, zone_name, resolve_refs)

files:        {"geom", "col", "tex", "qb", "scripts"} -> bytes of the THUG2 level files
resolve_refs: function(list of thug2_tex.Texture) -> {crc: Texture with pixels} for header-only entries
The result still carries the template's internal names; zone_rename.rename_zone renames them.
"""
import struct

from thaw_sandbox import col as CL, convert_thug2 as C, geom as GM, pak, qb_data as QD, qb_file as F
from thaw_sandbox import qb_parser as Q, thaw_tex as TT, thug2_tex as T2, zone

# THUG2 node classes whose models do not exist in THAW: keep the nodes (link indices) but stop them spawning
NEUTRALISE = ("LevelObject", "LevelLight", "Pedestrian", "Vehicle", "ParticleObject", "GameObject",
              "ParticleEmitter")  # (the last is THPS4's)
# THPS4 node field names -> the THUG2/THAW ones
RENAME_KEYS = {"Position": "Pos"}
NODE_FILTER = None
SCRIPT_FILTER = None
GREY = struct.pack("<16I", *([0x80606060] * 16))
log = print


def _biggest(zb, tab):
    T = {Q.qbcrc(x): x for x in (".tex", ".geom", ".col", ".nqb")}
    out = {}
    for e in tab:
        t = T.get(struct.unpack_from("<I", zb, e.pos)[0])
        if t and e.size < 0x40000000 and e.size > out.get(t, (None, -1))[1]:
            out[t] = (e, e.size)
    return {k: v[0] for k, v in out.items()}


def _named(zb, tab):
    return {zb[x.pos + 32:x.pos + 192].split(b"\0")[0].decode().split("\\")[-1]: x
            for x in tab if struct.unpack_from("<I", zb, x.pos + 28)[0] & 0x20}


def convert_nodes(qb_bytes, code, na_zone, orig_crc, flip_z=False, neutralise=(), trigger_classes=None):
    """THUG2 node file -> THAW node file (renamed node array, inlined includes, neutralised THUG2-only classes,
    sorted name index)."""
    _, items = F.read(C.convert(qb_bytes, "x")[0])
    old_na, new_na = {Q.qbcrc(f"{code}_NodeArray"), Q.qbcrc("NodeArray")}, Q.qbcrc(f"{na_zone}_NodeArray")
    for it in items:  # THUG2: <code>_NodeArray, THPS4: NodeArray
        if it.name in old_na:
            it.name = new_na
    na = next(it for it in items if it.name == new_na).value
    # THUG2 nodes include shared field sets by bare name (ncomp_* structs); inline them
    structs = {it.name: it.value for it in items if isinstance(it.value, QD.Struct)}

    def expand(sv, depth=0):
        out = []
        for k, v in sv.items:
            if k == 0 and isinstance(v, QD.Name) and v.crc in structs and depth < 4:
                out += expand(structs[v.crc], depth + 1)
            else:
                out.append((k, v))
        return out
    ren = {Q.qbcrc(a): Q.qbcrc(b) for a, b in RENAME_KEYS.items()}
    POS, ANG = Q.qbcrc("Pos"), Q.qbcrc("Angles")
    for node in na.items:
        node.items = [(ren.get(k, k), v) for k, v in expand(node)]
        if flip_z:  # THPS3/4 node space has Z mirrored relative to THUG and later (position Z and Z angle)
            node.items = [(k, (v[0], v[1], -v[2]) if k in (POS, ANG) and isinstance(v, tuple) and len(v) == 3 else v)
                          for k, v in node.items]
    CLS, CAS, MODEL, WP = Q.qbcrc("Class"), Q.qbcrc("CreatedAtStart"), Q.qbcrc("model"), Q.qbcrc("Waypoint")
    drop, keep_class = {Q.qbcrc(c) for c in NEUTRALISE + tuple(neutralise)}, {Q.qbcrc("GameObject")}
    for s in list(na.items) + [it.value for it in items if isinstance(it.value, QD.Struct)]:
        c = next((getattr(v, "crc", None) for k, v in s.items if k == CLS), None)
        if c not in drop:
            continue
        s.items = [(k, v) for k, v in s.items if k != MODEL and not (k == 0 and getattr(v, "crc", None) == CAS)]
        if c not in keep_class:
            s.items = [(k, QD.Name(WP) if k == CLS else v) for k, v in s.items]
    if trigger_classes is not None:  # TriggerScript kept only on these node classes (gap triggers: rails, geometry)
        keep_t, TS = {Q.qbcrc(c) for c in trigger_classes}, Q.qbcrc("TriggerScript")
        CLS_ = Q.qbcrc("Class")
        for s in na.items:
            if next((getattr(v, "crc", None) for k, v in s.items if k == CLS_), None) not in keep_t:
                s.items = [(k, v) for k, v in s.items if k != TS]
    if NODE_FILTER:  # bisection hook (harness): keep only some nodes
        na.items = NODE_FILTER(na.items)
    NAME = Q.qbcrc("name")  # THAW node files carry a sorted name index
    pairs = sorted((v.crc, i) for i, s in enumerate(na.items) for n, v in s.items if n == NAME)
    items += [F.Item(12, Q.qbcrc(f"{na_zone}_NodeArray_SortedNames"), QD.Array(13, [QD.Name(c) for c, _ in pairs])),
              F.Item(12, Q.qbcrc(f"{na_zone}_NodeArray_SortedIndices"), QD.Array(1, [i for _, i in pairs]))]
    return F.write(orig_crc, items)


def convert_textures_and_geometry(tex_bytes, geom_bytes, resolve_refs):
    """THUG2 texture dictionary + geometry -> THAW ones (bound to each other)."""
    _, t2 = T2.parse(tex_bytes)
    refs = resolve_refs(t2)
    new = []
    for x in t2:
        src = x if x.mips else refs.get(x.crc)
        if src is not None:  # header-only entries reference a texture defined elsewhere: copy its pixels
            new.append(TT.NewTexture(x.crc, src.width, src.height, src.psm, src.cpsm, src.clut, src.mips[:4],
                                     group=x.group))
        else:
            new.append(TT.NewTexture(x.crc, 8, 8, 0x14, 0, GREY, [bytes(32)], group=x.group))
    moved = TT.split_groups(new)  # groups too big for one THAW VRAM window are split
    tex = TT.write(new)
    order, by = [], {}
    for t in new:
        if t.group not in by:
            order.append(t.group)
            by[t.group] = []
        by[t.group].append(t.crc)
    geom, st = GM.thug2_to_thaw(geom_bytes, order, by, moved=moved)
    geom, st["untextured leaves dropped"] = GM.drop_untextured(geom)
    geom, _ = GM.bind_textures(geom, tex)
    st["textures"] = len(new)
    st["texture references resolved"] = len(refs)
    return tex, geom, st


def convert_level(template_zone, files, code, zone_name, resolve_refs, template="z_ja", level_scripts=True):
    zb = template_zone
    tab = zone.entries(zb)
    big = _biggest(zb, tab)
    p0 = pak.data_pos(big[".nqb"], 0)
    orig_crc, _ = F.read(zb[p0:p0 + big[".nqb"].size])
    nqb = convert_nodes(files["qb"], code, zone_name, orig_crc, flip_z=files.get("flip_z", False),
                        neutralise=files.get("neutralise", ()), trigger_classes=files.get("trigger_classes"))
    tex, geom, st = convert_textures_and_geometry(files["tex"], files["geom"], resolve_refs)
    rep = {big[".tex"].pos: tex, big[".geom"].pos: geom, big[".col"].pos: CL.thug2_to_thaw(files["col"]),
           big[".nqb"].pos: nqb}
    # level scripts: the template's script names stay (emptied; they are renamed to the new zone later) plus the
    # THUG2 level's own scripts (its nodes name them as trigger scripts: gaps etc.)
    named = _named(zb, tab)
    se = named[f"{template}_scripts.qb.ps2"]
    sp = pak.data_pos(se, 0)
    scrc, sitems = F.read(zb[sp:sp + se.size])
    empty = C.script_body(b"\x01\x24")
    for it in sitems:
        if it.vtype == 7:
            it.value = empty
    if level_scripts and files.get("scripts"):
        have = {it.name for it in sitems}
        _, extra = F.read(C.convert(files["scripts"], "x")[0])
        extra = [it for it in extra if it.name not in have]
        if SCRIPT_FILTER:  # bisection hook (harness)
            extra = SCRIPT_FILTER(extra)
        sitems += extra
    rep[se.pos] = F.write(scrc, sitems)
    pe = named[f"{template}_peds.qb.ps2"]  # template peds would walk the template's paths: none
    pp = pak.data_pos(pe, 0)
    pcrc, pitems = F.read(zb[pp:pp + pe.size])
    for it in pitems:
        if it.name == Q.qbcrc(f"{template}_skate_peds"):
            it.value.items = []
    rep[pe.pos] = F.write(pcrc, pitems)
    return zone.rebuild(zb, rep), st
