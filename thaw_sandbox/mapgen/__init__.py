"""Generated levels: build a THAW zone from a Scene (geometry, collision, rails, start points) and borrowed textures.

    zb, st = build_zone(template_zone, scene, textures, zone_name)

textures: material name -> a palettised source texture (thug2_tex.Texture or thaw_tex.NewTexture).
"""
import struct

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

    def build_zone(self, code, template_zone, zone_name, template):
        make = next(m for c, _, m in self._levels if c == code)
        scene, textures = make()
        return build_zone(template_zone, scene, textures, zone_name, template)


def _struct_unused():
    return struct
