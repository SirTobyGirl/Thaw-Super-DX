"""Set a zone's recorded size in zone_sizes_ps2 (pak/qb.pab inside DATAP.WAD of an ISO) to its current
PAK size. usage: bump_zone_size.py ISO ZONE   (same-size int edit in place)"""
import struct
import sys

from thaw_sandbox import iso_manager as I, pak, qb_parser as Q, wad


def main(iso, z):
    ents, _ = wad.parse_hed(I.read_file(iso, "/DATAP.HED;1"))
    zc = next(x for x in ents if x.name.lower().endswith(f"\\{z}\\{z}.pak.ps2"))
    pabe = next(x for x in ents if x.name.endswith("\\pak\\qb.pab.ps2"))
    idx = open("_workspace/datap/pak/qb.pak.ps2", "rb").read()
    fe = next(x for x in pak.parse_pak(idx) if x.name.endswith("zone_sizes_ps2.qb.ps2"))
    fpos = pak.data_pos(fe, len(idx))
    qb = open("_workspace/datap/pak/qb.pab.ps2", "rb").read()[fpos:fpos + fe.size]
    r = Q.parse(qb).records[0]
    p = struct.unpack_from("<I", qb, r.value + 4)[0]
    while p:
        _, name, val, nxt = struct.unpack_from("<4I", qb, p)
        if name == Q.qbcrc(z):
            break
        p = nxt
    c = struct.unpack_from("<I", qb, val + 4)[0]
    _, name, old, _ = struct.unpack_from("<4I", qb, c)
    assert name == Q.qbcrc("size")
    wo, _ = I.file_extent(iso, "/DATAP.WAD;1")
    I.patch_in_place(iso, wo + pabe.offset * 2048 + fpos + c + 8, struct.pack("<I", zc.size))
    print(f"{z}: recorded size {old} -> {zc.size}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
