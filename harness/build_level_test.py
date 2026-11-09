"""Experiment: put a converted THUG2 level into an existing THAW zone's slot (no WAD/ISO growth).

usage: build_level_test.py BASE.iso OUT.iso THUG2_LEVEL_DIR THUG2_CODE THAW_ZONE [--tex convert|empty|thug2|file:PATH]
       [--parts tex,geom,col,nqb] [--nqb PREBUILT_THAW.qb]
e.g.   build_level_test.py _workspace/build/sandbox.iso _workspace/build/berlin_in_kyoto.iso \
           _workspace/thug2/be be z_ja
The THAW zone keeps its table; its main .tex/.geom/.col/.nqb entries get the THUG2 level's data.
The node array is renamed <ZONE>_NodeArray and records get the zone file's hash. BASE.iso is copied.
"""
import os
import struct
import sys

from thaw_sandbox import convert_thug2 as C, iso_manager as I, qb_data as QD, qb_file as F, qb_parser as Q, wad, zone, pak
from thaw_sandbox import col as CL, geom as GM, thaw_tex as TT, thug2_tex as T2

HED = "_workspace/stage/DATAP.HED"
D = "_workspace/datap/"


def build_zone(src_dir, code, z, tex_mode="thug2", parts=("tex", "geom", "col", "nqb"), nqb_file=None, no_create=(),
               na_zone=None):
    """Convert THUG2 level CODE into a copy of THAW zone z's PAK; returns the new zone bytes.
    The node array (and its sorted index) is named after na_zone (default z) - the engine looks it up by the
    level's zone name."""
    na_zone = na_zone or z
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
    old_na, new_na = Q.qbcrc(f"{code}_NodeArray"), Q.qbcrc(f"{na_zone}_NodeArray")
    for it in items:
        if it.name == old_na:
            it.name = new_na
    assert any(it.name == new_na for it in items), "node array not found"
    if no_create:  # experiment: neutralise THUG2-only node classes (indices kept so links still resolve)
        na = next(it for it in items if it.name == new_na).value
        CLS, CAS, MODEL, WP = Q.qbcrc("Class"), Q.qbcrc("CreatedAtStart"), Q.qbcrc("model"), Q.qbcrc("Waypoint")
        drop = {Q.qbcrc(c) for c in no_create}
        keep_class = {Q.qbcrc("GameObject")}
        n_off = 0
        structs = list(na.items) + [it.value for it in items if isinstance(it.value, QD.Struct)]  # + included structs
        for s_ in structs:
            c = next((getattr(v, "crc", None) for k, v in s_.items if k == CLS), None)
            if c not in drop:
                continue
            n_off += 1
            s_.items = [(k, v) for k, v in s_.items
                        if k != MODEL and not (k == 0 and getattr(v, "crc", None) == CAS)]
            if c not in keep_class:
                s_.items = [(k, QD.Name(WP) if k == CLS else v) for k, v in s_.items]
        print(f"neutralised {n_off} nodes of {sorted(no_create)} (model + CreatedAtStart removed)")
    if os.environ.get("NODE_KEEP"):  # experiment: keep only these node classes, drop all links
        keep_cls = {Q.qbcrc(c) for c in os.environ["NODE_KEEP"].split(",")}
        na = next(it for it in items if it.name == new_na).value
        CLS, LINKS = Q.qbcrc("Class"), Q.qbcrc("links")
        na.items = [s_ for s_ in na.items if any(k == CLS and getattr(v, "crc", None) in keep_cls for k, v in s_.items)]
        for s_ in na.items:
            s_.items = [(k, v) for k, v in s_.items if k != LINKS]
        print(f"node array cut to {len(na.items)} nodes of {os.environ['NODE_KEEP']}")
    if not nqb_file:  # THAW node files carry a sorted name index; THUG2 ones do not
        na = next(it for it in items if it.name == new_na).value
        NAME = Q.qbcrc("name")
        pairs = sorted((v.crc, i) for i, s_ in enumerate(na.items) for n, v in s_.items if n == NAME)
        items += [F.Item(12, Q.qbcrc(f"{na_zone}_NodeArray_SortedNames"), QD.Array(13, [QD.Name(c) for c, _ in pairs])),
                        F.Item(12, Q.qbcrc(f"{na_zone}_NodeArray_SortedIndices"), QD.Array(1, [i for _, i in pairs]))]  # at the end, like THAW
        print(f"sorted node index: {len(pairs)} named nodes")
    nqb = F.write(orig_crc, items)
    geom = open(f"{src_dir}/{code}.geom.ps2", "rb").read()
    if os.environ.get("SECTORS"):  # experiment: "a:b" keeps only root children a..b-1
        a_, b_ = map(int, os.environ["SECTORS"].split(":"))
        geom, nk = GM.keep_sectors(geom, lambda i: a_ <= i < b_)
        print(f"sectors kept {a_}..{b_} of {nk}")
    if os.environ.get("KEEP_LEAVES"):  # experiment: comma list of leaf indices (depth-first) to keep
        ks = {int(x) for x in os.environ["KEEP_LEAVES"].split(",")}
        geom, nl = GM.prune_leaves(geom, lambda i: i in ks)
        print(f"leaves kept {sorted(ks)} of {nl}")
    if tex_mode.startswith("file:"):
        tex = open(tex_mode[5:], "rb").read()
        if os.environ.get("ONE_TEX"):  # experiment: every leaf uses group 1 texture 1 of the given file
            gb = bytearray(geom)
            for o_, n_ in GM.walk(geom):
                if n_[7] & 2:
                    struct.pack_into("<I", gb, o_ + 7 * 4, n_[7] | 0x100)
                    struct.pack_into("<I", gb, o_ + 11 * 4, 1)
                    struct.pack_into("<I", gb, o_ + 17 * 4, 1)
            geom = bytes(gb)
            print("all leaves -> group 1 texture 1 (texture file given)")
    elif tex_mode == "convert":
        _, t2 = T2.parse(open(f"{src_dir}/{code}.tex.ps2", "rb").read())
        from thaw_sandbox.thug2_texrefs import resolve
        refs = resolve(t2)  # header-only entries are references to textures defined elsewhere
        grey = struct.pack("<16I", *([0x80606060] * 16))  # placeholder palette, CT32, opaque grey
        new = []
        for x in t2:
            if x.mips:
                mips = x.mips[:1] if os.environ.get("TEX_TOP_ONLY") else x.mips[:4]  # THAW uses at most 4 levels
                new.append(TT.NewTexture(x.crc, x.width, x.height, x.psm, x.cpsm, x.clut, mips, group=x.group))
            elif x.crc in refs:  # header-only reference: copy the real pixels, keep this entry's group
                r = refs[x.crc]
                mips = r.mips[:1] if os.environ.get("TEX_TOP_ONLY") else r.mips[:4]
                new.append(TT.NewTexture(x.crc, r.width, r.height, r.psm, r.cpsm, r.clut, mips, group=x.group))
            else:  # unresolved: stand-in 8x8 grey so references resolve
                if os.environ.get("PLACEHOLDER32"):
                    new.append(TT.NewTexture(x.crc, 32, 32, 0x14, 0, grey, [bytes(512)], group=x.group))
                else:
                    new.append(TT.NewTexture(x.crc, 8, 8, 0x14, 0, grey, [bytes(32)], group=x.group))
        tex = TT.write(new)
        order, by = [], {}
        for t in new:  # the writer keeps groups in order of first appearance, textures in input order
            if t.group not in by:
                order.append(t.group)
                by[t.group] = []
            by[t.group].append(t.crc)
        geom, st = GM.thug2_to_thaw(geom, order, by)
        geom, ndrop = GM.drop_untextured(geom)
        st["untextured leaves dropped"] = ndrop
        if os.environ.get("LEAVES"):  # experiment: "a:b" keeps only leaves a..b-1 active
            a_, b_ = map(int, os.environ["LEAVES"].split(":"))
            geom = GM.set_active(geom, lambda i: a_ <= i < b_)
            print(f"active leaves {a_}..{b_}")
        if os.environ.get("ONE_TEX"):  # experiment: every leaf uses group 1 texture 1
            gb = bytearray(geom)
            for o_, n_ in GM.walk(geom):
                if n_[7] & 2:
                    struct.pack_into("<I", gb, o_ + 11 * 4, 1)
                    struct.pack_into("<I", gb, o_ + 17 * 4, 1)
            geom = bytes(gb)
            print("all leaves -> group 1 texture 1")
        if os.environ.get("PLAIN_TAGS"):  # experiment: vertex GIFtag word2 top half -> 0, word1 bits 12-13 -> 0
            gb = bytearray(geom)
            for o_, n_ in GM.walk(geom):
                if not n_[7] & 2:
                    continue
                cs = list(GM.vif_codes(geom, 0x10 + n_[8]))
                for j_, (p_, w_) in enumerate(cs):
                    if (w_ >> 24) & 0x6F == 0x6C and ((w_ >> 16) & 0xFF) == 1 and j_ and cs[j_ - 1][1] == 0x01000103:
                        w1_, w2_ = struct.unpack_from("<2I", gb, p_ + 8)
                        struct.pack_into("<2I", gb, p_ + 8, w1_ & ~0x3000, w2_ & 0xFFFF)
            geom = bytes(gb)
            print("vertex GIFtag microcode params cleared")
        if os.environ.get("OPAQUE"):  # experiment: ALPHA/TEST registers -> the plain opaque values
            gb = bytearray(geom)
            for o_, n_ in GM.walk(geom):
                if not n_[7] & 2:
                    continue
                for p_, w_ in GM.vif_codes(geom, 0x10 + n_[8]):
                    if (w_ >> 24) & 0x6F == 0x68:
                        for k_ in range((w_ >> 16) & 0xFF):
                            q_ = p_ + 4 + 12 * k_
                            r_ = struct.unpack_from("<I", gb, q_ + 8)[0] & 0xFF
                            if r_ == 0x42:
                                struct.pack_into("<2I", gb, q_, 0xA, 0)
                            elif r_ == 0x47:
                                struct.pack_into("<2I", gb, q_, 0x50000, 0)
            geom = bytes(gb)
            print("ALPHA/TEST forced opaque")
        if os.environ.get("CLEAR_FLAG"):  # experiment: clear these leaf flag bits
            m_ = int(os.environ["CLEAR_FLAG"], 0); gb = bytearray(geom)
            for o_, n_ in GM.walk(geom):
                if n_[7] & 2:
                    struct.pack_into("<I", gb, o_ + 7 * 4, n_[7] & ~m_)
            geom = bytes(gb)
            print(f"cleared leaf flag bits {m_:#x}")
        if os.environ.get("CLEAR_W14"):  # experiment: drop the +0x38 structure links
            gb = bytearray(geom); nclr = 0
            for o_, n_ in GM.walk(geom):
                if n_[14] != 0xFFFFFFFF:
                    struct.pack_into("<I", gb, o_ + 14 * 4, 0xFFFFFFFF); nclr += 1
                    struct.pack_into("<I", gb, o_ + 7 * 4, n_[7] & ~0x80000)
            geom = bytes(gb)
            print(f"cleared w14 on {nclr} nodes")
        if os.environ.get("RUN_LEAVES"):  # experiment: "a:b" keeps MSCAL only in leaves a..b-1
            a_, b_ = map(int, os.environ["RUN_LEAVES"].split(":"))
            geom = GM.mute_leaves(geom, lambda i: a_ <= i < b_)
            print(f"microcode runs only for leaves {a_}..{b_}")
        print(f"geometry: {st}")
        print(f"textures: {len(new)} ({sum(1 for x in t2 if not x.mips and x.crc not in refs)} grey placeholders, "
              f"{len(refs)} references resolved), {len(tex)} bytes")
    elif tex_mode == "empty":
        tex = struct.pack("<HH4I", 6, 0x14, 0, 0, 0, 0)  # version 6 header with zero textures (experiment)
    else:
        tex = open(f"{src_dir}/{code}.tex.ps2", "rb").read()
    if tex_mode == "convert" and not os.environ.get("NO_BIND"):
        geom, bst = GM.bind_textures(geom, tex)  # leaf TEX0/MIPTBP/TEX1 from the converted dictionary
        print(f"texture registers bound: {bst}")
    rep = {
        biggest[".tex"][0].pos: tex,
        biggest[".geom"][0].pos: geom,
        biggest[".col"][0].pos: CL.thug2_to_thaw(open(f"{src_dir}/{code}.col.ps2", "rb").read()),
        orig_nqb.pos: nqb,
    }
    # level scripts: keep the zone's record names (the engine calls <ZONE>_Setup etc.) with empty bodies,
    # append the THUG2 level's scripts (its nodes name them as trigger scripts); empty the ped spawn list
    named = {zb[x.pos + 32:x.pos + 192].split(b"\0")[0].decode().split("\\")[-1]: x
             for x in tab if struct.unpack_from("<I", zb, x.pos + 28)[0] & 0x20}
    se = named[f"{z}_scripts.qb.ps2"]
    sp = pak.data_pos(se, 0)
    scrc, sitems = F.read(zb[sp:sp + se.size])
    empty = C.script_body(b"\x01\x24")
    for it in sitems:
        if it.vtype == 7:
            it.value = empty
    have = {it.name for it in sitems}
    _, extra = F.read(C.convert(open(f"{src_dir}/{code}_scripts.qb", "rb").read(), "x")[0])

    if os.environ.get("NO_LEVEL_SCRIPTS"):  # experiment: leave the THUG2 level's scripts out
        extra = []
    sitems += [it for it in extra if it.name not in have]
    rep[se.pos] = F.write(scrc, sitems)
    pe = named[f"{z}_peds.qb.ps2"]
    pp = pak.data_pos(pe, 0)
    pcrc, pitems = F.read(zb[pp:pp + pe.size])
    for it in pitems:
        if it.name == Q.qbcrc(f"{z}_skate_peds"):
            it.value.items = []
    rep[pe.pos] = F.write(pcrc, pitems)
    print(f"scripts: {len(sitems)} records ({len(extra)} from {code}_scripts)")
    keep = {"tex": biggest[".tex"][0].pos, "geom": biggest[".geom"][0].pos, "col": biggest[".col"][0].pos,
            "nqb": orig_nqb.pos, "scripts": se.pos, "peds": pe.pos}
    rep = {k: v for k, v in rep.items() if k in {keep[p] for p in parts}}
    print("replacing:", ", ".join(parts), "| tex:", tex_mode)
    return zone.rebuild(zb, rep)


def main(base, out, src_dir, code, z, tex_mode="thug2", parts=("tex", "geom", "col", "nqb"), nqb_file=None, no_create=()):
    new_zone = build_zone(src_dir, code, z, tex_mode, parts, nqb_file, no_create)
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
    sys.path.insert(0, os.path.dirname(__file__))
    import rotate_isos
    rotate_isos.rotate(3)


if __name__ == "__main__":
    a = sys.argv[1:]
    mode = a[a.index("--tex") + 1] if "--tex" in a else "thug2"
    parts = a[a.index("--parts") + 1].split(",") if "--parts" in a else ("tex", "geom", "col", "nqb")
    nqbf = a[a.index("--nqb") + 1] if "--nqb" in a else None
    nc = a[a.index("--no-create") + 1].split(",") if "--no-create" in a else ()
    main(*a[:5], tex_mode=mode, parts=parts, nqb_file=nqbf, no_create=nc)
