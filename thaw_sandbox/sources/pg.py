"""Tony Hawk's Proving Ground (PS2, NTSC-U SLUS-21616) as a level source.

Same engine and files as Project 8 (sources/p8.py, which does the work): THAW-format zone PAKs whose textures,
geometry and collision THAW reads as they are. Its areas (Philadelphia, Baltimore, Washington DC) become separate
levels; test, menu and helper zones are skipped.

PARKED (not in sources.ADAPTERS; user decision 2026-11-12): the levels load and skate but are not usable yet.
  * the city areas use a unit about 12x THAW's (collision 250-650 units across; Training, ~5300, is THAW scale):
    THAW's skater is a giant in them. Geometry, collision and nodes need scaling.
  * about half of each area's leaves store positions as V4_32 (fixed point, 12 fraction bits, absolute; leaf
    centre words 0) where THAW's microcode expects V4_16 relative to the leaf centre: they draw as shards.
  * Baltimore (z_bcity) crashed in the play check (TLB miss, pc 0x15dab4).
Plan: decode both vertex forms into triangles, scale city areas x12, rewrite geometry/collision with mapgen's
writers (keeping the texture dictionary), scale node positions; then re-test.
"""
from thaw_sandbox import iso_manager as I
from thaw_sandbox.sources import p8

GAME = "Proving Ground"
GENERATION = 9  # newer than Project 8
ORIGIN = {}
SERIALS = ("SLUS_216.16",)
LEVELS = ("love", "fdr", "slums", "bcity", "harbor", "lansdowne", "monuments", "museums", "museum_int", "training")
NAMES = {"love": "Love Park", "fdr": "FDR", "slums": "Slums", "bcity": "Baltimore", "harbor": "Inner Harbor",
         "lansdowne": "Lansdowne", "monuments": "Monuments", "museums": "Museums", "museum_int": "Museum Interior",
         "training": "PG Training"}
ZONE_HINTS = {"love": "z_lp", "fdr": "z_fd", "slums": "z_sl", "bcity": "z_bc", "harbor": "z_hb",
              "lansdowne": "z_ld", "monuments": "z_mo", "museums": "z_mu", "museum_int": "z_mi", "training": "z_pt"}


def detect(iso):
    try:
        cnf = I.read_file(iso, "/SYSTEM.CNF;1")
    except Exception:
        return False
    return any(s.encode() in cnf for s in SERIALS)


class Source(p8.Source):
    GAME = GAME
    GENERATION = GENERATION
    ORIGIN = ORIGIN
    ZONE_HINTS = ZONE_HINTS
    LEVELS = LEVELS
    NAMES = NAMES
