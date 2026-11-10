"""THAW rail table (.rnb, zone PAK entry type 0x91e1028d) built from a level's node array.

THAW does not create rails from RailNode/ClimbingNode entries in the node array; it loads them from this table
(FUN_0025a818 when RAILNODE_ASSETS_ENABLED; the node pass only switches rails on by name, FUN_00356cc8). The
template's table would give a converted level Kyoto's rails, so each level gets its own.

file    = u32 count | u32 1 (0: the table is not handed to the rail manager) | count records | zero padding to
          8 + count * 0x60 (the records are unpacked in place to 0x60 bytes each)
record  = 22 words: v0, v1 (bounding box min / max of the node and its linked node), v2 (node position), v3 (0)
          as x, y, z, 1.0 (v3: 0, 0, 0, 0) | flags | name crc | terrain crc | cluster crc | next index | prev index
          records sorted by name crc (binary search); next / prev are record indices (0 when absent)
flags   = 0x1 LipOverride, 0x2 DefaultLine, 0x4 CreatedAtStart, 0x8 NoClimbing, 0x10 ClimbingNode (no terrain),
          0x20 Type Ladder, 0x80 HangRight, 0x100 TrickObject (has Cluster), 0x200 has next, 0x400 has prev
Checked: rebuilding every THAW zone's own table (header 1) from its node array reproduces it byte for byte.
"""
import struct

from thaw_sandbox import qb_data as QD
from thaw_sandbox.qb_parser import qbcrc as H

RNB_TYPE = 0x91E1028D
CLASSES = {H("RailNode"): 0, H("ClimbingNode"): 0x10}
FLAGS = {H("LipOverride"): 0x1, H("DefaultLine"): 0x2, H("CreatedAtStart"): 0x4, H("NoClimbing"): 0x8,
         H("HangRight"): 0x80, H("TrickObject"): 0x100}
K_CLASS, K_NAME, K_POS, K_LINKS, K_TERRAIN, K_CLUSTER, K_TYPE = (
    H("Class"), H("name"), H("pos"), H("links"), H("TerrainType"), H("Cluster"), H("Type"))
LADDER = H("Ladder")


def _flat(s, structs, depth=0):
    out = []
    for k, v in s.items:
        if k == 0 and isinstance(v, QD.Name) and v.crc in structs and depth < 4:
            out += _flat(structs[v.crc], structs, depth + 1)
        else:
            out.append((k, v))
    return out


def build(nodes, structs=None) -> bytes:
    """nodes: the node array's structs (QD.Struct list); structs: {name crc: QD.Struct} for included field sets."""
    structs = structs or {}
    flat = [_flat(s, structs) for s in nodes]
    info = {}
    for i, f in enumerate(flat):
        d = {}
        for k, v in f:
            d.setdefault(k, v)
        c = getattr(d.get(K_CLASS), "crc", None)
        if c in CLASSES and K_NAME in d:
            info[i] = (d, f)
    order = sorted(info, key=lambda i: info[i][0][K_NAME].crc)
    rec_of = {i: r for r, i in enumerate(order)}

    def link(i):
        ls = info[i][0].get(K_LINKS)
        for x in (ls.items if ls is not None else []):
            if x in info:
                return x
        return None
    prev = {}
    for i in order:
        j = link(i)
        if j is not None:
            prev.setdefault(j, i)
    out = bytearray(struct.pack("<2I", len(order), 1))
    for i in order:
        d, f = info[i]
        p = tuple(d.get(K_POS, (0.0, 0.0, 0.0)))
        j = link(i)
        q = tuple(info[j][0].get(K_POS, (0.0, 0.0, 0.0))) if j is not None else p
        lo = tuple(min(a, b) for a, b in zip(p, q))
        hi = tuple(max(a, b) for a, b in zip(p, q))
        flags = CLASSES[d[K_CLASS].crc]
        for k, v in f:
            if k == 0 and isinstance(v, QD.Name):
                flags |= FLAGS.get(v.crc, 0)
        if getattr(d.get(K_TYPE), "crc", None) == LADDER:
            flags |= 0x20
        if K_CLUSTER in d:
            flags |= 0x100
        nxt = rec_of[j] if j is not None else 0
        prv = rec_of[prev[i]] if i in prev else 0
        flags |= (0x200 if j is not None else 0) | (0x400 if i in prev else 0)
        terrain = getattr(d.get(K_TERRAIN), "crc", 0) if not flags & 0x10 else 0
        cluster = getattr(d.get(K_CLUSTER), "crc", 0)
        out += struct.pack("<16f6I", *lo, 1.0, *hi, 1.0, *p, 1.0, 0.0, 0.0, 0.0, 0.0,
                           flags, d[K_NAME].crc, terrain, cluster, nxt, prv)
    out += bytes(8 + 0x60 * len(order) - len(out))
    return bytes(out)
