"""Convert a THUG2 level (its .geom/.col/.tex/.qb/_scripts.qb) into a THAW zone PAK, using a THAW zone
(Kyoto, z_ja) as the template. Everything here was proven in game; see thaw_sandbox/geom.py, col.py,
thaw_tex.py for the per-format rules.

    zone = convert_level(template_zone, files, code, zone_name, resolve_refs)

files:        {"geom", "col", "tex", "qb", "scripts"} -> bytes of the THUG2 level files
resolve_refs: function(list of thug2_tex.Texture) -> {crc: Texture with pixels} for header-only entries
The result still carries the template's internal names; zone_rename.rename_zone renames them.
"""
import struct

from thaw_sandbox import classic, col as CL, convert_thug2 as C, geom as GM, pak, qb_data as QD, qb_file as F
from thaw_sandbox import gaps, prefix_table, qb_parser as Q, rails, thaw_tex as TT, thug2_qb, thug2_tex as T2, zone

# THUG2 node classes whose models do not exist in THAW: keep the nodes (link indices) but stop them spawning
NEUTRALISE = ("LevelObject", "LevelLight", "Pedestrian", "Vehicle", "ParticleObject", "GameObject",
              "ParticleEmitter")  # (the last is THPS4's)
# THPS4 node field names -> the THUG2/THAW ones
RENAME_KEYS = {"Position": "Pos"}
NODE_FILTER = None
SCRIPT_FILTER = None
GREY = struct.pack("<16I", *([0x80606060] * 16))
# Largest zone PAK proven safe: THAW sizes a buffer from the biggest zone file on the disc, and above about
# 10.5 MB (THUG San Diego, 10.78 MB) THAW's own open-world levels (Hollywood, Santa Monica, ...) hang while
# loading. Moscow at 10,500,592 bytes is fine. Bigger zones lose the top mip level of their largest textures.
MAX_ZONE_BYTES = 10_400_000
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


def convert_nodes(qb_bytes, code, na_zone, orig_crc, flip_z=False, neutralise=(), trigger_classes=None,
                  with_rails=False, goal_objects=False, remap=None):
    """THUG2 node file -> THAW node file (renamed node array, inlined includes, neutralised THUG2-only classes,
    sorted name index); with_rails: -> (node file, rail table built from the converted nodes).
    goal_objects: the classic goal objects (SKATE and COMBO letters, secret tape) keep their models: THAW has them.
    remap: name checksums to swap in the node file's scripts (classic.remap_table)."""
    _, items = F.read(C.convert(qb_bytes, "x")[0])
    if remap:
        classic.remap_items(items, remap)
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
    TYPE, goal_types = Q.qbcrc("Type"), {Q.qbcrc(t) for t in classic.GOAL_OBJECT_TYPES} if goal_objects else ()
    for s in list(na.items) + [it.value for it in items if isinstance(it.value, QD.Struct)]:
        c = next((getattr(v, "crc", None) for k, v in s.items if k == CLS), None)
        if c not in drop:
            continue
        if c in keep_class and any(k == TYPE and getattr(v, "crc", None) in goal_types for k, v in s.items):
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
    out = F.write(orig_crc, items)
    if with_rails:
        return out, rails.build(na.items, {it.name: it.value for it in items if isinstance(it.value, QD.Struct)}), \
            na.items
    return out


def _halvable(src):
    return src.psm in (0x13, 0x14) and src.width >= 16 and src.height >= 16 and src.mips


def _half(src):
    """Top level at half size: the next mip level when there is one, else every other pixel (T8 / T4)."""
    if len(src.mips) >= 2:
        return src.mips[1:5]
    w, h, m = src.width, src.height, src.mips[0]
    if src.psm == 0x13:
        return [bytes(m[y * w + x] for y in range(0, h, 2) for x in range(0, w, 2))]
    px = [m[(y * w + x) >> 1] >> (4 * (x & 1)) & 0xF for y in range(0, h, 2) for x in range(0, w, 2)]
    return [bytes(a | b << 4 for a, b in zip(px[0::2], px[1::2]))]


