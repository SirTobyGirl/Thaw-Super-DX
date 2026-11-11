"""usage: harness/build_osm.py OUT.iso [OSM.json ELEV.json LAT LON RADIUS NAME]  - THAW + a level generated from
OpenStreetMap + elevation (default: Durham, plus code 9C6WQCGF+QP), shrunk, for in-game tests."""
import sys

sys.path.insert(0, ".")
from thaw_sandbox import build as B, cli
from thaw_sandbox.mapgen import GeneratedSource, osm, testpark

WORK = "_workspace/e2e"
THAW = "iso/tony hawk's american wasteland (usa) (collector's edition).chd"
a = sys.argv[1:] + [None] * 7
out = a[0]
po, pe = a[1] or "_workspace/mapgen/durham.json", a[2] or "_workspace/mapgen/durham_elev.json"
lat, lon = float(a[3] or 54.776938), float(a[4] or -1.575687)
radius, name = float(a[5] or 150), a[6] or "Durham"
PICKS = {"paving": 16, "grass": 52, "asphalt": 10, "path": 1, "brick": 12, "stone": 4, "roof": 11, "wood": 71,
         "metal": 6}
tex = testpark.boston_textures("iso/TonyHawksUnderground2.ISO", WORK, PICKS)
data, elev = osm.load(po, pe)


def make():
    sc = osm.build(data, elev, lat, lon, radius)
    print(f"scene: {len(sc.quads)} quads, {len(sc.tris)} tris, {len(sc.rails)} rails")
    return sc, tex


src = GeneratedSource([("du", name, make)])
orig = B.sources.open_source
B.sources.open_source = lambda iso, cache: src if iso == "GENERATED" else orig(iso, cache)
orig_img = B.disc_image
B.disc_image = lambda p, w: p if p == "GENERATED" else orig_img(p, w)
cli.run_build(THAW, [("GENERATED", None)], out, WORK, shrink=True)
