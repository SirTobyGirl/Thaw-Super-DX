"""Write THAW PS2 collision (.col version 10 with THAW's supersector block) from triangles.

Layout (see thaw_sandbox/col.py; offsets checked on Kyoto):
  header   8 x u32: 10, objects, verts, large faces, small faces, float verts, fixed verts, 0
  super    u32 0, 0, grid columns, grid rows, f32 bbox min x,y,z,1, max x,y,z,1
  objects  64 bytes: u32 checksum, u16 flags, u16 verts, u16 faces, u8 small faces, u8 fixed verts,
           u32 face offset (from the face region), f32 bbox min x,y,z,1 max x,y,z,1, u32 vert offset (from the
           vertex region), u32 BSP offset (from the node region), u32 intensity offset, u32 0
  align 16; float verts (none here); fixed verts: u16 x,y,z = (p - object bbox min) * 16
  intensities (1 byte per vert); align 4; faces in object order: small = u16 flags, u16 terrain, u8 a,b,c, u8 0
  align 2; one byte per large face (none); align 4; u32 node bytes; nodes; u16 face indices
  BSP leaf node: u8 3, u8 0, u16 face count, u32 first index in the face index list
Front faces: (b - a) x (c - a) points out (floors: up). Objects are kept to one spatial cell and <= 255 verts.
"""
import collections
import math
import struct

from thaw_sandbox.qb_parser import qbcrc as H

CELL = 1500.0
MAX_VERTS = 240
MAX_FACES = 200


def _objects(tris):
    by = collections.defaultdict(list)
    for t in tris:
        c = [sum(p[i] for p in t.p) / 3 for i in range(3)]
        # height too: fixed verts are u16 / 16 from the object's bbox min (tall levels)
        by[(math.floor(c[0] / CELL), math.floor(c[2] / CELL), math.floor(c[1] / CELL))].append(t)
    objs = []
    for key in sorted(by):
        cur, idx, verts = [], {}, []
        for t in by[key]:
            new = [p for p in t.p if p not in idx]
            if cur and (len(verts) + len(new) > MAX_VERTS or len(cur) >= MAX_FACES):
                objs.append((verts, cur))
                cur, idx, verts = [], {}, []
            ids = []
            for p in t.p:
                if p not in idx:
                    idx[p] = len(verts)
                    verts.append(p)
                ids.append(idx[p])
            cur.append((ids, t.flags, t.terrain))
        if cur:
            objs.append((verts, cur))
    return objs


def write(tris, name_prefix="gen") -> bytes:
    objs = _objects(tris)
    recs, fixed, inten, faces, nodes, findex = bytearray(), bytearray(), bytearray(), bytearray(), bytearray(), []
    gmin, gmax = [math.inf] * 3, [-math.inf] * 3
    for i, (verts, fs) in enumerate(objs):
        lo = [min(p[j] for p in verts) for j in range(3)]
        hi = [max(p[j] for p in verts) for j in range(3)]
        assert max(h - l for l, h in zip(lo, hi)) * 16 < 65535, "collision object too large for fixed verts"
        for j in range(3):
            gmin[j], gmax[j] = min(gmin[j], lo[j]), max(gmax[j], hi[j])
        recs += struct.pack("<IHHHBBI8fIIII", H(f"{name_prefix}_col{i}"), 0, len(verts), len(fs), 1, 1, len(faces),
                            *lo, 1.0, *hi, 1.0, len(fixed), len(nodes), len(inten), 0)
        for p in verts:
            fixed += struct.pack("<3H", *(int(round((p[j] - lo[j]) * 16)) for j in range(3)))
        inten += bytes([0x80]) * len(verts)
        nodes += struct.pack("<BBHI", 3, 0, len(fs), len(findex))
        for f, (ids, flags, terr) in enumerate(fs):
            faces += struct.pack("<HH3BB", flags, terr, *ids, 0)
            findex.append(f)
    n_obj, n_verts, n_faces = len(objs), sum(len(v) for v, _ in objs), sum(len(f) for _, f in objs)
    cols = max(1, min(64, math.ceil((gmax[0] - gmin[0]) / CELL)))
    rows = max(1, min(64, math.ceil((gmax[2] - gmin[2]) / CELL)))
    out = bytearray(struct.pack("<8I", 10, n_obj, n_verts, 0, n_faces, 0, n_verts, 0))
    out += struct.pack("<4I8f", 0, 0, cols, rows, *gmin, 1.0, *gmax, 1.0)
    out += recs
    out += bytes(-len(out) % 16)
    vert_region = len(out)
    out += fixed
    out += inten
    out += bytes(-len(out) % 4)
    out += faces
    out += bytes(-len(out) % 2)
    out += bytes(-len(out) % 4)
    out += struct.pack("<I", len(nodes))
    out += nodes
    out += struct.pack(f"<{len(findex)}H", *findex)
    del vert_region
    return bytes(out)
