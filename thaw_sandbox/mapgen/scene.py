"""A level as plain geometry: textured, collidable quads/triangles plus rails and start points.

Units are THAW's (about 1 inch; a skater is ~72 tall), Y is up. Surfaces are given front-facing by the right-hand
rule: for a quad p0..p3 (counter-clockwise seen from the front) the normal is (p1-p0) x (p3-p0). Large quads are
tiled (render leaves and collision objects must stay small: positions are stored as 16-bit offsets).
"""
import math
from dataclasses import dataclass, field

TILE = 512.0  # max quad edge after tiling
SUN = (0.45, 0.8, 0.35)  # baked lighting direction (normalised below)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    n = math.sqrt(sum(x * x for x in a)) or 1.0
    return tuple(x / n for x in a)


def _lerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


_SUN = _norm(SUN)


@dataclass
class Material:
    name: str            # key into the level's texture list
    scale: float = 256.0  # world units per texture repeat
    terrain: int = 0      # collision terrain type index (0 = default)


@dataclass
class Tri:
    p: tuple             # 3 positions, front-facing by the right-hand rule
    uv: tuple            # 3 (u, v)
    col: tuple           # 3 (r, g, b, a), 128 = 1.0
    material: str
    flags: int = 0       # collision face flags (0x8 = vert / quarter pipe)
    terrain: int = 0
    render: bool = True
    collide: bool = True


@dataclass
class Quad:  # kept as a quad so it renders as one 4-vertex strip
    p: tuple
    uv: tuple
    col: tuple
    material: str
    flags: int = 0
    terrain: int = 0
    render: bool = True
    collide: bool = True

    def tris(self):
        a, b, c, d = range(4)
        return [Tri(tuple(self.p[i] for i in t), tuple(self.uv[i] for i in t), tuple(self.col[i] for i in t),
                    self.material, self.flags, self.terrain, self.render, self.collide) for t in ((a, b, c), (a, c, d))]


@dataclass
class Rail:
    points: list         # polyline [(x, y, z)]
    terrain: str = "TERRAIN_GRINDMETAL"
    climb: bool = False


