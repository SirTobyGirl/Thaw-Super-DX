"""Generated levels: build a THAW zone from a Scene (geometry, collision, rails, start points) and borrowed textures.

    zb, st = build_zone(template_zone, scene, textures, zone_name)

textures: material name -> a palettised source texture (thug2_tex.Texture or thaw_tex.NewTexture).
"""
import hashlib
import inspect
import re

from thaw_sandbox import level_convert as LC, pak, thaw_tex as TT, zone
from thaw_sandbox.mapgen import col_writer, geom_writer, nodes, texlib
from thaw_sandbox.qb_parser import qbcrc as H


def build_zone(template_zone, scene, textures, zone_name, template="z_ja"):
    tab = zone.entries(template_zone)
    big = LC._biggest(template_zone, tab)
    gp = pak.data_pos(big[".geom"], 0)
    template_geom = template_zone[gp:gp + big[".geom"].size]
    mats = sorted(scene.materials)
    group = H(f"{zone_name}_generated")
    new = [texlib.new_texture(textures[m], crc=H(f"{zone_name}_{m}"), group=group) for m in mats]
    tex = TT.write(new)
    tex_index = {m: (1, i + 1) for i, m in enumerate(mats)}
    geom, gst = geom_writer.write(template_geom, scene.render_items(), tex_index, name_prefix=zone_name)
    col = col_writer.write(scene.collision_tris(), name_prefix=zone_name)
    node_items = nodes.build(scene, zone_name)
    zb, st = LC.assemble_level(template_zone, tex, geom, col, node_items, zone_name, template)
    st.update(gst)
    st["rails"] = len(scene.rails)
    return zb, st


# THAW's own Beverly Hills textures (always available: the user's THAW disc), by position among its palettised
# textures of at least 64 x 64 in dictionary order
THAW_PICKS = {"paving": 3, "path": 1, "grass": 149, "asphalt": 92, "brick": 112, "stone": 23, "roof": 33, "wood": 5,
              "metal": 24}


def thaw_textures(disc, picks=THAW_PICKS, zone_name="z_bh"):
    zb = disc.read(f"\\worlds\\worldzones\\{zone_name}\\{zone_name}.pak.ps2")
    big = LC._biggest(zb, zone.entries(zb))
    p = pak.data_pos(big[".tex"], 0)
    tex = zb[p:p + big[".tex"].size]
    offs, ts = TT.parse(tex)
    sel = [t for t in ts if t.width >= 64 and t.height >= 64 and t.psm in (0x13, 0x14)]
    return {m: TT.extract_native(tex, offs, sel[i]) for m, i in picks.items()}


def real_place(location, radius=150.0, name=None, work=".", layout=None):
    """A generated level spec (code, display name, make(disc)) for a real location; layout: skatepark pieces
    (dict, or a path to the layout editor's JSON) placed in the skatepark there."""
    from thaw_sandbox.mapgen import fetch, osm

    def make(disc):
        lat, lon = fetch.resolve(location)
        data, elev = fetch.fetch(lat, lon, radius, f"{work}/mapdata")
        lay = layout
        if isinstance(lay, str):
            import json
            lay = json.load(open(lay))
        return osm.build(data, elev, lat, lon, radius, park_layout=lay), thaw_textures(disc)
    place = re.sub(r"[23456789CFGHJMPQRVWX]{2,8}\+[23456789CFGHJMPQRVWX]{2,3}|-?\d+(\.\d+)?", "", location, flags=re.I)
    disp = name or place.strip(" ,;") or "Real Place"
    return ("gen" + hashlib.sha1(location.encode()).hexdigest()[:2], disp[:20], make)


class GeneratedSource:
    """A 'source game' whose levels are generated (used by build.build like a disc adapter)."""
    GAME = "Generated"
    GENERATION = 0
    PREBUILT = True

    def __init__(self, levels):
        self._levels = levels  # [(code, display name, make() -> (scene, textures))]

    def levels(self):
        return [(c, n) for c, n, _ in self._levels]

    all_levels = levels

    def build_zone(self, code, template_zone, zone_name, template, disc=None):
        make = next(m for c, _, m in self._levels if c == code)
        scene, textures = make(disc) if inspect.signature(make).parameters else make()
        return build_zone(template_zone, scene, textures, zone_name, template)
