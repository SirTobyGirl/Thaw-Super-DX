"""Tony Hawk's Project 8 (PS2, NTSC-U SLUS-21444) as a level source.

Project 8's PS2 version runs on THAW's engine: DATAP.HED/WAD like THAW's, and each area is a THAW-format zone PAK
(worlds\\worldzones\\z_<name>\\z_<name>.pak.ps2) whose texture dictionary (version 6), geometry, collision (with
THAW's supersector block) and node file THAW reads as they are. HED offsets are 21-bit sector numbers, sign-extended
(entries past 2 GB of the WAD read negative).
The areas are pieces of one streamed city: each becomes its own level. The zone's textures, geometry and collision
are kept; nodes are kept except those THAW cannot spawn (objects, peds, vehicles, particles: become Waypoints) and
TriggerScripts (Project 8's scripts are not carried over). Areas without a restart node get one where a pedestrian
stands (they are placed on the ground), else above a rail. The rest is assembled like a generated level
(level_convert.assemble_level: rails, prefix table, empty gap list, template scripts emptied).
"""
import os

from thaw_sandbox import iso_manager as I, level_convert as LC, pak, qb_data as QD, qb_file as F, qb_parser as Q
from thaw_sandbox import wad, zone
from thaw_sandbox.qb_parser import qbcrc as H

GAME = "Project 8"
GENERATION = 8  # newer than THAW
ORIGIN = {}
SERIALS = ("SLUS_214.44",)
# area zones (z_ms is THAW's Marseilles left on the disc; test, menu and helper zones are skipped)
LEVELS = ("houses", "sz", "inschool", "center", "shops", "cretepark", "funpark", "cf", "riod", "training")
NAMES = {"houses": "Suburbs", "sz": "School", "inschool": "Inside the School", "center": "Town Center",
         "shops": "Main Street", "cretepark": "Concrete Park", "funpark": "Fun Park", "cf": "Car Factory",
         "riod": "Rio D", "training": "P8 Training"}
ZONE_HINTS = {"houses": "z_hs", "sz": "z_hl", "inschool": "z_is", "center": "z_tc", "shops": "z_mn",
              "cretepark": "z_cp", "funpark": "z_fp", "cf": "z_cf", "riod": "z_rd", "training": "z_tg"}
KEEP_CLASSES = {H(c) for c in ("restart", "RailNode", "ClimbingNode", "Waypoint", "LevelGeometry")}
CLS, NAME, POS, TS, CAS, MODEL = (H(x) for x in ("Class", "name", "pos", "TriggerScript", "CreatedAtStart", "model"))


def detect(iso):
    try:
        cnf = I.read_file(iso, "/SYSTEM.CNF;1")
    except Exception:
        return False
    return any(s.encode() in cnf for s in SERIALS)


def _parts(zb):
    types = {H(x): x for x in (".tex", ".geom", ".col", ".nqb")}
    out = {}
    for e in zone.entries(zb):
        if e.size >= 0x40000000:
            continue
        t = types.get(int.from_bytes(zb[e.pos:e.pos + 4], "little"))
        if t and (t not in out or e.size > len(out[t])):
            out[t] = zb[pak.data_pos(e, 0):pak.data_pos(e, 0) + e.size]
    return out


def thaw_nodes(nqb, zone_name):
    """Project 8 node file (THAW form) -> node structs for zone_name: unspawnable classes become Waypoints, no
    TriggerScripts, a restart added if the area has none."""
    _, items = F.read(nqb)
    na = max((i for i in items if isinstance(i.value, QD.Array)), key=lambda i: len(i.value.items))
    nodes = [s for s in na.value.items if isinstance(s, QD.Struct)]
    for s in nodes:
        c = next((getattr(v, "crc", None) for k, v in s.items if k == CLS), None)
        s.items = [(k, v) for k, v in s.items if k != TS]
        if c is not None and c not in KEEP_CLASSES:
            s.items = [(k, QD.Name(H("Waypoint")) if k == CLS else v) for k, v in s.items
                       if k != MODEL and not (k == 0 and getattr(v, "crc", None) == CAS)]
    if not any(any(k == CLS and getattr(v, "crc", None) == H("restart") for k, v in s.items) for s in nodes):
        p = None
        for cls, lift in (("Pedestrian", 20.0), ("RailNode", 60.0)):  # original classes (peds were renamed above)
            p = _orig_pos(nqb, cls)
            if p:
                p = (p[0], p[1] + lift, p[2])
                break
        if p:
            nodes.append(QD.Struct([
                (NAME, QD.Name(H(f"{zone_name}_start0"))), (POS, tuple(float(x) for x in p)),
                (H("Angles"), (0.0, 0.0, 0.0)), (CLS, QD.Name(H("restart"))), (H("type"), QD.Name(H("Player1"))),
                (0, QD.Name(CAS)), (H("RestartName"), "Start"),
                (H("restart_types"), QD.Array(13, [QD.Name(H("Player1"))]))]))
    return nodes


def _orig_pos(nqb, cls):
    _, items = F.read(nqb)
    na = max((i for i in items if isinstance(i.value, QD.Array)), key=lambda i: len(i.value.items))
    for s in na.value.items:
        if isinstance(s, QD.Struct):
            d = dict(s.items)
            if getattr(d.get(CLS), "crc", None) == H(cls) and d.get(POS):
                return d[POS]
    return None


class Source:
    """Also the base for other THAW-engine games (sources/pg.py): they set these class attributes."""
    GAME = GAME
    GENERATION = GENERATION
    ORIGIN = ORIGIN
    ZONE_HINTS = ZONE_HINTS
    LEVELS = LEVELS
    NAMES = NAMES
    PREBUILT = True

    def __init__(self, iso, cache_dir=None):
        self.iso = iso
        ents, _ = wad.parse_hed(I.read_file(iso, "/DATAP.HED;1"))
        self.ents = {e.name.lower(): e for e in ents}
        self.wad_off, _ = I.file_extent(iso, "/DATAP.WAD;1")

    def read(self, name):
        e = self.ents[name.lower()]
        with open(self.iso, "rb") as f:
            f.seek(self.wad_off + (e.offset & 0x1FFFFF) * 2048)  # 21-bit sector numbers, sign-extended
            return f.read(e.size)

    def levels(self):
        return [(c, self.NAMES[c]) for c in self.LEVELS]

    all_levels = levels

    def build_zone(self, code, template_zone, zone_name, template, disc=None):
        zb = self.read(f"\\worlds\\worldzones\\z_{code}\\z_{code}.pak.ps2")
        p = _parts(zb)
        nodes = thaw_nodes(p[".nqb"], zone_name)
        out, st = LC.assemble_level(template_zone, p[".tex"], p[".geom"], p[".col"], nodes, zone_name, template)
        st["nodes"] = len(nodes)
        return out, st
