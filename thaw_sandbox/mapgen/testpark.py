"""Proof level: a walled plaza with a quarter pipe, a ledge, a kicker, a handrail and a road strip, textured
with THUG2 Boston textures from the user's disc."""
from thaw_sandbox import build as B, sources, thug2_tex as T2
from thaw_sandbox.mapgen.scene import Material, Scene

# Boston (THUG2 'bo') textures >= 64 px, in disc order (see the contact sheet tool)
PICKS = {"ground": 37, "asphalt": 10, "brick": 12, "ramp": 8, "wood": 71, "metal": 6}


def boston_textures(thug2_disc, work, picks=None):
    s = sources.open_source(B.disc_image(thug2_disc, work), f"{work}/cache")
    f = s.level_files("bo")
    _, t2 = T2.parse(f["tex"])
    refs = s.resolve_texture_refs(t2)
    ts = []
    for x in t2:
        src = x if x.mips else refs.get(x.crc)
        if src is not None and src.width >= 64 and src.height >= 64:
            ts.append(src)
    return {m: ts[i] for m, i in (picks or PICKS).items()}


def scene():
    sc = Scene()
    sc.materials = {"ground": Material("ground", 192), "asphalt": Material("asphalt", 256),
                    "brick": Material("brick", 128), "ramp": Material("ramp", 160), "wood": Material("wood", 128),
                    "metal": Material("metal", 64)}
    W = 2400.0  # plaza half size
    sc.ground(-W, -W, W, -600, 0, "ground")
    sc.ground(-W, -600, W, 600, -6, "asphalt")  # road strip, a kerb lower
    sc.ground(-W, 600, W, W, 0, "ground")
    sc.quad((-W, -6, -600), (W, -6, -600), (W, 0, -600), (-W, 0, -600), "ground", face=(0, 0, 1))
    sc.quad((W, -6, 600), (-W, -6, 600), (-W, 0, 600), (W, 0, 600), "ground", face=(0, 0, -1))
    for a, b in (((-W, -W), (W, -W)), ((W, -W), (W, W)), ((W, W), (-W, W)), ((-W, W), (-W, -W))):
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)  # boundary walls face inwards
        sc.quad((a[0], -6, a[1]), (b[0], -6, b[1]), (b[0], 600, b[1]), (a[0], 600, a[1]), "brick",
                face=(-mid[0], 0, -mid[1]))
    sc.quarter_pipe((1200, 2150), (-1200, 2150), 0, 120, 150, 200, "ramp", deck_mat="wood")  # faces -z
    sc.ledge((-800, 0, -1600), (400, 24, -1450), "brick", top="ground")
    sc.ramp((900, -1700), (1300, -1700), 0, 180, 60, "ramp")
    sc.rail((-1500, 0, 1200), (-300, 0, 1200), 28, "metal")
    sc.start((0.0, 0.0, -2000.0), 0.0)
    return sc
