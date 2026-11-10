"""Tony Hawk's Pro Skater 4 (PS2, NTSC-U SLUS-20504) as a level source.

SKATE4.HED/WAD (HED offsets in bytes, like THUG2). Per level: loose levels\\<code>\\<code>.geom.ps2, <code>.qb
(nodes) and <code>_scripts.qb; the texture dictionary is in pre\\<code>scn.pre and collision in
pre\\<code>col.pre (PRE archives: Neversoft LZSS, same coder as THAW script bodies). Every file is turned into
its THUG2 form here (thps4_geom, thps4_col, thps4_qb; textures are version 4, which thug2_tex reads), so the
rest of the pipeline is the THUG2 one.
"""
import struct

from thaw_sandbox import iso_manager as I, lzss, qb_data as QD, qb_parser as Q, thps4_col, thps4_geom, thps4_qb
from thaw_sandbox import thug2_qb, thug2_tex as T2
from thaw_sandbox.sources.thug2 import _hed

GAME = "THPS4"
GENERATION = 4
ORIGIN = {}  # THPS4's levels are its own
SERIALS = ("SLUS_205.04",)
# Carnival (cnv) is left out: its zone loads but the game returns to the level list (even with empty scripts)
LEVELS = ("sch", "sf2", "alc", "kon", "jnk", "lon", "zoo", "hof")
# levels whose own scripts stop the load from finishing (kept playable without them: no gap triggers yet)
NO_SCRIPTS = {"alc"}
DISPLAY = {"hof": "Chicago"}  # the level struct calls it Hoffman (the factory); the game shows Chicago
ZONE_HINTS = {"sch": "z_co", "sf2": "z_s4", "alc": "z_al", "kon": "z_ko", "jnk": "z_sy", "lon": "z_lo",
              "zoo": "z_zo", "cnv": "z_cv", "hof": "z_ch"}


def detect(iso):
    try:
        cnf = I.read_file(iso, "/SYSTEM.CNF;1")
    except Exception:
        return False
    return any(s.encode() in cnf for s in SERIALS)


def read_pre(b):
    """PRE archive -> {lower-case name: bytes}."""
    _total, _ver, count = struct.unpack_from("<IIi", b, 0)
    pos, out = 12, {}
    for _ in range(count):
        size, csize, nlen = struct.unpack_from("<3I", b, pos)
        name = b[pos + 12:pos + 12 + nlen].split(b"\0")[0].decode("latin1").lower()
        data = b[pos + 12 + nlen:pos + 12 + nlen + (csize or size)]
        out[name] = lzss.decompress(data, size) if csize else data
        pos += 12 + nlen + (((csize or size) + 3) & ~3)
    return out


class Source:
    GAME = GAME
    GENERATION = GENERATION
    ORIGIN = ORIGIN
    ZONE_HINTS = ZONE_HINTS
    USE_SETUP = False  # THPS4's <code>_setup scripts call THPS4-era functions; with them the load never finished

    def __init__(self, iso, cache_dir):
        self.iso = iso
        self.hed = _hed(I.read_file(iso, "/SKATE4.HED;1"))
        self.wad_off, _ = I.file_extent(iso, "/SKATE4.WAD;1")

    def read(self, name):
        off, size = self.hed[name.lower()]
        with open(self.iso, "rb") as f:
            f.seek(self.wad_off + off)
            return f.read(size)

    def levels(self):
        q = thug2_qb.parse(thps4_qb.to_thug2(self.read("\\scripts\\levels.qb")))
        names = {}
        for v in q.data.values():
            if isinstance(v, QD.Struct):
                d = {k: x for k, x in v.items}
                lv, nm = d.get(Q.qbcrc("level")), d.get(Q.qbcrc("name"))
                if isinstance(lv, str) and isinstance(nm, str):
                    names[lv.lower()] = nm
        return [(c, DISPLAY.get(c) or names.get(c, c.upper())) for c in LEVELS]

    def level_files(self, code):
        tex = read_pre(self.read(f"\\pre\\{code}scn.pre"))[f"levels\\{code}\\{code}.tex.ps2"]
        col = read_pre(self.read(f"\\pre\\{code}col.pre"))[f"levels\\{code}\\{code}.col.ps2"]
        _, textures = T2.parse(tex)
        geom, _ = thps4_geom.to_thug2(self.read(f"\\levels\\{code}\\{code}.geom.ps2"), textures)
        scripts = b"" if code in NO_SCRIPTS else thps4_qb.to_thug2(self.read(f"\\levels\\{code}\\{code}_scripts.qb"))
        return {"geom": geom, "col": thps4_col.to_v10(col), "tex": tex,
                "qb": thps4_qb.to_thug2(self.read(f"\\levels\\{code}\\{code}.qb")),
                "scripts": scripts,
                "flip_z": True,
                # THPS4 proximity nodes are radius spheres (THUG2/THAW: geometry boxes); the load never finished
                # with them. They only switch ambient sounds.
                "neutralise": ("ProximNode",),
                # restart/waypoint trigger scripts run on spawn (THPS4 goal logic); Alcatraz and London never
                # finished loading with them. Gaps live on rails and level geometry.
                "trigger_classes": ("RailNode", "LevelGeometry")}  # node positions: THPS4 has Z mirrored (restarts land on collision only flipped)

    def resolve_texture_refs(self, textures):
        return {}  # THPS4 dictionaries carry all their pixels
