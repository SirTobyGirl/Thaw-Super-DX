"""Extract one THUG2 level's files from the THUG2 ISO (DATAP.HED/WAD, byte offsets).
usage: extract_thug2_level.py CODE [OUT_DIR]   e.g. extract_thug2_level.py tr  -> _workspace/thug2/tr/
Writes CODE.geom.ps2, CODE.col.ps2, CODE.tex.ps2, CODE.qb (node array), CODE_scripts.qb (non-net versions)."""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from thaw_sandbox import iso_manager as I  # noqa: E402

ISO = "iso/TonyHawksUnderground2.ISO"


def hed_entries(h):
    p, out = 0, {}
    while p + 8 <= len(h):
        off, size = struct.unpack_from("<iI", h, p)
        if off == -1:
            break
        e = h.index(b"\0", p + 8)
        out[h[p + 8:e].decode("latin1").lower()] = (off, size)
        p = (e + 1 + 3) & ~3
    return out


def main(code, out_dir=None):
    out_dir = out_dir or f"_workspace/thug2/{code}"
    os.makedirs(out_dir, exist_ok=True)
    hed = hed_entries(I.read_file(ISO, "/DATAP.HED;1"))
    wad_off, _ = I.file_extent(ISO, "/DATAP.WAD;1")
    want = {f"{code}.geom.ps2", f"{code}.col.ps2", f"{code}.tex.ps2", f"{code}.qb", f"{code}_scripts.qb"}
    with open(ISO, "rb") as f:
        for name, (off, size) in hed.items():
            base = name.split("\\")[-1]
            if name.startswith(f"\\levels\\{code}\\") and base in want:
                f.seek(wad_off + off)
                open(os.path.join(out_dir, base), "wb").write(f.read(size))
                print(f"{base:24s} {size:9d}")


if __name__ == "__main__":
    main(*sys.argv[1:])
