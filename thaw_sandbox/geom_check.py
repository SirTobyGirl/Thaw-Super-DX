"""Check converted geometry against the rules THAW's renderer depends on (all learned from THAW's own data/code):
  layout   every batch's VIF unpack sequence is one THAW uses (shapes collected from all THAW zones)
  field    leaf size field == sum over batches of 3*verts + 2 + GS registers (mod 1024)
  addrs    unpack addresses are contiguous per THAW's layout (last written slot + 1 == field, single batch)
  selector vertex GIFtag microcode selector is one THAW's VU1 branch table has
  eop      every vertex GIFtag has EOP set
  tex0     the leaf has a TEX0 register (untextured leaves are a THUG2-only type)
"""
import collections
import glob
import os
import pickle
import struct

from thaw_sandbox import geom as GM, pak, zone

THAW_SELECTORS = {0x3C, 0x3E, 0x40, 0x44, 0x46, 0x48, 0x4A, 0x4E, 0x50, 0x52, 0x54}
SHAPES = "_workspace/thaw_batch_shapes.pkl"


def batch_shapes(b, o):
    s = []
    for _, w in GM.vif_codes(b, o):
        cmd = (w >> 24) & 0x7F
        if cmd >= 0x60:
            s.append(f"U{cmd & 0xF:x}" + ("1" if ((w >> 16) & 0xFF) == 1 else ""))
        elif cmd in (1, 2, 5, 0x14, 0x20):
            s.append({1: "CY", 2: "OF", 5: "MD", 0x14: "MS", 0x20: "SM"}[cmd])
        elif cmd:
            s.append(f"?{cmd:x}")
    return [x.strip() for x in " ".join(s).split("MS") if x.strip()]


def thaw_shapes():
    if os.path.exists(SHAPES):
        return pickle.load(open(SHAPES, "rb"))
    known = set()
    for zp in glob.glob("_workspace/datap/worlds/worldzones/z_*/z_*.pak.ps2"):
        zb = open(zp, "rb").read()
        for e in zone.entries(zb):
            if struct.unpack_from("<I", zb, e.pos)[0] != 0x7EA7357B or e.size >= 0x40000000 or e.size < 5000:
                continue
            p = pak.data_pos(e, 0)
            b = zb[p:p + e.size]
            try:
                for _, n in GM.walk(b):
                    if n[7] & 2:
                        known.update(batch_shapes(b, 0x10 + n[8]))
            except Exception:
                pass
    pickle.dump(known, open(SHAPES, "wb"))
    return known


def check(b: bytes) -> collections.Counter:
    known = thaw_shapes()
    bad = collections.Counter()
    for _, n in GM.walk(b):
        if not n[7] & 2:
            continue
        o = 0x10 + n[8]
        bad["leaves"] += 0
        if any(s not in known for s in batch_shapes(b, o)):
            bad["layout"] += 1
        f = GM.thaw_field(b, o)
        if f is not None and f != (n[9] >> 16) & 0x3FF:
            bad["field"] += 1
        codes = list(GM.vif_codes(b, o))
        if sum(1 for _, w in codes if (w >> 24) & 0x7F == 0x14) == 1:
            # each unpack advances by the STCYCL cycle length in force (1 for tags/registers, the number of
            # per-vertex streams - usually 3, 2 without UVs - for vertex data)
            mx, cl = 0, 1
            for _, w in codes:
                if (w >> 24) & 0x7F == 0x01:
                    cl = w & 0xFF
                elif (w >> 24) & 0x7F >= 0x60:
                    mx = max(mx, (w & 0x3FF) + ((((w >> 16) & 0xFF) or 256) - 1) * cl)
            if mx + 1 != (n[9] >> 16) & 0x3FF:
                bad["addrs"] += 1
        for j, (p, w) in enumerate(codes):
            if (w >> 24) & 0x6F == 0x6C and ((w >> 16) & 0xFF) == 1 and j and codes[j - 1][1] == 0x01000103:
                w0, w1 = struct.unpack_from("<2I", b, p + 4)
                if (w1 & 0xFF) not in THAW_SELECTORS:
                    bad["selector"] += 1
                if not w0 & 0x8000:
                    bad["eop"] += 1
        if 0x06 not in GM.leaf_regs(b, o):
            bad["tex0"] += 1
    return bad
