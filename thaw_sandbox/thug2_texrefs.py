"""Resolve THUG2 'header-only' textures (flag bit 31: no pixels in this entry).

They are references to a texture defined elsewhere: in another group of the same .tex file (most), or in another
level's .tex (mainmenu, other levels, the park editor set). Checked on Training: 106/106 found with pixels.
The index of every THUG2 .tex on the disc is cached in _workspace/thug2/tex_index.pkl.
"""
import os
import pickle
import sys

from thaw_sandbox import iso_manager as I, thug2_tex as T2

INDEX = "_workspace/thug2/tex_index.pkl"
ISO = "iso/TonyHawksUnderground2.ISO"


def _hed():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
    import extract_thug2_level as X
    return X.hed_entries(I.read_file(ISO, "/DATAP.HED;1"))


def _read(name, hed, wad_off):
    off, size = hed[name]
    with open(ISO, "rb") as f:
        f.seek(wad_off + off)
        return f.read(size)


def index():
    """crc -> list of .tex file names (on the THUG2 disc) that define it with pixels."""
    if os.path.exists(INDEX):
        return pickle.load(open(INDEX, "rb"))
    hed = _hed()
    wo, _ = I.file_extent(ISO, "/DATAP.WAD;1")
    idx = {}
    for name in hed:
        if not name.endswith(".tex.ps2"):
            continue
        try:
            _, tt = T2.parse(_read(name, hed, wo))
        except Exception:
            continue
        for x in tt:
            if x.mips:
                idx.setdefault(x.crc, []).append(name)
    pickle.dump(idx, open(INDEX, "wb"))
    return idx


def resolve(textures):
    """Return {crc: Texture with pixels} for every header-only texture in `textures` (THUG2 Texture list)."""
    local = {x.crc: x for x in textures if x.mips}
    out, missing = {}, []
    for x in textures:
        if x.mips:
            continue
        if x.crc in local:
            out[x.crc] = local[x.crc]
        else:
            missing.append(x.crc)
    if missing:
        idx = index()
        hed = _hed()
        wo, _ = I.file_extent(ISO, "/DATAP.WAD;1")
        cache = {}
        for crc in missing:
            files = idx.get(crc)
            if not files:
                continue
            if files[0] not in cache:
                _, tt = T2.parse(_read(files[0], hed, wo))
                cache[files[0]] = {t.crc: t for t in tt if t.mips}
            out[crc] = cache[files[0]][crc]
    return out