def convert_textures_and_geometry(tex_bytes, geom_bytes, resolve_refs, budget=0):
    """THUG2 texture dictionary + geometry -> THAW ones (bound to each other).
    budget: bytes to save by dropping the top mip level of the largest textures (0: keep all)."""
    _, t2 = T2.parse(tex_bytes)
    refs = resolve_refs(t2)
    srcs = [(x, x if x.mips else refs.get(x.crc)) for x in t2]
    halve, saved = set(), 0
    for i in sorted((i for i, (_, s) in enumerate(srcs) if s is not None and _halvable(s)),
                    key=lambda i: -len(srcs[i][1].mips[0])):
        if saved >= budget:
            break
        halve.add(i)
        saved += len(srcs[i][1].mips[0])
    new = []
    for i, (x, src) in enumerate(srcs):
        if src is not None and i in halve:
            new.append(TT.NewTexture(x.crc, src.width // 2, src.height // 2, src.psm, src.cpsm, src.clut,
                                     _half(src), group=x.group))
        elif src is not None:  # header-only entries reference a texture defined elsewhere: copy its pixels
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
    st["textures halved"] = len(halve)
    st["texture references resolved"] = len(refs)
    return tex, geom, st


def convert_level(template_zone, files, code, zone_name, resolve_refs, template="z_ja", level_scripts=True,
                  classic_consts=None):
    """classic_consts: THUG2's score globals (classic.thug2_constants) -> the level gets its classic goals
    (classic.convert_goals) in the template's Goals script; None: no goals."""
    zb = template_zone
    with_goals = classic_consts is not None and level_scripts and bool(files.get("scripts"))
    remap = classic.remap_table(code, zone_name) if with_goals else None
    tab = zone.entries(zb)
    big = _biggest(zb, tab)
    p0 = pak.data_pos(big[".nqb"], 0)
    orig_crc, _ = F.read(zb[p0:p0 + big[".nqb"].size])
    nqb, rnb, node_items = convert_nodes(files["qb"], code, zone_name, orig_crc, flip_z=files.get("flip_z", False),
                             neutralise=files.get("neutralise", ()), trigger_classes=files.get("trigger_classes"),
                             with_rails=True, goal_objects=with_goals, remap=remap)
    tex, geom, st = convert_textures_and_geometry(files["tex"], files["geom"], resolve_refs)
    rep = {big[".tex"].pos: tex, big[".geom"].pos: geom, big[".col"].pos: CL.thug2_to_thaw(files["col"]),
           big[".nqb"].pos: nqb}
    # rails come from the zone's rail table, not from the node array: the template's would give Kyoto's rails
    for e in tab:
        if struct.unpack_from("<I", zb, e.pos)[0] == rails.RNB_TYPE and e.size < 0x40000000:
            rep[e.pos] = rnb
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
        st["classic goals"] = 0
        if with_goals:
            src = thug2_qb.parse(files["scripts"]).scripts.get(Q.qbcrc(f"{code}_Goals"))
            body, st["classic goals"] = classic.convert_goals(src, zone_name, classic_consts) if src else (None, 0)
            if body:
                classic.remap_items(extra, remap)
                next(it for it in sitems if it.name == Q.qbcrc(f"{template}_Goals")).value = C.script_body(body)
    rep[se.pos] = F.write(scrc, sitems)
    # gap checklist: the template's names Kyoto's gaps under z_ja; the level's own come from its EndGap calls
    gap_list = gaps.collect(sitems) if level_scripts else []
    st["gaps"] = len(gap_list)
    for e in tab:
        if struct.unpack_from("<I", zb, e.pos)[0] == gaps.GAP_TYPE and e.size < 0x40000000:
            rep[e.pos] = gaps.build(gap_list, zone_name)
    # node name-prefix table: the template's lists Kyoto's prefixes and node indices
    names = {}
    for key in ("qb", "scripts"):
        if files.get(key):
            try:
                names.update(thug2_qb.parse(files[key]).names)
            except Exception:
                pass
    prefixes = prefix_table.script_prefixes(sitems, names)
    for e in tab:
        if struct.unpack_from("<I", zb, e.pos)[0] == prefix_table.TYPE and e.size < 0x40000000:
            p_ = pak.data_pos(e, 0)
            if struct.unpack_from("<I", zb, p_)[0] == Q.qbcrc(f"{template}_NodeArray"):
                rep[e.pos] = prefix_table.build(node_items, names, prefixes, zone_name)
    st["prefixes"] = len(prefixes)
    pe = named[f"{template}_peds.qb.ps2"]  # template peds would walk the template's paths: none
    pp = pak.data_pos(pe, 0)
    pcrc, pitems = F.read(zb[pp:pp + pe.size])
    for it in pitems:
        if it.name == Q.qbcrc(f"{template}_skate_peds"):
            it.value.items = []
    rep[pe.pos] = F.write(pcrc, pitems)
    out, budget = zone.rebuild(zb, rep), 0
    for _ in range(4):  # over the size cap: halve the largest textures until it fits
        if len(out) <= MAX_ZONE_BYTES:
            break
        budget += len(out) - MAX_ZONE_BYTES + 0x8000
        tex, geom, st2 = convert_textures_and_geometry(files["tex"], files["geom"], resolve_refs, budget)
        st.update(st2)
        rep[big[".tex"].pos], rep[big[".geom"].pos] = tex, geom
        out = zone.rebuild(zb, rep)
    return out, st


