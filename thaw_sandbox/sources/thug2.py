"""Tony Hawk's Underground 2 (PS2, NTSC-U SLUS-20965) as a level source.

Data lives in DATAP.HED/WAD (HED offsets in BYTES, unlike THAW's sectors). Levels are loose files under
levels\\<code>\\: <code>.geom.ps2, .col.ps2, .tex.ps2, <code>.qb (nodes), <code>_scripts.qb.
"""
import os
import pickle
import struct

from thaw_sandbox import iso_manager as I, qb_data as QD, qb_parser as Q, thug2_qb, thug2_tex as T2

GAME = "THUG2"
GENERATION = 6  # engine order: THPS3 3, THPS4 4, THUG 5, THUG2 6, THAW 7 (newest version of a level wins)
# classic levels THUG2 remade from earlier games: the same level as the original game's version (only this newer
# one is imported when both discs are given). THPS3 codes checked on the THPS3 disc (ap/can/la .pre + loadscrn).
ORIGIN = {"ap": "thps3:airport", "ca": "thps3:canada", "la": "thps3:los_angeles"}
SERIALS = ("SLUS_209.65",)
# the 15 skateable levels (story + classic); codes as on the disc
# zone name preferences (THAW zone names are z_ + 2 characters) and display names differing from THUG2's own
ZONE_HINTS = {"se2": "z_t2"}
DISPLAY = {"sc": "School"}
LEVELS = ("tr", "bo", "ba", "be", "au", "no", "st", "se", "se2", "la", "sc", "ph", "dj", "ca", "ap")


def detect(iso):
    try:
        cnf = I.read_file(iso, "/SYSTEM.CNF;1")
    except Exception:
        return False
    return any(s.encode() in cnf for s in SERIALS)


def _hed(data):
    p, out = 0, {}
    while p + 8 <= len(data):
        off, size = struct.unpack_from("<iI", data, p)
        if off == -1:
            break
        e = data.index(b"\0", p + 8)
        out[data[p + 8:e].decode("latin1").lower()] = (off, size)
        p = (e + 1 + 3) & ~3
    return out


class Source:
    GAME = GAME
    GENERATION = GENERATION
    ORIGIN = ORIGIN
    ZONE_HINTS = ZONE_HINTS

    def __init__(self, iso, cache_dir):
        self.iso = iso
        self.cache = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self.hed = _hed(I.read_file(iso, "/DATAP.HED;1"))
        self.wad_off, _ = I.file_extent(iso, "/DATAP.WAD;1")
        self._index = None

    def read(self, name):
        off, size = self.hed[name.lower()]
        with open(self.iso, "rb") as f:
            f.seek(self.wad_off + off)
            return f.read(size)

    def levels(self):
        """[(code, display name)] from THUG2's own level definitions (scripts\\game\\levels.qb)."""
        q = thug2_qb.parse(self.read("\\scripts\\game\\levels.qb"))
        names = {}
        for v in q.data.values():
            if isinstance(v, QD.Struct):
                d = {k: x for k, x in v.items}
                lv, nm = d.get(Q.qbcrc("Level")), d.get(Q.qbcrc("name"))
                if isinstance(lv, str) and isinstance(nm, str):
                    names[lv.lower()] = nm
        return [(c, DISPLAY.get(c) or names.get(c, c.upper())) for c in LEVELS]

    def level_files(self, code):
        b = f"\\levels\\{code}\\{code}"
        return {"geom": self.read(b + ".geom.ps2"), "col": self.read(b + ".col.ps2"), "tex": self.read(b + ".tex.ps2"),
                "qb": self.read(b + ".qb"), "scripts": self.read(b + "_scripts.qb")}

    def _tex_index(self):
        """texture crc -> .tex files defining it with pixels (all of the disc), cached."""
        if self._index is None:
            path = os.path.join(self.cache, "thug2_tex_index.pkl")
            if os.path.exists(path):
                self._index = pickle.load(open(path, "rb"))
            else:
                idx = {}
                for name in self.hed:
                    if name.endswith(".tex.ps2"):
                        try:
                            _, tt = T2.parse(self.read(name))
                        except Exception:
                            continue
                        for x in tt:
                            if x.mips:
                                idx.setdefault(x.crc, []).append(name)
                pickle.dump(idx, open(path, "wb"))
                self._index = idx
        return self._index

    def resolve_texture_refs(self, textures):
        """Header-only textures (flag bit 31) reference a texture defined elsewhere: another group of the same
        file, or another level's .tex. -> {crc: Texture with pixels}"""
        local = {x.crc: x for x in textures if x.mips}
        out, cache = {}, {}
        for x in textures:
            if x.mips:
                continue
            if x.crc in local:
                out[x.crc] = local[x.crc]
                continue
            files = self._tex_index().get(x.crc)
            if files:
                if files[0] not in cache:
                    _, tt = T2.parse(self.read(files[0]))
                    cache[files[0]] = {t.crc: t for t in tt if t.mips}
                out[x.crc] = cache[files[0]][x.crc]
        return out
