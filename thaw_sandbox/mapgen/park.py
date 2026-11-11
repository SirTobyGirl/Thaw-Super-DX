"""Skatepark kit: pieces placed by a layout (from the layout editor) built into a Scene.

Layout JSON:
  {"name": "...", "location": "...", "pieces": [{"type": T, "x": m, "y": m, "rot": deg, ...}, ...]}
x = metres east of the park centre, y = metres north, rot = degrees clockwise from north (the direction the
piece "faces": a quarter pipe's ramp, a bank's slope, a stair set's way down). Sizes in metres.

Types and fields (defaults in PIECES):
  quarter_pipe   length, height, deck            transition radius = 0.85 * height
  bank           length, width, height           a wedge rising away from the facing side
  box            length, width, height           grindable top edges (a ledge / manual pad)
  rail           length, height                  flat rail on posts
  stairs         width, steps, run               stair set going down in the facing direction, handrails
  pyramid        width, height, top              four banks around a flat top, grindable top edges
  mini_ramp      length, height, flat            two quarter pipes facing each other
  bowl           length, width, depth            sunken rectangular bowl, coping all round
"""
import math

from thaw_sandbox.mapgen.scene import Rail

U = 39.37
PIECES = {
    "quarter_pipe": {"length": 6.0, "height": 1.5, "deck": 1.5},
    "bank": {"length": 4.0, "width": 3.0, "height": 1.0},
    "box": {"length": 4.0, "width": 1.0, "height": 0.4},
    "rail": {"length": 5.0, "height": 0.45},
    "stairs": {"width": 3.0, "steps": 5, "run": 0.35},
    "pyramid": {"width": 6.0, "height": 1.0, "top": 2.0},
    "mini_ramp": {"length": 6.0, "height": 1.2, "flat": 3.0},
    "bowl": {"length": 10.0, "width": 7.0, "depth": 1.8},
}
LABELS = {"quarter_pipe": "Quarter pipe", "bank": "Bank", "box": "Box / ledge", "rail": "Rail", "stairs": "Stairs",
          "pyramid": "Pyramid", "mini_ramp": "Mini ramp", "bowl": "Bowl"}


def footprint(p):
    """Corners (metres, east/north) of a piece's footprint, for the editor and for flattening the ground."""
    t, d = p["type"], {**PIECES[p["type"]], **p}
    if t == "quarter_pipe":
        w, h = d["length"], 0.85 * d["height"] + d["deck"]
        return _rect(p, w, h, -0.85 * d["height"] / 2 + d["deck"] / 2)
    if t == "bank":
        return _rect(p, d["width"], d["length"], 0)
    if t == "box":
        return _rect(p, d["length"], d["width"], 0)
    if t == "rail":
        return _rect(p, d["length"], 0.3, 0)
    if t == "stairs":
        return _rect(p, d["width"], d["steps"] * d["run"], 0)
    if t == "pyramid":
        return _rect(p, d["width"], d["width"], 0)
    if t == "mini_ramp":
        r = 0.85 * d["height"]
        return _rect(p, d["length"], 2 * (r + 1.0) + d["flat"], 0)
    if t == "bowl":
        return _rect(p, d["width"], d["length"], 0)
    raise ValueError(t)


