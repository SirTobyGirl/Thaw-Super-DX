"""Build a test ISO from the vanilla one by editing QB scripts in place (sizes never change).

usage: patch_iso.py OUT.iso SPEC [SPEC ...]
  SCRIPT:OLD_NAME:NEW_NAME   swap every OLD_NAME hash in SCRIPT's decompressed code for NEW_NAME's
                             (OLD_NAME may be a raw 0x... hash; lzss.patch_code edits literal bytes of
                             the stream and verifies by re-decoding)
  SCRIPT@=statement text     overwrite the first bytes of SCRIPT's code (lzss.patch_prefix; needs literal
                             room; the code must end with endscript, the stale tail is never reached)
SCRIPT is looked up by name in z_mainmenu_scripts.qb (zone PAK) and in every script of pak/qb.pab.
Whole-body replacement is NOT offered: the game silently did not run replaced bodies.
The vanilla ISO is copied to OUT first and never modified.
Run from the project root with PYTHONPATH=. (needs _workspace/stage/*, _workspace/datap/*, names.pkl).
"""
import struct
import sys

from thaw_sandbox import iso_manager as I, lzss, pak, qb_parser as Q, qb_tokens as T, wad

VANILLA = "_workspace/stage/thaw_vanilla.iso"
HED = "_workspace/stage/DATAP.HED"
D = "_workspace/datap/"


class Container:
    """A WAD entry holding QB files: the z_mainmenu zone PAK (data inline) or pak/qb.pab (index in qb.pak)."""

    def __init__(self, wad_name, local, index=None):
        self.wad_name, self.local = wad_name, local
        self.data = bytearray(open(local, "rb").read())
        if index is None:
            ents, base = pak.parse_pak(bytes(self.data)), 0
        else:
            idx = open(index, "rb").read()
            ents, base = pak.parse_pak(idx), len(idx)
        self.files = [(e.name, pak.data_pos(e, base), e.size) for e in ents if e.name.endswith(".qb.ps2")]


def main(out, specs):
    names = Q.NameTable.load("_workspace/qbwork/names.pkl")
    wad_off, _ = I.file_extent(VANILLA, "/DATAP.WAD;1")
    hed, _ = wad.parse_hed(open(HED, "rb").read())
    conts = [
        Container("z_mainmenu\\z_mainmenu.pak.ps2", D + "worlds/worldzones/z_mainmenu/z_mainmenu.pak.ps2"),
        Container("\\pak\\qb.pab.ps2", D + "pak/qb.pab.ps2", index=D + "pak/qb.pak.ps2"),
    ]
    # script name -> (container, body position inside the container, body length, file name)
    where = {}
    for c in conts:
        for fname, pos, size in c.files:
            qb = bytes(c.data[pos:pos + size])
            if len(qb) < 0x40:
                continue
            for r in Q.parse(qb).records:
                if r.vtype == 7:
                    where.setdefault(names.get(r.name), (c, pos + r.body_pos, len(r.body), fname))
    for spec in specs:
        if "@=" in spec.split(":")[0]:
            script, text = spec.split("@=", 1)
            c, bp, bl, fname = where[script]
            code = T.assemble(text.replace(";", "\n"), Q.qbcrc)
            c.data[bp:bp + bl] = lzss.patch_prefix(bytes(c.data[bp:bp + bl]), code)
            print(f"{script} ({fname}): first {len(code)} code bytes patched in place")
            continue
        script, old, new = spec.split(":")
        c, bp, bl, fname = where[script]
        oldbody = bytes(c.data[bp:bp + bl])
        code = lzss.unpack_body(oldbody)[1]
        oh = int(old, 16) if old.startswith("0x") else Q.qbcrc(old)
        o, n = struct.pack("<I", oh), struct.pack("<I", Q.qbcrc(new))
        hits = [i for i in range(len(code) - 3) if code[i:i + 4] == o]
        assert hits, f"{old} not found in {script}"
        edited = bytearray(code)
        for i in hits:
            edited[i:i + 4] = n
        c.data[bp:bp + bl] = lzss.patch_code(oldbody, bytes(edited))
        print(f"{script} ({fname}): {old} -> {new} x{len(hits)}")
    I.stage_copy(VANILLA, out)
    wad_bytes = None
    for c in conts:
        e = next(x for x in hed if x.name.endswith(c.wad_name))
        orig = open(c.local, "rb").read()
        assert len(orig) == len(c.data) == e.size
        if bytes(c.data) != orig:
            I.patch_in_place(out, wad_off + e.offset * 2048, bytes(c.data))
            wad_bytes = wad_bytes or I.read_file(out, "/DATAP.WAD;1")
            back = I.read_file(out, "/DATAP.WAD;1")[e.offset * 2048:e.offset * 2048 + e.size]
            assert back == bytes(c.data), f"readback mismatch for {c.wad_name}"
    print("built", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
