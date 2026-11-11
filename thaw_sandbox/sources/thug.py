"""Tony Hawk's Underground (PS2, NTSC-U SLUS-20731) as a level source.

SKATE5.HED/WAD, same layout as THPS4: loose levels\\<code>\\<code>.geom.ps2/.qb/_scripts.qb, textures in
pre\\<code>scn.pre, collision in pre\\<code>col.pre (PRE version 3). Formats sit between THPS4 and THUG2: textures
v5 and V2_32 UVs and texture-naming leaves like THUG2; geometry node words (w7 top byte, w14, w16) like THPS4;
collision v9 (v10 without the per-face byte block); scripts in THUG2 tokens; nodes in THUG's axes (no flip).
"""
from thaw_sandbox import thps4_qb, col, iso_manager as I, qb_data as QD, qb_parser as Q, thps4_geom, thug2_qb, thug2_tex as T2
from thaw_sandbox.sources.thps4 import read_pre
from thaw_sandbox.sources.thug2 import _hed

GAME = "THUG"
GENERATION = 5
SERIALS = ("SLUS_207.31",)
# story levels, the secret Hotter Than Hell, and the classic levels THUG carries ("Old ...")
LEVELS = ("nj", "ny", "fl", "sd", "hi", "vc", "sj", "ru", "se", "sc", "dj", "ph", "vn", "hn", "sc2")
# School, Downhill Jam and Philly are the same levels THUG2 ships (58-77% of their textures shared); THUG2's newer
# versions win. (THUG's se, Hotter Than Hell, shares no textures with THUG2's se: a different level.)
ORIGIN = {"sc": "classic:school", "dj": "classic:downhill_jam", "ph": "classic:philadelphia"}
# display names that read better than the game's own level-table names (user request 2026-11-11)
RENAME = {"fl": "Tampa", "vn": "Venice"}
ZONE_HINTS = {"se": "z_hh", "sc2": "z_s2", "ny": "z_mh", "sj": "z_sj", "vn": "z_vn", "hn": "z_hn"}


def detect(iso):
    try:
        cnf = I.read_file(iso, "/SYSTEM.CNF;1")
    except Exception:
        return False
    return any(s.encode() in cnf for s in SERIALS)


class Source:
    GAME = GAME
    GENERATION = GENERATION
    ORIGIN = ORIGIN
    ZONE_HINTS = ZONE_HINTS

    def __init__(self, iso, cache_dir):
        self.iso = iso
        self.hed = _hed(I.read_file(iso, "/SKATE5.HED;1"))
        self.wad_off, _ = I.file_extent(iso, "/SKATE5.WAD;1")

    def read(self, name):
        off, size = self.hed[name.lower()]
        with open(self.iso, "rb") as f:
            f.seek(self.wad_off + off)
            return f.read(size)

    def levels(self, codes=LEVELS):
        q = thug2_qb.parse(self.read("\\scripts\\game\\levels.qb"))
        names = {}
        for v in q.data.values():
            if isinstance(v, QD.Struct):
                d = {k: x for k, x in v.items}
                lv, nm = d.get(Q.qbcrc("level")), d.get(Q.qbcrc("name"))
                if isinstance(lv, str) and isinstance(nm, str):
                    names[lv.lower()] = nm
        return [(c, RENAME.get(c) or names.get(c, c.upper())) for c in codes]

    def level_files(self, code):
        tex = read_pre(self.read(f"\\pre\\{code}scn.pre"))[f"levels\\{code}\\{code}.tex.ps2"]
        cb = read_pre(self.read(f"\\pre\\{code}col.pre"))[f"levels\\{code}\\{code}.col.ps2"]
        _, textures = T2.parse(tex)
        geom, _ = thps4_geom.to_thug2(self.read(f"\\levels\\{code}\\{code}.geom.ps2"), textures)
        return {"geom": geom, "col": col.v9_to_v10(cb), "tex": tex,
                "qb": thps4_qb.to_thug2(self.read(f"\\levels\\{code}\\{code}.qb"), random_entry=6),
                "scripts": thps4_qb.to_thug2(self.read(f"\\levels\\{code}\\{code}_scripts.qb"), random_entry=6)}

    def resolve_texture_refs(self, textures):
        local = {x.crc: x for x in textures if x.mips}
        return {x.crc: local[x.crc] for x in textures if not x.mips and x.crc in local}
