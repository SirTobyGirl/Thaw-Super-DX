"""Experiment: put a converted THUG2 level into an existing THAW zone's slot (no WAD/ISO growth).

usage: build_level_test.py BASE.iso OUT.iso THUG2_LEVEL_DIR THUG2_CODE THAW_ZONE [--tex convert|empty|thug2|file:PATH]
       [--parts tex,geom,col,nqb] [--nqb PREBUILT_THAW.qb]
e.g.   build_level_test.py _workspace/build/sandbox.iso _workspace/build/berlin_in_kyoto.iso \
           _workspace/thug2/be be z_ja
The THAW zone keeps its table; its main .tex/.geom/.col/.nqb entries get the THUG2 level's data.
The node array is renamed <ZONE>_NodeArray and records get the zone file's hash. BASE.iso is copied.
"""
import struct
import sys

from thaw_sandbox import convert_thug2 as C, iso_manager as I, qb_data as QD, qb_file as F, qb_parser as Q, wad, zone, pak
from thaw_sandbox import thaw_tex as TT, thug2_tex as T2

HED = "_workspace/stage/DATAP.HED"
D = "_workspace/datap/"


def main(base, out, src_dir, code, z, tex_mode="thug2", parts=("tex", "geom", "col", "nqb"), nqb_file=None):
    zpath = f"{D}worlds/worldzones/{z}/{z}.pak.ps2"
    zb = open(zpath, "rb").read()
    tab = zone.entries(zb)
    T = {Q.qbcrc(x): x for x in (".tex", ".geom", ".col", ".nqb")}
    biggest = {}
    for e in tab:
        t = T.get(struct.unpack_from("<I", zb, e.pos)[0])
        if t and e.size < 0x40000000 and e.size > biggest.get(t, (None, -1))[1]:
            biggest[t] = (e, e.size)
    # node array: convert, rename, take the original zone qb's file hash
    orig_nqb = biggest[".nqb"][0]
    p0 = pak.data_pos(orig_nqb, 0)
    orig_crc, _ = F.read(zb[p0:p0 + orig_nqb.size])
    if nqb_file:  # use a prebuilt THAW qb (experiments)
        fcrc, items = F.read(open(nqb_file, "rb").read())
    else:
        qb, src = C.convert(open(f"{src_dir}/{code}.qb", "rb").read(), "x")
        fcrc, items = F.read(qb)
    old_na, new_na = Q.qbcrc(f"{code}_NodeArray"), Q.qbcrc(f"{z}_NodeArray")
    for it in items:
        if it.name == old_na:
            it.name = new_na
    assert any(it.name == new_na for it in items), "node array not found"
    if not nqb_file:  # THAW node files carry a sorted name index; THUG2 ones do not
        na = next(it for it in items if it.name == new_na).value
        NAME = Q.qbcrc("name")
        pairs = sorted((v.crc, i) for i, s_ in enumerate(na.items) for n, v in s_.items if n == NAME)
        items += [F.Item(12, Q.qbcrc(f"{z}_NodeArray_SortedNames"), QD.Array(13, [QD.Name(c) for c, _ in pairs])),
                        F.Item(12, Q.qbcrc(f"{z}_NodeArray_SortedIndices"), QD.Array(1, [i for _, i in pairs]))]  # at the end, like THAW
        print(f"sorted node index: {len(pairs)} named nodes")
    nqb = F.write(orig_crc, items)
    if tex_mode.startswith("file:"):
        tex = open(tex_mode[5:], "rb").read()
    elif tex_mode == "convert":
        _, t2 = T2.parse(open(f"{src_dir}/{code}.tex.ps2", "rb").read())
        grey = struct.pack("<16I", *([0x80606060] * 16))  # placeholder palette, CT32, opaque grey
        new = []
        for x in t2:
            if x.mips:
                new.append(TT.NewTexture(x.crc, x.width, x.height, x.psm, x.cpsm, x.clut, x.mips, group=x.group))
            else:  # header-only entry: stand-in 8x8 grey so references resolve
                new.append(TT.NewTexture(x.crc, 8, 8, 0x14, 0, grey, [bytes(32)], group=x.group))
        tex = TT.write(new)
        print(f"textures: {len(new)} ({sum(1 for x in t2 if not x.mips)} placeholders), {len(tex)} bytes")
    elif tex_mode == "empty":
        tex = struct.pack("<HH4I", 6, 0x14, 0, 0, 0, 0)  # version 6 header with zero textures (experiment)
    else:
        tex = open(f"{src_dir}/{code}.tex.ps2", "rb").read()
    rep = {
        biggest[".tex"][0].pos: tex,
        biggest[".geom"][0].pos: open(f"{src_dir}/{code}.geom.ps2", "rb").read(),
        biggest[".col"][0].pos: open(f"{src_dir}/{code}.col.ps2", "rb").read(),
        orig_nqb.pos: nqb,
    }
    keep = {"tex": biggest[".tex"][0].pos, "geom": biggest[".geom"][0].pos, "col": biggest[".col"][0].pos,
            "nqb": orig_nqb.pos}
    rep = {k: v for k, v in rep.items() if k in {keep[p] for p in parts}}
    print("replacing:", ", ".join(parts), "| tex:", tex_mode)
    new_zone = zone.rebuild(zb, rep)
    # WAD slot check
    hed_b = bytearray(open(HED, "rb").read())
    ents, _ = wad.parse_hed(bytes(hed_b))
    e = next(x for x in ents if x.name.lower().endswith(f"\\{z}\\{z}.pak.ps2"))
    nxt = min(x.offset for x in ents if x.offset > e.offset)
    slot = (nxt - e.offset) * 2048
    print(f"{z}: new zone {len(new_zone)} bytes, slot {slot} bytes, nodes renamed to {z}_NodeArray")
    assert len(new_zone) <= slot, "does not fit the slot"
    # HED: patch this entry's size field in place
    p = 0
    while True:
        off, size = struct.unpack_from("<iI", hed_b, p)
        nend = hed_b.index(b"\0", p + 8)
        if hed_b[p + 8:nend].decode("latin1") == e.name:
            struct.pack_into("<I", hed_b, p + 4, len(new_zone))
            break
        p = nend + 1
        p += -p % 4
    I.stage_copy(base, out)
    wad_off, _ = I.file_extent(out, "/DATAP.WAD;1")
    hed_off, hed_len = I.file_extent(out, "/DATAP.HED;1")
    assert hed_len == len(hed_b)
    I.patch_in_place(out, wad_off + e.offset * 2048, new_zone + b"\0" * (slot - len(new_zone)))
    I.patch_in_place(out, hed_off, bytes(hed_b))
    print("built", out)


if __name__ == "__main__":
    a = sys.argv[1:]
    mode = a[a.index("--tex") + 1] if "--tex" in a else "thug2"
    parts = a[a.index("--parts") + 1].split(",") if "--parts" in a else ("tex", "geom", "col", "nqb")
    nqbf = a[a.index("--nqb") + 1] if "--nqb" in a else None
    main(*a[:5], tex_mode=mode, parts=parts, nqb_file=nqbf)
