"""Real-world blockout: OpenStreetMap features + an elevation grid -> Scene.

Data: OpenStreetMap (Overpass JSON with 'out body geom'; (c) OpenStreetMap contributors, ODbL) and an elevation grid
(e.g. EU-DEM 25 m via OpenTopoData). Frame: 1 m = 39.37 units, x = east, z = south (Neversoft: Y up, Z = -north),
y = height above the lowest grid sample. The level is the square of half size `radius` metres around the centre.

What becomes what (first pass):
  terrain     ground grid draped over the elevation (grass where OSM says grass/park, else paving)
  roads       asphalt ribbons just above the terrain; footways / pedestrian streets: paving ribbons
  buildings   footprint walls + flat roof (height from height / building:levels, else 3 storeys)
  steps       stair set with a smooth collision slope and grindable handrails on both sides
  benches     grindable ledges;  barrier=wall: low grindable walls;  bollards, street lamps: posts
  boundary    walls around the square; start point at the centre
"""
import json
import math

from thaw_sandbox.mapgen.scene import Material, Scene

U = 39.37          # units per metre
CELL = 150.0       # terrain grid cell (units)
LIFT = {"road": 2.5, "path": 3.5}  # ribbons above the terrain (units)
ROAD_W = {"trunk": 9.0, "primary": 8.0, "secondary": 7.5, "tertiary": 7.0, "unclassified": 6.0,
          "residential": 6.0, "service": 4.0, "living_street": 5.0}
PATH_W = {"pedestrian": 6.0, "footway": 2.5, "path": 2.0, "cycleway": 2.5}
STOREY = 3.3
KERB_W, KERB_H = 14.0, 7.0  # kerb strip width / height (units)
GRASS = {("landuse", "grass"), ("leisure", "park"), ("landuse", "recreation_ground"), ("leisure", "garden"),
         ("natural", "grassland"), ("landuse", "meadow"), ("natural", "wood")}


class Terrain:
    """Bilinear height (units) from a regular lat/lon grid of n x n samples (row 0 = south)."""

    def __init__(self, samples, n, radius):
        e = [s["elevation"] if s.get("elevation") is not None else 0.0 for s in samples]
        self.n, self.r, self.lo = n, radius * U, min(e)
        self.e = [(v - self.lo) * U for v in e]

    def h(self, x, z):
        n = self.n
        gj = (x + self.r) / (2 * self.r) * (n - 1)          # east
        gi = (-z + self.r) / (2 * self.r) * (n - 1)         # north (row index)
        gi, gj = min(max(gi, 0), n - 1.0001), min(max(gj, 0), n - 1.0001)
        i0, j0 = int(gi), int(gj)
        fi, fj = gi - i0, gj - j0
        e = self.e
        return (e[i0 * n + j0] * (1 - fi) * (1 - fj) + e[(i0 + 1) * n + j0] * fi * (1 - fj) +
                e[i0 * n + j0 + 1] * (1 - fi) * fj + e[(i0 + 1) * n + j0 + 1] * fi * fj)


def _inside(pt, poly):
    x, z = pt
    c = False
    for (x1, z1), (x2, z2) in zip(poly, poly[1:] + poly[:1]):
        if (z1 > z) != (z2 > z) and x < (x2 - x1) * (z - z1) / (z2 - z1) + x1:
            c = not c
    return c


def _area(poly):
    return sum(x1 * z2 - x2 * z1 for (x1, z1), (x2, z2) in zip(poly, poly[1:] + poly[:1])) / 2


def _ears(poly):
    """Ear-clipping triangulation of a simple polygon [(x, z)] -> index triples (any winding)."""
    idx = list(range(len(poly)))
    if _area(poly) < 0:
        idx.reverse()
    out, guard = [], 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        for k in range(len(idx)):
            a, b, c = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            (ax, az), (bx, bz), (cx, cz) = poly[a], poly[b], poly[c]
            if (bx - ax) * (cz - az) - (bz - az) * (cx - ax) <= 0:
                continue  # reflex
            if any(_in_tri(poly[p], poly[a], poly[b], poly[c]) for p in idx if p not in (a, b, c)):
                continue
            out.append((a, b, c))
            idx.pop(k)
            break
        else:
            break
    if len(idx) == 3:
        out.append(tuple(idx))
    return out


