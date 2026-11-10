"""THPS4 (PS2) collision (.col version 8) -> THUG2 layout (version 10), which col.thug2_to_thaw then takes to THAW.

THPS4 v8 (layout from io_thps_scene's import_thps4, checked against School: parses to the face section end):
  header 8 x u32 {8, objects, verts, large faces, small faces, large verts, small verts, 0}; 64-byte object
  records (same fields as v10, but the first vert offset counts vertices); align 16; vertices 16 B each
  (3 f32 + 4 intensity bytes); faces: large 12 B (flags, terrain, 3 x u16, pad), small 8 B (3 x u8, pad).
  Camera-collide face flag 0x80 has the opposite meaning to later games.
The BSP is rebuilt in THUG2's form (io_thps_scene's exporter rules): nodes of 8 bytes, split word
(axis | int(point * 16) << 2) + byte offset of the left child (right child follows it); leaves axis 3,
u16 face count, u32 index into the u16 face index list. Faces go left / right if any vertex is below /
at or above the split point.
"""
import struct

CAMERA = 0x80
LEAF_FACES = 50


def parse_v8(b):
    ver, no, nv, nlf, nsf, nlv, nsv, _ = struct.unpack_from("<8I", b, 0)
    assert ver == 8, ver
    vbase = (32 + 64 * no + 15) & ~15
    fbase = vbase + (nv * 16 if nlv == 0 and nsv == 0 else nlv * 16 + nsv * 6)
    objs = []
    for i in range(no):
        r = struct.unpack_from("<IHHH??I8fIIII", b, 32 + 64 * i)
        crc, flags, nverts, nfaces, small, fixed, foff = r[:7]
        bbox, voff = r[7:15], r[15]
        assert not fixed, "fixed-point THPS4 collision vertices are not handled"
        verts, inten = [], []
        for j in range(nverts):
            x, y, z = struct.unpack_from("<3f", b, vbase + (voff + j) * 16)
            verts.append((x, y, z))
            inten.append(b[vbase + (voff + j) * 16 + 12])
        faces = []
        for j in range(nfaces):
            if small:
                fl, tt, a, bb, c = struct.unpack_from("<HH3B", b, fbase + foff + 8 * j)
            else:
                fl, tt, a, bb, c = struct.unpack_from("<HH3H", b, fbase + foff + 12 * j)
            faces.append((fl ^ CAMERA, tt, (a, bb, c)))
        objs.append(dict(crc=crc, flags=flags, bbox=bbox, verts=verts, intensity=inten, faces=faces))
    return objs


def _bsp(verts, faces):
    """-> list of nodes in breadth-first order: ('leaf', [face idx]) or ('node', axis, point, left index)."""
    def build(fs, cant=frozenset()):
        if len(fs) <= LEAF_FACES:
            return ("leaf", fs)
        best = None
        for axis in range(3):
            if axis in cant:
                continue
            vals = sorted(verts[v][axis] for f in fs for v in faces[f][2])
            point = int(vals[len(vals) // 2] * 16.0) * 0.0625
            left = [f for f in fs if any(verts[v][axis] < point for v in faces[f][2])]
            right = [f for f in fs if any(verts[v][axis] >= point for v in faces[f][2])]
            d = len(left) + len(right) - len(fs)
            if best is None or d < best[0]:
                best = (d, axis, point, left, right)
        if best is None or best[0] >= len(fs) // 2:
            return ("leaf", fs)
        d, axis, point, left, right = best
        return ("node", axis, point,
                build(left, cant | {axis} if len(left) == len(fs) else cant),
                build(right, cant | {axis} if len(right) == len(fs) else cant))
    root = build(list(range(len(faces))))
    out, queue = [], [root]
    while queue:  # breadth first: a node's two children are consecutive
        t = queue.pop(0)
        out.append(t)
        if t[0] == "node":
            queue += [t[3], t[4]]
    # child index of each inner node: children are appended in order, so count
    idx, nxt = {}, 1
    for i, t in enumerate(out):
        if t[0] == "node":
            idx[i] = nxt
            nxt += 2
    return out, idx


def to_v10(b):
    objs = parse_v8(b)
    nv = sum(len(o["verts"]) for o in objs)
    nf = sum(len(o["faces"]) for o in objs)
    recs, verts, inten, faces, nodes, findex = bytearray(), bytearray(), bytearray(), bytearray(), bytearray(), []
    for o in objs:
        tree, child = _bsp(o["verts"], o["faces"])
        node_base = len(nodes)
        recs += struct.pack("<IHHH??I8fIIII", o["crc"], o["flags"], len(o["verts"]), len(o["faces"]), False, False,
                            len(faces), *o["bbox"], len(verts), node_base, len(inten), 0)
        for v in o["verts"]:
            verts += struct.pack("<3f", *v)
        inten += bytes(o["intensity"])
        for fl, tt, (a, bb, c) in o["faces"]:
            faces += struct.pack("<HH3H", fl, tt, a, bb, c)
        for i, t in enumerate(tree):
            if t[0] == "leaf":
                nodes += struct.pack("<BBHI", 3, 0, len(t[1]), len(findex))
                findex += t[1]
            else:
                nodes += struct.pack("<iI", (t[1] & 3) | (int(t[2] * 16.0) << 2), node_base + child[i] * 8)
    out = bytearray(struct.pack("<8I", 10, len(objs), nv, nf, 0, nv, 0, 0)) + recs
    out += bytes(-len(out) % 16) + verts + inten
    out += bytes(-len(out) % 4) + faces
    out += bytes(-len(out) % 2) + bytes(nf)  # one byte per large face
    out += bytes(-len(out) % 4) + struct.pack("<I", len(nodes)) + nodes
    out += struct.pack(f"<{len(findex)}H", *findex)
    return bytes(out)
