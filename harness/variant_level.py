"""Bisect a converted level: build an image where some parts of the new zone are Kyoto's originals.

usage: variant_level.py BASE_THAW.iso OUT.iso SOURCE_DISC CODE PARTS_FROM_KYOTO
PARTS_FROM_KYOTO: comma list of tex,geom,col,nqb,scripts ('' = none). tex and geom go together.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from thaw_sandbox import build as B, level_convert as L, zone  # noqa: E402

base, out, disc, code, parts = sys.argv[1:6]
parts = set(p for p in parts.split(",") if p)
orig = L.convert_level


def patched(template_zone, files, code_, zone_name, resolve_refs, template="z_ja", level_scripts=True):
    zb, st = orig(template_zone, files, code_, zone_name, resolve_refs, template, level_scripts and "scripts" not in parts)
    tab_t, tab_n = zone.entries(template_zone), zone.entries(zb)
    big_t, big_n = L._biggest(template_zone, tab_t), L._biggest(zb, tab_n)
    from thaw_sandbox import pak
    rep = {}
    for p in parts & {"tex", "geom", "col", "nqb"}:
        e = big_t["." + p]
        d = pak.data_pos(e, 0)
        rep[big_n["." + p].pos] = template_zone[d:d + e.size]
    if rep:
        zb = zone.rebuild(zb, rep)
    print("kyoto parts:", sorted(parts))
    return zb, st


if os.environ.get("NODE_KEEP"):  # keep only these node classes; links dropped (indices change)
    from thaw_sandbox import qb_parser as Q
    keep = {Q.qbcrc(c) for c in os.environ["NODE_KEEP"].split(",")}
    CLS, LINKS = Q.qbcrc("Class"), Q.qbcrc("links")

    def flt(nodes):
        out = [s for s in nodes if any(k == CLS and getattr(v, "crc", None) in keep for k, v in s.items)]
        for s in out:
            s.items = [(k, v) for k, v in s.items if k != LINKS]
        print(f"nodes kept: {len(out)} of {len(nodes)}")
        return out
    L.NODE_FILTER = flt
if os.environ.get("SCRIPT_RANGE"):  # keep only level scripts a..b-1 (records in file order); others dropped
    a_, b_ = map(int, os.environ["SCRIPT_RANGE"].split(":"))

    def sflt(items):
        print(f"level scripts kept {a_}..{b_} of {len(items)}")
        kept = items[a_:b_]
        if os.environ.get("SCRIPT_RENAME"):  # rename the kept scripts (tests a name collision vs the body)
            for it in kept:
                it.name ^= 0x5A5A0000
        return kept
    L.SCRIPT_FILTER = sflt
if os.environ.get("ALL_SCRIPTS"):  # lift a source's per-level no-scripts exceptions
    from thaw_sandbox.sources import thps4
    thps4.NO_SCRIPTS.clear()
if os.environ.get("LEAVES"):  # keep only converted leaves a..b-1 (depth-first order); the rest are unlinked
    from thaw_sandbox import geom as GM
    la, lb = map(int, os.environ["LEAVES"].split(":"))
    _ctg = L.convert_textures_and_geometry

    def ctg(*a, **k):
        tex, geom, st = _ctg(*a, **k)
        geom, n = GM.prune_leaves(geom, lambda i: la <= i < lb)
        print(f"leaves kept {la}..{lb} ({n})")
        return tex, geom, st
    L.convert_textures_and_geometry = ctg
L.convert_level = patched
B.build(base, [(disc, [code])], out, "_workspace/e2e")