def _in_tri(p, a, b, c):
    def s(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
    d1, d2, d3 = s(p, a, b), s(p, b, c), s(p, c, a)
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


class Durham:  # generic, named after the first place it was made for
    pass


def find_park(osm, lat0, lon0):
    """The skatepark nearest the centre: (outline [(east m, north m)], centre (east m, north m)) or None."""
    kx = 111320 * math.cos(math.radians(lat0))
    best = None
    for w in osm["elements"]:
        t = w.get("tags", {})
        if w["type"] != "way" or "geometry" not in w:
            continue
        if not (t.get("leisure") == "skatepark" or t.get("sport") in ("skateboard", "skateboarding")):
            continue
        poly = [((g["lon"] - lon0) * kx, (g["lat"] - lat0) * 111320) for g in w["geometry"]]
        if len(poly) > 3 and poly[0] == poly[-1]:
            poly = poly[:-1]
        c = (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))
        d = math.hypot(*c)
        if best is None or d < best[0]:
            best = (d, poly, c)
    return (best[1], best[2]) if best and best[0] < 400 else None


def build(osm, elev, lat0, lon0, radius=150.0, n_elev=13, materials=None, park_layout=None):
    """osm: Overpass JSON; elev: n x n samples (OpenTopoData results); park_layout: skatepark pieces (park.py)
    placed around the skatepark outline found in the data (or the centre) -> Scene."""
    sc = Scene()
    sc.materials = materials or {
        "paving": Material("paving", 160), "grass": Material("grass", 256), "asphalt": Material("asphalt", 320),
        "path": Material("path", 160), "brick": Material("brick", 160), "stone": Material("stone", 200),
        "roof": Material("roof", 200), "wood": Material("wood", 96), "metal": Material("metal", 64)}
    T = Terrain(elev, n_elev, radius)
    R = radius * U
    kx = 111320 * math.cos(math.radians(lat0))

    def P(lat, lon):
        return ((lon - lon0) * kx * U, -(lat - lat0) * 111320 * U)

    def inb(p, m=0.0):
        return abs(p[0]) <= R - m and abs(p[1]) <= R - m

    els = osm["elements"]
    ways = [w for w in els if w["type"] == "way" and "geometry" in w]
    grass, buildings = [], []
    for w in ways:
        t = w.get("tags", {})
        pts = [P(g["lat"], g["lon"]) for g in w["geometry"]]
        if len(pts) >= 4 and pts[0] == pts[-1]:
            poly = pts[:-1]
            if any((k, t.get(k)) in GRASS for k in ("landuse", "leisure", "natural")):
                grass.append(poly)
            if "building" in t and sum(inb(p) for p in poly) >= len(poly) * 0.6:
                buildings.append((poly, t))

    def bbox(poly):
        xs, zs = [p[0] for p in poly], [p[1] for p in poly]
        return min(xs), min(zs), max(xs), max(zs)
    bb_build = [(bbox(p), p) for p, _ in buildings]
    bb_grass = [(bbox(p), p) for p in grass]

    def hit(pt, polys):
        return any(b[0] <= pt[0] <= b[2] and b[1] <= pt[1] <= b[3] and _inside(pt, p) for b, p in polys)

    # ---- skatepark area: a flat slab over the park outline (cells of the ground grid it replaces)
    park_poly = park_c = None
    if park_layout is not None:
        found = find_park(osm, lat0, lon0)
        if found:
            park_poly = [(e * U, -n_ * U) for e, n_ in found[0]]
            park_c = (found[1][0] * U, -found[1][1] * U)
        else:
            park_c = (0.0, 0.0)
            park_poly = [(x * U, z * U) for x, z in ((-30, -30), (30, -30), (30, 30), (-30, 30))]
        park_bb = [(bbox(park_poly), park_poly)]
        park_y = sum(T.h(*q) for q in park_poly) / len(park_poly)
        from thaw_sandbox.mapgen import park as PK
        to_world = lambda e, n_: (park_c[0] + e * U, park_c[1] - n_ * U)
        holes = [[to_world(*q) for q in h] for h in PK.slab_holes(park_layout)]
        hole_bb = [(bbox(h), h) for h in holes]

    # ---- terrain
    n = int(2 * R // CELL)
    step = 2 * R / n
    slab_cells = []
    for i in range(n):
        for j in range(n):
            x0, z0 = -R + j * step, -R + i * step
            x1, z1 = x0 + step, z0 + step
            c = ((x0 + x1) / 2, (z0 + z1) / 2)  # ground also runs under buildings: walls go below it
            if park_poly and hit(c, park_bb):
                slab_cells.append((x0, z0))
                continue
            mat = "grass" if hit(c, bb_grass) else "paving"
            # quad with up normal: (x0,z0) (x0,z1) (x1,z1) (x1,z0) is counter-clockwise seen from above
            sc.quad((x0, T.h(x0, z0), z0), (x0, T.h(x0, z1), z1), (x1, T.h(x1, z1), z1), (x1, T.h(x1, z0), z0), mat)
    if park_poly:
        k = 4
        sub = step / k
        for x0, z0 in slab_cells:
            subs = []
            for a in range(k):
                for b in range(k):
                    sx, sz = x0 + b * sub, z0 + a * sub
                    corners = [(sx, sz), (sx, sz + sub), (sx + sub, sz + sub), (sx + sub, sz)]
                    if not any(hit(q, hole_bb) for q in corners):
                        subs.append(corners)
            if len(subs) == k * k:  # no bowl opening here: one quad
                subs = [[(x0, z0), (x0, z0 + step), (x0 + step, z0 + step), (x0 + step, z0)]]
            for corners in subs:
                sc.quad(*[(x, park_y, z) for x, z in corners], "paving", face=(0, 1, 0))
            for (ex, ez), (fx, fz) in (((x0, z0), (x0 + step, z0)), ((x0 + step, z0), (x0 + step, z0 + step)),
                                       ((x0 + step, z0 + step), (x0, z0 + step)), ((x0, z0 + step), (x0, z0))):
                mid = ((ex + fx) / 2, (ez + fz) / 2)  # slab edge where it meets the sloped ground: a small step
                out = (mid[0] - (x0 + step / 2), 0, mid[1] - (z0 + step / 2))
                ny = (mid[0] + out[0] * 0.05, mid[1] + out[2] * 0.05)
                if (ny[0] - step / 2, ny[1] - step / 2) and any(
                        abs(ny[0] - (cx + step / 2)) < step / 2 and abs(ny[1] - (cz + step / 2)) < step / 2
                        for cx, cz in slab_cells):
                    continue
                ha, hb = T.h(ex, ez), T.h(fx, fz)
                lo_a, lo_b = min(ha, park_y) - 4, min(hb, park_y) - 4
                hi_a, hi_b = max(ha, park_y), max(hb, park_y)
                if hi_a - lo_a > 6 or hi_b - lo_b > 6:
                    sc.quad((ex, lo_a, ez), (fx, lo_b, fz), (fx, hi_b, fz), (ex, hi_a, ez), "stone", face=out)
        PK.build(sc, park_layout, to_world, park_y)

    # ---- ribbons (roads, paths) with mitred joins; kerbs along roads
    def dense(pts, step=220.0):
        seq = []
        for a, b in zip(pts, pts[1:]):
            k = max(1, math.ceil(math.dist(a, b) / step))
            seq += [(a[0] + (b[0] - a[0]) * s / k, a[1] + (b[1] - a[1]) * s / k) for s in range(k)]
        seq.append(pts[-1])
        out = [seq[0]]
        for p in seq[1:]:
            if math.dist(p, out[-1]) > 1:
                out.append(p)
        return out

    def offsets(seq, hw):
        """Per-vertex left offsets (mitred, clamped)."""
        segs = []
        for a, b in zip(seq, seq[1:]):
            L = math.dist(a, b)
            segs.append((-(b[1] - a[1]) / L, (b[0] - a[0]) / L))
        out = []
        for i in range(len(seq)):
            ns = [segs[j] for j in (i - 1, i) if 0 <= j < len(segs)]
            mx, mz = sum(n[0] for n in ns), sum(n[1] for n in ns)
            m = math.hypot(mx, mz) or 1.0
            mx, mz = mx / m, mz / m
            cos = max(0.5, mx * ns[0][0] + mz * ns[0][1])
            out.append((mx * hw / cos, mz * hw / cos))
        return out

    def ribbon(seq, hw, mat, lift):
        offs = offsets(seq, hw)
        for i in range(len(seq) - 1):
            (ax, az), (bx, bz) = seq[i], seq[i + 1]
            (oax, oaz), (obx, obz) = offs[i], offs[i + 1]
            q = [(ax + oax, az + oaz), (bx + obx, bz + obz), (bx - obx, bz - obz), (ax - oax, az - oaz)]
            sc.quad(*[(x, T.h(x, z) + lift, z) for x, z in q], mat, face=(0, 1, 0), collide=False)
        return offs

    roads, paths = [], []
    for w in ways:
        t = w.get("tags", {})
        h = t.get("highway")
        pts = [P(g["lat"], g["lon"]) for g in w["geometry"]]
        if h in ROAD_W:
            roads.append((pts, ROAD_W[h] * U / 2))
        elif h in PATH_W and t.get("area") != "yes":
            paths.append((pts, PATH_W[h] * U / 2))

    def clip(seq, m):
        """Pieces of seq inside the level (margin m)."""
        runs, cur = [], []
        for p in seq:
            if inb(p, m):
                cur.append(p)
            elif cur:
                runs.append(cur)
                cur = []
        if cur:
            runs.append(cur)
        return [r for r in runs if len(r) >= 2]

    def on_road(p, pad):
        for pts, hw in roads:
            for a, b in zip(pts, pts[1:]):
                ex, ez = b[0] - a[0], b[1] - a[1]
                L2 = ex * ex + ez * ez or 1.0
                t = max(0.0, min(1.0, ((p[0] - a[0]) * ex + (p[1] - a[1]) * ez) / L2))
                if math.dist(p, (a[0] + ex * t, a[1] + ez * t)) < hw + pad:
                    return True
        return False

    for pts, hw in paths:
        for run in clip(dense(pts), hw):
            ribbon(run, hw, "path", LIFT["path"])
    for pts, hw in roads:
        for run in clip(dense(pts), hw + KERB_W):
            offs = ribbon(run, hw, "asphalt", LIFT["road"])
            for side in (1, -1):
                edge = [(p[0] + side * o[0], p[1] + side * o[1]) for p, o in zip(run, offs)]
                kerbs(sc, T, edge, run, side, lambda q: on_road(q, 2.0))
    # ---- buildings
    for k, (poly, t) in enumerate(buildings):
        try:
            hm = float(t.get("height", "").split()[0])
        except (ValueError, IndexError):
            try:
                hm = float(t.get("building:levels")) * STOREY + 1.0
            except (TypeError, ValueError):
                hm = 3 * STOREY + (k % 3) * 1.5  # untagged: 3 storeys, a little variety
        base = min(T.h(x, z) for x, z in poly) - 20
        top = max(T.h(x, z) for x, z in poly) + hm * U
        mat = ("brick", "stone")[k % 2]
        if _area(poly) < 0:  # make the footprint counter-clockwise seen from above (x east, z south)
            poly = poly[::-1]
        for (ax, az), (bx, bz) in zip(poly, poly[1:] + poly[:1]):
            mx, mz = (ax + bx) / 2, (az + bz) / 2
            ex, ez = bx - ax, bz - az
            out = (ez, 0, -ex)  # outward normal for a counter-clockwise ring in this frame
            if not _inside((mx + out[0] * 0.01, mz + out[2] * 0.01), poly):
                pass
            else:
                out = (-ez, 0, ex)
            sc.quad((ax, base, az), (bx, base, bz), (bx, top, bz), (ax, top, az), mat, face=out)
        for a, b, c in _ears(poly):
            p = [(poly[i][0], top, poly[i][1]) for i in (a, b, c)]
            n_ = ((p[1][2] - p[0][2]) * (p[2][0] - p[0][0]) - (p[1][0] - p[0][0]) * (p[2][2] - p[0][2]))
            if n_ < 0:
                p[1], p[2] = p[2], p[1]
            sc.tri(*p, "roof")

    # ---- steps
    for w in ways:
        t = w.get("tags", {})
        if t.get("highway") != "steps":
            continue
        pts = [P(g["lat"], g["lon"]) for g in w["geometry"]]
        for a, b in zip(pts, pts[1:]):
            if not (inb(a, 100) and inb(b, 100)):
                continue
            stairs(sc, T, a, b, float(t.get("width", 2.4)) * U)

    # ---- point features
    for nd in els:
        if nd["type"] != "node":
            continue
        t = nd.get("tags", {})
        x, z = P(nd["lat"], nd["lon"])
        if not inb((x, z), 100):
            continue
        y = T.h(x, z)
        if t.get("amenity") == "bench":
            sc.ledge((x - 36, y, z - 12), (x + 36, y + 18, z + 12), "wood", edges=("z0", "z1"))
        elif t.get("barrier") == "bollard":
            sc.box((x - 5, y, z - 5), (x + 5, y + 38, z + 5), "metal")
        elif t.get("highway") == "street_lamp":
            sc.box((x - 3, y, z - 3), (x + 3, y + 220, z + 3), "metal")
    for w in ways:
        t = w.get("tags", {})
        if t.get("barrier") != "wall":
            continue
        pts = [P(g["lat"], g["lon"]) for g in w["geometry"]]
        for a, b in zip(pts, pts[1:]):
            if inb(a, 60) and inb(b, 60):
                low_wall(sc, T, a, b)

    # ---- boundary walls and start
    corners = [(-R, -R), (R, -R), (R, R), (-R, R)]
    for a, b in zip(corners, corners[1:] + corners[:1]):
        k = max(1, math.ceil(math.dist(a, b) / 400))
        for s in range(k):
            p = (a[0] + (b[0] - a[0]) * s / k, a[1] + (b[1] - a[1]) * s / k)
            q = (a[0] + (b[0] - a[0]) * (s + 1) / k, a[1] + (b[1] - a[1]) * (s + 1) / k)
            mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            sc.quad((p[0], T.h(*p) - 40, p[1]), (q[0], T.h(*q) - 40, q[1]), (q[0], T.h(*q) + 700, q[1]),
                    (p[0], T.h(*p) + 700, p[1]), "brick", face=(-mid[0], 0, -mid[1]))
    # ---- quarter pipes along the boundary (inside the walls), where no building is in the way
    QP_R, QP_H, QP_DECK, QP_LEN = 140.0, 170.0, 150.0, 560.0
    for a, b in zip(corners, corners[1:] + corners[:1]):
        L = math.dist(a, b)
        tx, tz = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        nx, nz = -tz, tx  # inwards (left of a->b)
        k = int((L - 2 * QP_DECK) // (QP_LEN + 40))
        for s_ in range(k):
            d0 = QP_DECK + 20 + s_ * (QP_LEN + 40)
            p0 = (a[0] + tx * d0 + nx * QP_DECK, a[1] + tz * d0 + nz * QP_DECK)
            p1 = (p0[0] + tx * QP_LEN, p0[1] + tz * QP_LEN)
            foot = [(p0[0] + tx * u + nx * v, p0[1] + tz * u + nz * v)
                    for u in (0, QP_LEN / 2, QP_LEN) for v in (-QP_DECK, 0, QP_R)]
            if any(hit(q, bb_build) for q in foot):
                continue
            y = min(T.h(*q) for q in foot) - 4
            sc.quarter_pipe(p0, p1, y, QP_R, QP_H, QP_DECK, "stone", deck_mat="paving")
    if park_c is not None:
        sc.starts.append(((park_c[0], park_y + 10, park_c[1]), 0.0))
    else:
        sc.start((0.0, T.h(0, 0) + 10, 0.0), 0.0)
    return sc


def stairs(sc, T, a, b, width, rise=14.0):
    """A stair set along a->b (x, z) between the terrain heights at its ends, with handrails on both sides."""
    ya, yb = T.h(*a), T.h(*b)
    if yb > ya:  # build downhill from a
        a, b, ya, yb = b, a, yb, ya
    L = math.dist(a, b)
    if L < 40:
        return
    tx, tz = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    nx, nz = -tz * width / 2, tx * width / 2
    drop = max(ya - yb, 0.0)
    k = max(2, int(drop // rise)) if drop > 2 * rise else 0
    if k:  # visible treads (render only); collision is the slope below
        for s in range(k):
            y = ya - drop * s / k
            p0 = (a[0] + tx * L * s / k, a[1] + tz * L * s / k)
            p1 = (a[0] + tx * L * (s + 1) / k, a[1] + tz * L * (s + 1) / k)
            c = [(p0[0] + nx, p0[1] + nz), (p1[0] + nx, p1[1] + nz), (p1[0] - nx, p1[1] - nz), (p0[0] - nx, p0[1] - nz)]
            sc.quad(*[(x, y, z) for x, z in c], "stone", face=(0, 1, 0), collide=False)
            y2 = ya - drop * (s + 1) / k
            sc.quad((p1[0] + nx, y2, p1[1] + nz), (p1[0] - nx, y2, p1[1] - nz), (p1[0] - nx, y, p1[1] - nz),
                    (p1[0] + nx, y, p1[1] + nz), "stone", face=(tx, 0, tz), collide=False)
    c = [(a[0] + nx, ya + 2, a[1] + nz), (b[0] + nx, yb + 2, b[1] + nz), (b[0] - nx, yb + 2, b[1] - nz),
         (a[0] - nx, ya + 2, a[1] - nz)]
    sc.quad(*c, "stone", face=(0, 1, 0), render=not k)
    for side in (1, -1):  # handrails
        o = (side * nx * 1.05, side * nz * 1.05)
        sc.rail((a[0] + o[0], ya, a[1] + o[1]), (b[0] + o[0], yb, b[1] + o[1]), 32, "metal")


def low_wall(sc, T, a, b, h=32.0, t=8.0):
    L = math.dist(a, b)
    if L < 20:
        return
    nx, nz = -(b[1] - a[1]) / L * t, (b[0] - a[0]) / L * t
    ya, yb = T.h(*a), T.h(*b)
    top_a, top_b = ya + h, yb + h
    sc.quad((a[0] - nx, top_a, a[1] - nz), (a[0] + nx, top_a, a[1] + nz), (b[0] + nx, top_b, b[1] + nz),
            (b[0] - nx, top_b, b[1] - nz), "stone", face=(0, 1, 0))
    for s in (1, -1):
        sc.quad((a[0] + s * nx, ya - 10, a[1] + s * nz), (b[0] + s * nx, yb - 10, b[1] + s * nz),
                (b[0] + s * nx, top_b, b[1] + s * nz), (a[0] + s * nx, top_a, a[1] + s * nz), "stone",
                face=(s * nx, 0, s * nz))
    from thaw_sandbox.mapgen.scene import Rail
    sc.rails.append(Rail([(a[0], top_a, a[1]), (b[0], top_b, b[1])], "TERRAIN_GRINDCONC"))


def load(path_osm, path_elev):
    return json.load(open(path_osm)), json.load(open(path_elev))


def kerbs(sc, T, edge, centre, side, blocked):
    """Raised kerb strip just outside a road edge, cut where it would cross another road; grindable (one rail per
    continuous run, along the road-side top edge)."""
    from thaw_sandbox.mapgen.scene import Rail
    run = []

    def flush():
        if len(run) >= 2:
            sc.rails.append(Rail([(x, T.h(x, z) + KERB_H, z) for x, z in run], "TERRAIN_GRINDCONC"))
        run.clear()
    for i in range(len(edge) - 1):
        a, b = edge[i], edge[i + 1]
        L = math.dist(a, b)
        if L < 1:
            continue
        ox, oz = (a[0] - centre[i][0]), (a[1] - centre[i][1])
        m = math.hypot(ox, oz) or 1.0
        ox, oz = ox / m * KERB_W, oz / m * KERB_W
        ox2, oz2 = (b[0] - centre[i + 1][0]), (b[1] - centre[i + 1][1])
        m2 = math.hypot(ox2, oz2) or 1.0
        ox2, oz2 = ox2 / m2 * KERB_W, oz2 / m2 * KERB_W
        mid = ((a[0] + b[0]) / 2 + (ox + ox2) / 4, (a[1] + b[1]) / 2 + (oz + oz2) / 4)
        if blocked(mid):
            flush()
            continue
        A, B = (a[0] + ox, a[1] + oz), (b[0] + ox2, b[1] + oz2)
        h = lambda p, d=0.0: T.h(*p) + d
        sc.quad((a[0], h(a, KERB_H), a[1]), (b[0], h(b, KERB_H), b[1]), (B[0], h(B, KERB_H), B[1]),
                (A[0], h(A, KERB_H), A[1]), "stone", face=(0, 1, 0))
        sc.quad((a[0], h(a, -2), a[1]), (b[0], h(b, -2), b[1]), (b[0], h(b, KERB_H), b[1]), (a[0], h(a, KERB_H), a[1]),
                "stone", face=(-ox, 0, -oz))
        sc.quad((A[0], h(A, -2), A[1]), (B[0], h(B, -2), B[1]), (B[0], h(B, KERB_H), B[1]), (A[0], h(A, KERB_H), A[1]),
                "stone", face=(ox, 0, oz))
        if not run:
            run.append(a)
        run.append(b)
    flush()