def _rect(p, across, along, shift):
    """Rectangle across x along (metres) centred on the piece, shifted along its facing axis."""
    a = math.radians(p.get("rot", 0.0))
    fx, fy = math.sin(a), math.cos(a)      # facing (east, north)
    rx, ry = math.cos(a), -math.sin(a)     # right of facing
    cx, cy = p["x"] + fx * shift, p["y"] + fy * shift
    return [(cx + rx * sa * across / 2 + fx * sb * along / 2, cy + ry * sa * across / 2 + fy * sb * along / 2)
            for sa, sb in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def build(sc, layout, to_world, ground_y):
    """Add the layout's pieces to the scene. to_world(east m, north m) -> (x, z) units around the park centre;
    ground_y: the park slab height (units)."""
    for p in layout.get("pieces", []):
        d = {**PIECES[p["type"]], **p}
        a = math.radians(p.get("rot", 0.0))
        fe, fn = math.sin(a), math.cos(a)

        def W(e, n, along=0.0, across=0.0):  # metres -> world (x, z), offsets along facing / to the right
            ee = e + fe * along + math.cos(a) * across
            nn = n + fn * along - math.sin(a) * across
            return to_world(ee, nn)
        y = ground_y
        t = p["type"]
        e0, n0 = p["x"], p["y"]
        if t == "quarter_pipe":
            # lip line across the piece; the ramp faces the facing direction, the deck is behind
            r = 0.85 * d["height"]
            L = d["length"] / 2
            fw = _dir(W(e0, n0), W(e0, n0, 1.0))
            _qp(sc, W(e0, n0, -r / 2, L), W(e0, n0, -r / 2, -L), fw, y, r * U, d["height"] * U, d["deck"] * U,
                "stone", "paving")
        elif t == "mini_ramp":
            r = 0.85 * d["height"]
            L, half = d["length"] / 2, d["flat"] / 2 + r
            fw = _dir(W(e0, n0), W(e0, n0, 1.0))
            _qp(sc, W(e0, n0, -half, L), W(e0, n0, -half, -L), fw, y, r * U, d["height"] * U, 1.0 * U, "wood", "wood")
            _qp(sc, W(e0, n0, half, -L), W(e0, n0, half, L), (-fw[0], -fw[1]), y, r * U, d["height"] * U, 1.0 * U,
                "wood", "wood")
        elif t == "bank":
            L, Wd = d["length"], d["width"] / 2
            _wedge(sc, W(e0, n0, L / 2, -Wd), W(e0, n0, L / 2, Wd), W(e0, n0, -L / 2, Wd), W(e0, n0, -L / 2, -Wd),
                   y, d["height"] * U)
        elif t == "box":
            c = [W(e0, n0, s1 * d["width"] / 2, s2 * d["length"] / 2) for s1, s2 in ((-1, -1), (-1, 1), (1, 1), (1, -1))]
            _prism(sc, c, y, y + d["height"] * U, "stone", top="paving")
            for i in range(4):
                if i % 2 == 0:  # long edges
                    sc.rails.append(Rail([(c[i][0], y + d["height"] * U, c[i][1]),
                                          (c[(i + 1) % 4][0], y + d["height"] * U, c[(i + 1) % 4][1])],
                                         "TERRAIN_GRINDCONC"))
        elif t == "rail":
            A, B = W(e0, n0, 0, -d["length"] / 2), W(e0, n0, 0, d["length"] / 2)
            sc.rail((A[0], y, A[1]), (B[0], y, B[1]), d["height"] * U, "metal")
        elif t == "stairs":
            n, run, rise = int(d["steps"]), d["run"], 0.16
            Wd = d["width"] / 2
            top = y + n * rise * U  # the stairs go down towards the facing direction, ending at the slab
            L = n * run
            for s in range(n):
                h0 = top - s * rise * U
                f0, f1 = -L / 2 + s * run, -L / 2 + (s + 1) * run
                c = [W(e0, n0, f0, -Wd), W(e0, n0, f0, Wd), W(e0, n0, f1, Wd), W(e0, n0, f1, -Wd)]
                _prism(sc, c, y, h0, "stone", top="paving", collide=False)
            c = [W(e0, n0, -L / 2, -Wd), W(e0, n0, -L / 2, Wd), W(e0, n0, L / 2, Wd), W(e0, n0, L / 2, -Wd)]
            hi, lo = top, y + rise * U
            p3 = [(c[0][0], hi, c[0][1]), (c[1][0], hi, c[1][1]), (c[2][0], lo, c[2][1]), (c[3][0], lo, c[3][1])]
            sc.quad(*p3, "paving", face=(0, 1, 0), render=False)  # collision slope
            # a top landing behind the stairs and handrails on both sides
            back = [W(e0, n0, -L / 2 - 1.5, -Wd), W(e0, n0, -L / 2 - 1.5, Wd), W(e0, n0, -L / 2, Wd), W(e0, n0, -L / 2, -Wd)]
            _prism(sc, back, y, top, "stone", top="paving")
            for side in (-1, 1):
                A, B = W(e0, n0, -L / 2, side * (Wd + 0.1)), W(e0, n0, L / 2, side * (Wd + 0.1))
                sc.rail((A[0], hi, A[1]), (B[0], lo, B[1]), 0.85 * U, "metal")
        elif t == "pyramid":
            Wd, T = d["width"] / 2, d["top"] / 2
            H = y + d["height"] * U
            outer = [W(e0, n0, s1 * Wd, s2 * Wd) for s1, s2 in ((-1, -1), (-1, 1), (1, 1), (1, -1))]
            inner = [W(e0, n0, s1 * T, s2 * T) for s1, s2 in ((-1, -1), (-1, 1), (1, 1), (1, -1))]
            ci = [(q[0], H, q[1]) for q in inner]
            sc.quad(*ci, "paving", face=(0, 1, 0))
            for i in range(4):
                o0, o1, i0, i1 = outer[i], outer[(i + 1) % 4], inner[i], inner[(i + 1) % 4]
                mid = ((o0[0] + o1[0]) / 2 - (i0[0] + i1[0]) / 2, (o0[1] + o1[1]) / 2 - (i0[1] + i1[1]) / 2)
                sc.quad((o0[0], y, o0[1]), (o1[0], y, o1[1]), (i1[0], H, i1[1]), (i0[0], H, i0[1]), "stone",
                        face=(mid[0], 1, mid[1]))
                sc.rails.append(Rail([ci[i], ci[(i + 1) % 4]], "TERRAIN_GRINDCONC"))
        elif t == "bowl":
            _bowl(sc, W, e0, n0, d, y)


def _dir(a, b):
    L = math.dist(a, b) or 1.0
    return ((b[0] - a[0]) / L, (b[1] - a[1]) / L)


def _qp(sc, A, B, face, y, radius, height, deck, mat, deck_mat):
    """Quarter pipe with its lip on A-B whose ramp faces the world direction face (x, z)."""
    tx, tz = B[0] - A[0], B[1] - A[1]
    if -tz * face[0] + tx * face[1] < 0:  # scene.quarter_pipe faces left of A->B: (-tz, tx)
        A, B = B, A
    sc.quarter_pipe(A, B, y, radius, height, deck, mat, deck_mat=deck_mat)


def _prism(sc, c, y0, y1, mat, top=None, collide=True):
    """Vertical prism over a 4-corner footprint (any winding)."""
    cen = (sum(q[0] for q in c) / 4, sum(q[1] for q in c) / 4)
    sc.quad(*[(q[0], y1, q[1]) for q in c], top or mat, face=(0, 1, 0), collide=collide)
    for i in range(4):
        a, b = c[i], c[(i + 1) % 4]
        out = ((a[0] + b[0]) / 2 - cen[0], 0, (a[1] + b[1]) / 2 - cen[1])
        sc.quad((a[0], y0, a[1]), (b[0], y0, b[1]), (b[0], y1, b[1]), (a[0], y1, a[1]), mat, face=out, collide=collide)


def _wedge(sc, lo_a, lo_b, hi_b, hi_a, y, h):
    """Bank: low edge lo_a-lo_b on the ground rising to hi_a-hi_b at height h, with sides and a back wall."""
    P = lambda q, yy: (q[0], yy, q[1])
    up = (hi_a[0] - lo_a[0], 0, hi_a[1] - lo_a[1])
    sc.quad(P(lo_a, y), P(lo_b, y), P(hi_b, y + h), P(hi_a, y + h), "stone",
            face=(-up[0], math.hypot(up[0], up[2]), -up[2]))
    sc.quad(P(hi_a, y), P(hi_b, y), P(hi_b, y + h), P(hi_a, y + h), "stone", face=up)
    for lo, hi, s in ((lo_a, hi_a, 1), (lo_b, hi_b, -1)):
        o = (lo_b[0] - lo_a[0], 0, lo_b[1] - lo_a[1])
        f = (-o[0] * s, 0, -o[2] * s)
        p0, p1, p2 = P(lo, y), P(hi, y), P(hi, y + h)
        n = ((p1[1] - p0[1]) * (p2[2] - p0[2]) - (p1[2] - p0[2]) * (p2[1] - p0[1]), 0,
             (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p1[1] - p0[1]) * (p2[0] - p0[0]))
        if n[0] * f[0] + n[2] * f[2] < 0:
            p1, p2 = p2, p1
        sc.tri(p0, p1, p2, "stone")
    sc.rails.append(Rail([P(hi_a, y + h), P(hi_b, y + h)], "TERRAIN_GRINDCONC"))


def _bowl(sc, W, e0, n0, d, y, steps=8, arc=6):
    """Sunken rectangular bowl with rounded corners: straight quarter-pipe walls, corner transitions swept
    around each corner, a flat bottom, decks and coping all round. The caller leaves the slab open above it."""
    D = d["depth"] * U
    r = min(0.8 * d["depth"], d["width"] / 3, d["length"] / 3)
    L2, W2, deck = d["length"] / 2, d["width"] / 2, 1.2
    bottom = y - D
    cen = W(e0, n0)
    sides = [((-L2, -W2 + r), (-L2, W2 - r)), ((-L2 + r, W2), (L2 - r, W2)), ((L2, W2 - r), (L2, -W2 + r)),
             ((L2 - r, -W2), (-L2 + r, -W2))]
    for (a1, b1), (a2, b2) in sides:
        A, B = W(e0, n0, a1, b1), W(e0, n0, a2, b2)
        mid = ((A[0] + B[0]) / 2, (A[1] + B[1]) / 2)
        _qp(sc, A, B, _dir(mid, cen), bottom, r * U, D, deck * U, "stone", "paving")
    inner = [W(e0, n0, s1 * (L2 - r), s2 * (W2 - r)) for s1, s2 in ((-1, -1), (-1, 1), (1, 1), (1, -1))]
    sc.quad(*[(q[0], bottom, q[1]) for q in inner], "paving", face=(0, 1, 0))
    # profile (outward distance, height) from the flat bottom's edge up to the lip
    prof = [(r * math.sin(math.pi / 2 * i / steps), r - r * math.cos(math.pi / 2 * i / steps)) for i in range(steps + 1)]
    prof = [(o * U, h * U) for o, h in prof]
    if D > prof[-1][1] + 1:
        prof.append((r * U, D))
    for s1, s2 in ((-1, -1), (-1, 1), (1, 1), (1, -1)):
        C = W(e0, n0, s1 * (L2 - r), s2 * (W2 - r))
        ua, ub = _dir(C, W(e0, n0, s1 * L2, s2 * (W2 - r))), _dir(C, W(e0, n0, s1 * (L2 - r), s2 * W2))
        dirs = []
        for k in range(arc + 1):
            f = math.pi / 2 * k / arc
            dx, dz = ua[0] * math.cos(f) + ub[0] * math.sin(f), ua[1] * math.cos(f) + ub[1] * math.sin(f)
            m = math.hypot(dx, dz)
            dirs.append((dx / m, dz / m))
        pt = lambda dd, o, h: (C[0] + dd[0] * o, bottom + h, C[1] + dd[1] * o)
        for k in range(arc):
            d0, d1 = dirs[k], dirs[k + 1]
            dm = ((d0[0] + d1[0]) / 2, (d0[1] + d1[1]) / 2)
            for (o0, h0), (o1, h1) in zip(prof, prof[1:]):
                th = math.atan2(o1 - o0, h1 - h0)  # 0 = flat, pi/2 = vertical
                face = (-dm[0] * math.sin(th), math.cos(th), -dm[1] * math.sin(th))
                sc.quad(pt(d0, o0, h0), pt(d1, o0, h0), pt(d1, o1, h1), pt(d0, o1, h1), "stone", flags=0x8, face=face)
        top = prof[-1][1]
        lip = [pt(dd, r * U, top) for dd in dirs]
        far = r * U + deck * U
        qa, qb = pt(ua, far, top), pt(ub, far, top)
        qc = (C[0] + (ua[0] + ub[0]) * far, bottom + top, C[1] + (ua[1] + ub[1]) * far)
        for k in range(arc):  # deck behind the corner: a fan from the outer corner
            sc.tri(*_up(qc, lip[k], lip[k + 1]), "paving")
        sc.tri(*_up(qc, qa, lip[0]), "paving")
        sc.tri(*_up(qc, lip[-1], qb), "paving")
        sc.rails.append(Rail(lip, "TERRAIN_GRINDCONC"))


def _up(a, b, c):
    """Triangle corners ordered to face up."""
    ny = (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2])
    return (a, b, c) if ny > 0 else (a, c, b)


def slab_holes(layout):
    """Footprints (metres) that the park slab must leave open (bowls)."""
    return [footprint(p) for p in layout.get("pieces", []) if p["type"] == "bowl"]
