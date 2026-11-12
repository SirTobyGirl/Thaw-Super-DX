"""Custom levels made for THUG Pro (the PC mod of THUG2), e.g. from thpsgoat.com, as a level source.

A level comes as a .zip (or an unpacked folder) with <scene>.level.json and PRE archives renamed .prx:
<scene>scn.prx (levels\\<scene>\\<scene>.scn.xbx + .tex.xbx, and a sky), <scene>col.prx (.col.xbx = THUG2's
collision, version 10) and <scene>_scripts.prx (<scene>.qb = THUG2 nodes; scripts files may be empty).
The scene and textures are PC/Xbox formats (thaw_sandbox.xbx: plain vertex buffers, DXT textures), so the level is
rebuilt like THPS3's: triangles -> mapgen writers, textures palettised (at most 256 px), collision converted as
THUG2's, nodes/rails/restarts by level_convert.convert_level (prebuilt geometry). Sound banks (pcm.wad) that mods
ship to replace THUG Pro's are not used.
"""
import io
import json
import os
import zipfile

from thaw_sandbox import col as CL, geom as GM, level_convert as LC, pak, qb_parser as Q, rw
from thaw_sandbox import thaw_tex as TT, xbx, zone
from thaw_sandbox.mapgen import geom_writer, scene as S
from thaw_sandbox.sources.thps4 import read_pre
from thaw_sandbox.sources.thps3 import _split

GAME = "THUG Pro custom"
GENERATION = 6  # THUG2's engine
ORIGIN = {}
# THUG2 pass blend modes -> PS2 GS ALPHA (low byte; fixed factor goes in bits 32-39)
BLEND = {1: 0x48, 2: 0x68, 3: 0x42, 4: 0x62, 6: 0x64}
MAT_DECAL, MAT_TRANSPARENT = 0x10, 0x40


def is_mod(path):
    if os.path.isdir(path):
        return any(f.endswith(".level.json") for f in os.listdir(path))
    return path.lower().endswith(".zip") and any(n.endswith(".level.json") for n in zipfile.ZipFile(path).namelist())


class _Files:
    def __init__(self, path):
        self.path = path
        self.zip = None if os.path.isdir(path) else zipfile.ZipFile(path)

    def names(self):
        return self.zip.namelist() if self.zip else os.listdir(self.path)

    def read(self, name):
        name = next(n for n in self.names() if os.path.basename(n).lower() == name.lower())
        if self.zip:
            return self.zip.read(name)
        return open(os.path.join(self.path, name), "rb").read()


def _json(text):
    """The level.json files are hand-written (trailing commas)."""
    import re
    return json.loads(re.sub(r",\s*([}\]])", r"\1", text))


class Source:
    GAME = GAME
    GENERATION = GENERATION
    ORIGIN = ORIGIN
    ZONE_HINTS = {}
    PREBUILT = True

    def __init__(self, path, cache_dir=None):
        self.files = _Files(path)
        self.levels_ = []
        for n in self.files.names():
            if n.endswith(".level.json"):
                j = _json(self.files.read(os.path.basename(n)).decode("utf-8", "replace"))
                self.levels_.append((j["scene_name"].lower(), j.get("level_name") or j["scene_name"], j))

    def levels(self):
        return [(c, name) for c, name, _ in self.levels_]

    all_levels = levels

    def _pre(self, name):
        return read_pre(self.files.read(name.replace(".pre", ".prx")))

    def build_zone(self, code, template_zone, zone_name, template, disc=None):
        j = next(j for c, _, j in self.levels_ if c == code)
        scn = self._pre(j.get("level_scnpre", f"{code}scn.pre"))
        get = lambda files, ext: next(v for k, v in files.items() if k.endswith(f"\\{code}{ext}"))
        mats, tris = xbx.read_scene(get(scn, ".scn.xbx"))
        texs = xbx.read_textures(get(scn, ".tex.xbx"))
        col = CL.thug2_to_thaw(get(self._pre(j.get("level_colpre", f"{code}col.pre")), ".col.xbx"))
        qb = get(self._pre(j.get("level_pre", f"{code}_scripts.pre")), ".qb")
        # scene -> mapgen Scene (first pass of each material; render only: collision is the level's own)
        sc, styles, late = S.Scene(), {}, set()
        for _sec, mcrc, verts in tris:
            passes = mats.get(mcrc) or []
            if not passes or passes[0][0] not in texs:
                continue
            tex, flags, blend, fix, _colour = passes[0]
            key = f"{tex:08x}" + (f"#{blend}" if blend in BLEND else "")
            if key not in sc.materials:
                sc.materials[key] = S.Material(key)
                if blend in BLEND:
                    styles[key] = ({0x42: BLEND[blend] | fix << 32}, 0)
                if blend in BLEND or flags & (MAT_DECAL | MAT_TRANSPARENT):
                    late.add(key)
            p = tuple(v[0] for v in verts)
            uv = tuple(v[1] for v in verts)
            colour = tuple(tuple(min(255, c) for c in v[2][:3]) + (min(128, v[2][3]),) for v in verts)
            for pp, uu, cc in _split(p, uv, colour):
                sc.tris.append(S.Tri(pp, uu, cc, key, 0, 0, render=True, collide=False))
        mats_used = sorted(sc.materials)
        group = Q.qbcrc(f"{zone_name}_custom")
        new = []
        for m in mats_used:
            t = texs[int(m.split("#")[0], 16)]
            new.append(TT.NewTexture(Q.qbcrc(f"{zone_name}_{m}"), t.width, t.height, t.psm, t.cpsm, t.clut, t.mips[:4],
                                     group=group))
        TT.split_groups(new)
        tex = TT.write(new)
        order = list(dict.fromkeys(t.group for t in new))
        pos_in = {}
        for t in new:
            pos_in.setdefault(t.group, []).append(t.crc)
        tex_index = {m: (order.index(t.group) + 1, pos_in[t.group].index(t.crc) + 1) for m, t in zip(mats_used, new)}
        tab = zone.entries(template_zone)
        big = LC._biggest(template_zone, tab)
        gp = pak.data_pos(big[".geom"], 0)
        strips = sorted(sc.render_items(), key=lambda it: it[0] in late)
        geom, gst = geom_writer.write(template_zone[gp:gp + big[".geom"].size], strips, tex_index,
                                      name_prefix=zone_name, styles=styles)
        geom, _ = GM.bind_textures(geom, tex)
        # nodes: THUG2's own form. No level scripts come with the level: TriggerScripts are dropped (none would
        # exist), and LevelGeometry nodes (they name scene sectors this rebuilt geometry does not have) become
        # Waypoints with the classes THAW cannot spawn
        files = {"qb": qb, "scripts": b"", "neutralise": ("LevelGeometry", "ProximNode"), "trigger_classes": ()}
        zb, st = LC.convert_level(template_zone, files, code, zone_name, lambda t: {}, template,
                                  prebuilt=(tex, geom, col))
        st.update(gst)
        st["textures"] = len(new)
        st["leaves"] = sum(1 for _, n in GM.walk(geom) if n[7] & GM.LEAF)
        st["blended materials"] = len(styles)
        return zb, st
