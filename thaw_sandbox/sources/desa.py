"""Disney's Extreme Skate Adventure (PS2, NTSC-U SLUS-20607) as a level source.

Built on the THPS4 engine: same SKATE4.HED/WAD, geometry (0x10), texture dictionaries (version 4), collision
(version 8) and QB token streams, so THPS4's conversion is used as is (thps4_geom, thps4_col, thps4_qb; node Z
mirrored). Only the packing differs: every level file is inside PRE archives - pre\\<code>scn.pre (geometry,
textures, sky), pre\\<code>col.pre (collision) and pre\\<code>.pre (nodes, level scripts, its models and anims).
"""
from thaw_sandbox import thps4_col, thps4_geom, thps4_qb, thug2_tex as T2
from thaw_sandbox.sources import thps4
from thaw_sandbox.sources.thps4 import read_pre

GAME = "Disney Extreme Skate Adventure"
GENERATION = 4
ORIGIN = {}
SERIALS = ("SLUS_206.07",)
LEVELS = ("toystory_bedroom", "pizza", "zurghome", "tarzan_treehouse", "camp", "beach", "priderock", "graveyard",
          "canyon", "hub")
NAMES = {"toystory_bedroom": "Andy's Room", "pizza": "Pizza Planet", "zurghome": "Zurg's World",
         "tarzan_treehouse": "Jungle Treehouse", "camp": "Human Camp", "beach": "Clayton's Ship",
         "priderock": "Pride Rock", "graveyard": "Elephant Graveyard", "canyon": "The Canyon", "hub": "Olliewood"}
ZONE_HINTS = {"toystory_bedroom": "z_ar", "pizza": "z_pp", "zurghome": "z_zw", "tarzan_treehouse": "z_jt",
              "camp": "z_hm", "beach": "z_cl", "priderock": "z_pr", "graveyard": "z_eg", "canyon": "z_cy",
              "hub": "z_ow"}


def detect(iso):
    from thaw_sandbox import iso_manager as I
    try:
        cnf = I.read_file(iso, "/SYSTEM.CNF;1")
    except Exception:
        return False
    return any(s.encode() in cnf for s in SERIALS)


class Source(thps4.Source):
    GAME = GAME
    GENERATION = GENERATION
    ORIGIN = ORIGIN
    ZONE_HINTS = ZONE_HINTS

    def levels(self, codes=LEVELS):
        return [(c, NAMES.get(c, c)) for c in codes]

    def all_levels(self):
        return self.levels(LEVELS)

    def level_files(self, code):
        scn = read_pre(self.read(f"\\pre\\{code}scn.pre"))
        lv = read_pre(self.read(f"\\pre\\{code}.pre"))
        col = read_pre(self.read(f"\\pre\\{code}col.pre"))[f"levels\\{code}\\{code}.col.ps2"]
        tex = scn[f"levels\\{code}\\{code}.tex.ps2"]
        _, textures = T2.parse(tex)
        geom, _ = thps4_geom.to_thug2(scn[f"levels\\{code}\\{code}.geom.ps2"], textures)
        scripts = lv.get(f"levels\\{code}\\{code}_scripts.qb", b"")
        return {"geom": geom, "col": thps4_col.to_v10(col), "tex": tex,
                "qb": thps4_qb.to_thug2(lv[f"levels\\{code}\\{code}.qb"]),
                "scripts": thps4_qb.to_thug2(scripts) if scripts else b"",
                "flip_z": True, "neutralise": ("ProximNode",), "trigger_classes": ("RailNode", "LevelGeometry")}