@dataclass
class Scene:
    materials: dict = field(default_factory=dict)  # name -> Material
    quads: list = field(default_factory=list)
    tris: list = field(default_factory=list)
    rails: list = field(default_factory=list)
    starts: list = field(default_factory=list)  # [(pos, heading radians)]

    # ---------------------------------------------------------------- primitives
    def _shade(self, n, tint=(128, 128, 128)):
        k = 0.62 + 0.38 * max(0.0, sum(a * b for a, b in zip(n, _SUN)))
        return tuple(min(255, int(c * k)) for c in tint) + (128,)

    def _uv(self, p, n, mat):
        s = self.materials[mat].scale
        ax = max(range(3), key=lambda i: abs(n[i]))
        if ax == 1:
            u, v = p[0], p[2]
        elif ax == 0:
            u, v = p[2], -p[1]
        else:
            u, v = p[0], -p[1]
        return (u / s, v / s)

    def quad(self, p0, p1, p2, p3, mat, flags=0, tint=(128, 128, 128), render=True, collide=True, uv=None,
             face=None):
        """Front-facing quad (counter-clockwise from the front), tiled to TILE. face: a direction the quad must
        face; the corner order is reversed when it does not."""
        n = _norm(_cross(_sub(p1, p0), _sub(p3, p0)))
        if face is not None and sum(a * b for a, b in zip(n, face)) < 0:
            p0, p1, p2, p3 = p3, p2, p1, p0
            n = tuple(-x for x in n)
        nu = max(1, math.ceil(max(math.dist(p0, p1), math.dist(p3, p2)) / TILE))
        nv = max(1, math.ceil(max(math.dist(p0, p3), math.dist(p1, p2)) / TILE))
        col = self._shade(n, tint)
        terr = self.materials[mat].terrain

        def at(i, j):
            return _lerp(_lerp(p0, p1, i / nu), _lerp(p3, p2, i / nu), j / nv)
        for i in range(nu):
            for j in range(nv):
                ps = (at(i, j), at(i + 1, j), at(i + 1, j + 1), at(i, j + 1))
                uvs = tuple(uv(q) for q in ps) if uv else tuple(self._uv(q, n, mat) for q in ps)
                self.quads.append(Quad(ps, uvs, (col,) * 4, mat, flags, terr, render, collide))

    def tri(self, p0, p1, p2, mat, flags=0, tint=(128, 128, 128)):
        n = _norm(_cross(_sub(p1, p0), _sub(p2, p0)))
        col = self._shade(n, tint)
        self.tris.append(Tri((p0, p1, p2), tuple(self._uv(q, n, mat) for q in (p0, p1, p2)), (col,) * 3, mat, flags,
                             self.materials[mat].terrain))

    def box(self, lo, hi, mat, top=None, tint=(128, 128, 128), bottom=False, flags=0):
        """Axis-aligned box; top: material for the top face (default mat)."""
        (x0, y0, z0), (x1, y1, z1) = lo, hi
        self.quad((x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0), top or mat, tint=tint)  # top (+y)
        if bottom:
            self.quad((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1), mat, tint=tint)
        self.quad((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1), mat, flags, tint)  # +z
        self.quad((x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0), mat, flags, tint)  # -z
        self.quad((x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1), mat, flags, tint)  # +x
        self.quad((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0), mat, flags, tint)  # -x

    def ground(self, x0, z0, x1, z1, y, mat, tint=(128, 128, 128)):
        self.quad((x0, y, z0), (x0, y, z1), (x1, y, z1), (x1, y, z0), mat, tint=tint)

    def wall(self, a, b, y0, y1, mat, tint=(128, 128, 128), flags=0):
        """Vertical wall from a to b (x, z), facing left of the direction a->b."""
        self.quad((a[0], y0, a[1]), (b[0], y0, b[1]), (b[0], y1, b[1]), (a[0], y1, a[1]), mat, flags, tint)

    def quarter_pipe(self, a, b, y, radius, height, deck, mat, coping=True, steps=8, deck_mat=None):
        """Quarter pipe whose lip runs from a to b (x, z); the ramp faces left of a->b and the deck (depth deck)
        extends right. Curved transition of the given radius, vertical extension up to height."""
        dx, dz = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dz)
        tx, tz = dx / L, dz / L
        nx, nz = -tz, tx  # the ramp faces this way
        prof = [(radius - radius * math.sin(math.pi / 2 * i / steps), radius - radius * math.cos(math.pi / 2 * i / steps))
                for i in range(steps + 1)]  # (distance in front of the lip, height) from the floor up
        if height > radius:
            prof.append((0.0, height))
        top = prof[-1][1]
        P = lambda s, o, h: (s[0] + nx * o, y + h, s[1] + nz * o)
        for (o0, h0), (o1, h1) in zip(prof, prof[1:]):  # transition faces (vert flag)
            mid = ((o0 + o1) / 2, (h0 + h1) / 2)
            ang = math.atan2(radius - mid[1], radius - mid[0]) if mid[1] < radius else 0.0
            facing = (nx * math.cos(ang), math.sin(ang), nz * math.cos(ang))
            self.quad(P(a, o0, h0), P(b, o0, h0), P(b, o1, h1), P(a, o1, h1), mat, flags=0x8, face=facing)
        back = (-nx, 0, -nz)
        self.quad(P(a, 0, top), P(b, 0, top), P(b, -deck, top), P(a, -deck, top), deck_mat or mat, face=(0, 1, 0))
        self.quad(P(a, -deck, 0), P(b, -deck, 0), P(b, -deck, top), P(a, -deck, top), deck_mat or mat, face=back)
        for s, f in ((a, (-tx, 0, -tz)), (b, (tx, 0, tz))):  # sides: vertical slices under the profile + deck
            for (o0, h0), (o1, h1) in zip(prof, prof[1:]):
                self.quad(P(s, o0, 0), P(s, o1, 0), P(s, o1, h1), P(s, o0, h0), mat, face=f)
            self.quad(P(s, 0, 0), P(s, -deck, 0), P(s, -deck, top), P(s, 0, top), mat, face=f)
        if coping:
            self.rails.append(Rail([P(a, 0, top), P(b, 0, top)], "TERRAIN_GRINDMETAL"))

    def ramp(self, a, b, y, length, height, mat):
        """Kicker / bank: low edge a->b at y, rising away to the left of a->b over length to height."""
        dx, dz = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dz)
        nx, nz = -dz / L, dx / L
        hi = lambda s: (s[0] + nx * length, y + height, s[1] + nz * length)
        fl = lambda s: (s[0] + nx * length, y, s[1] + nz * length)
        lo = lambda s: (s[0], y, s[1])
        self.quad(lo(a), lo(b), hi(b), hi(a), mat, face=(-nx, 1, -nz))
        self.quad(fl(a), fl(b), hi(b), hi(a), mat, face=(nx, 0, nz))
        for s, f in ((a, (-dx, 0, -dz)), (b, (dx, 0, dz))):
            p0, p1, p2 = lo(s), fl(s), hi(s)
            n = _cross(_sub(p1, p0), _sub(p2, p0))
            if sum(x * y_ for x, y_ in zip(n, f)) < 0:
                p1, p2 = p2, p1
            self.tri(p0, p1, p2, mat)

    def rail(self, a, b, height, mat, size=4.0, posts=True):
        """Free-standing handrail from a to b (x, y, z of the ground under each end)."""
        top_a, top_b = (a[0], a[1] + height, a[2]), (b[0], b[1] + height, b[2])
        dx, dz = b[0] - a[0], b[2] - a[2]
        L = math.hypot(dx, dz) or 1.0
        nx, nz = -dz / L * size, dx / L * size
        up = (0, size, 0)
        A, B = top_a, top_b
        self.quad((A[0] - nx, A[1] + size, A[2] - nz), (A[0] + nx, A[1] + size, A[2] + nz),
                  (B[0] + nx, B[1] + size, B[2] + nz), (B[0] - nx, B[1] + size, B[2] - nz), mat, collide=False)
        self.quad((A[0] + nx, A[1] - size, A[2] + nz), (B[0] + nx, B[1] - size, B[2] + nz),
                  (B[0] + nx, B[1] + size, B[2] + nz), (A[0] + nx, A[1] + size, A[2] + nz), mat, collide=False)
        self.quad((B[0] - nx, B[1] - size, B[2] - nz), (A[0] - nx, A[1] - size, A[2] - nz),
                  (A[0] - nx, A[1] + size, A[2] - nz), (B[0] - nx, B[1] + size, B[2] - nz), mat, collide=False)
        if posts:
            for p in (a, b):
                self.box((p[0] - size, p[1], p[2] - size), (p[0] + size, p[1] + height, p[2] + size), mat)
        self.rails.append(Rail([top_a, top_b], "TERRAIN_GRINDMETAL"))
        del up

    def ledge(self, lo, hi, mat, top=None, edges=("x0", "x1", "z0", "z1")):
        """Box with grindable top edges (rails along the chosen edges)."""
        self.box(lo, hi, mat, top=top)
        (x0, _, z0), (x1, y1, z1) = lo, hi
        e = {"z0": [(x0, y1, z0), (x1, y1, z0)], "z1": [(x0, y1, z1), (x1, y1, z1)],
             "x0": [(x0, y1, z0), (x0, y1, z1)], "x1": [(x1, y1, z0), (x1, y1, z1)]}
        for k in edges:
            self.rails.append(Rail(e[k], "TERRAIN_GRINDCONC"))

    def start(self, pos, heading=0.0):
        self.starts.append((pos, heading))

    # ---------------------------------------------------------------- output helpers
    def render_items(self):
        """[(material, verts)] strips: verts = [(pos, uv, col)] in strip order."""
        out = []
        for q in self.quads:
            if q.render:  # strip p0, p3, p1, p2: even triangle (p0, p3, p1) has the winding THAW draws
                out.append((q.material, [(q.p[i], q.uv[i], q.col[i]) for i in (0, 3, 1, 2)]))
        for t in self.tris:
            if t.render:
                out.append((t.material, [(t.p[i], t.uv[i], t.col[i]) for i in (0, 2, 1)]))
        return out

    def collision_tris(self):
        out = []
        for q in self.quads:
            if q.collide:
                out += q.tris()
        out += [t for t in self.tris if t.collide]
        return out

    def bounds(self):
        ps = [p for q in self.quads for p in q.p] + [p for t in self.tris for p in t.p]
        return tuple(min(p[i] for p in ps) for i in range(3)), tuple(max(p[i] for p in ps) for i in range(3))
