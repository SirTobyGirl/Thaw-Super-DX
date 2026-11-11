"""usage: harness/build_testpark.py OUT.iso  - THAW + the generated test park only (shrunk), for in-game tests."""
import sys

sys.path.insert(0, ".")
from thaw_sandbox import cli
from thaw_sandbox.mapgen import GeneratedSource, testpark
from thaw_sandbox import build as B

WORK = "_workspace/e2e"
THAW = "iso/tony hawk's american wasteland (usa) (collector's edition).chd"
tex = testpark.boston_textures("iso/TonyHawksUnderground2.ISO", WORK)
src = GeneratedSource([("tp", "Test Park", lambda: (testpark.scene(), tex))])
orig = B.sources.open_source
B.sources.open_source = lambda iso, cache: src if iso == "GENERATED" else orig(iso, cache)
orig_img = B.disc_image
B.disc_image = lambda p, w: p if p == "GENERATED" else orig_img(p, w)
cli.run_build(THAW, [("GENERATED", None)], sys.argv[1], WORK, shrink=True)