def assemble_level(template_zone, tex, geom, col, node_items, zone_name, template="z_ja"):
    """A zone from ready THAW parts (generated levels): texture dictionary, geometry (texture registers are bound
    here), collision and node structs. The template's scripts are emptied, its peds and gaps cleared; rails come
    from the nodes."""
    zb = template_zone
    tab = zone.entries(zb)
    big = _biggest(zb, tab)
    p0 = pak.data_pos(big[".nqb"], 0)
    orig_crc, _ = F.read(zb[p0:p0 + big[".nqb"].size])
    na = QD.Array(10, node_items)
    NAME = Q.qbcrc("name")
    pairs = sorted((v.crc, i) for i, s in enumerate(node_items) for n, v in s.items if n == NAME)
    items = [F.Item(12, Q.qbcrc(f"{zone_name}_NodeArray"), na),
             F.Item(12, Q.qbcrc(f"{zone_name}_NodeArray_SortedNames"), QD.Array(13, [QD.Name(c) for c, _ in pairs])),
             F.Item(12, Q.qbcrc(f"{zone_name}_NodeArray_SortedIndices"), QD.Array(1, [i for _, i in pairs]))]
    geom, _ = GM.bind_textures(geom, tex)
    rep = {big[".tex"].pos: tex, big[".geom"].pos: geom, big[".col"].pos: col,
           big[".nqb"].pos: F.write(orig_crc, items)}
    rnb = rails.build(node_items, {})
    named = _named(zb, tab)
    se = named[f"{template}_scripts.qb.ps2"]
    sp = pak.data_pos(se, 0)
    scrc, sitems = F.read(zb[sp:sp + se.size])
    empty = C.script_body(b"\x01\x24")
    for it in sitems:
        if it.vtype == 7:
            it.value = empty
    rep[se.pos] = F.write(scrc, sitems)
    for e in tab:
        typ = struct.unpack_from("<I", zb, e.pos)[0]
        if e.size >= 0x40000000:
            continue
        if typ == rails.RNB_TYPE:
            rep[e.pos] = rnb
        elif typ == prefix_table.TYPE and struct.unpack_from("<I", zb, pak.data_pos(e, 0))[0] == \
                Q.qbcrc(f"{template}_NodeArray"):  # Kyoto's prefixes / node indices: none here
            rep[e.pos] = prefix_table.build(node_items, {}, (), zone_name)
        elif typ == gaps.GAP_TYPE:
            rep[e.pos] = gaps.build([], zone_name)
    pe = named[f"{template}_peds.qb.ps2"]
    pp = pak.data_pos(pe, 0)
    pcrc, pitems = F.read(zb[pp:pp + pe.size])
    for it in pitems:
        if it.name == Q.qbcrc(f"{template}_skate_peds"):
            it.value.items = []
    rep[pe.pos] = F.write(pcrc, pitems)
    return zone.rebuild(zb, rep), {"textures": TT.parse(tex)[1].__len__(), "leaves": sum(
        1 for _, n in GM.walk(geom) if n[7] & GM.LEAF)}
