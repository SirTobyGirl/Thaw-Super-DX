"""Add a converted THUG2 level to THAW as a NEW level (its own zone, level struct and level-list entry).

usage: add_level.py BASE.iso OUT.iso THUG2_CODE ZONE "Display name"
       add_level.py BASE.iso OUT.iso code:zone:Name [code:zone:Name ...]
e.g.   add_level.py _workspace/build/grow.iso _workspace/build/thug2.iso tr:z_tr:Training be:z_be:Berlin

BASE must be an image prepared by thaw_sandbox.iso_build (DATAP.WAD/HED moved to the end with slack).
What it adds (Kyoto, z_ja, is the template for everything level-wide):
  worlds\\worldzones\\ZONE\\ZONE.pak.ps2   converted level (Kyoto's zone PAK layout; node array = ZONE_NodeArray)
  worlds\\worldzones\\ZONE\\ZONEped.pak.ps2 and sounds\\pak\\ZONE_sfx.pak.ps2   copies of Kyoto's
  qb.pab: Level_ZONE + load_ZONE (levels.qb), a level-select entry after Kyoto (gamemenu_levelselect.qb),
          SkateZones.ZONE (zone_links.qb), zone_sizes_ps2.ZONE / ZONEped
"""
import copy
import os
import shutil
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from thaw_sandbox import convert_thug2 as C  # noqa: E402
from thaw_sandbox import iso_manager as I, lzss, pak, qb_data as QD, qb_file as F, qb_parser as Q  # noqa: E402
from thaw_sandbox.disc import Disc  # noqa: E402
import build_level_test as B  # noqa: E402

QBPAK = "_workspace/qbpak"
NO_CREATE = ("LevelObject", "LevelLight", "Pedestrian", "Vehicle", "ParticleObject", "GameObject")
H = Q.qbcrc


def _get(items, name):
    return next(it for it in items if it.name == H(name))


def _set(struct_v, key, value):
    """Replace a struct field keeping its value type (str vs LStr etc.)."""
    for i, (k, v) in enumerate(struct_v.items):
        if k == H(key):
            struct_v.items[i] = (k, type(v)(value) if not isinstance(v, QD.Name) else QD.Name(H(value)))
            return
    raise KeyError(key)


def _drop(struct_v, key):
    struct_v.items = [(k, v) for k, v in struct_v.items if k != H(key)]


def edit_qbs(src, zn, display, zone_size, ped_size, trim_net_zones=False, setup=None):
    ZN = zn.upper()
    nt = Q.NameTable.load("_workspace/qbwork/names.pkl")

    def rw(rel, fn):
        p = os.path.join(src, rel)
        crc, items = F.read(open(p, "rb").read())
        fn(items)
        open(p, "wb").write(F.write(crc, items))

    def levels(items):
        lv = copy.deepcopy(_get(items, "Level_Z_JA"))
        lv.name = H(f"Level_{ZN}")
        s = lv.value
        _set(s, "structure_name", f"Level_{ZN}")
        _set(s, "load_script", f"load_{ZN}")
        _set(s, "name", display)
        _set(s, "Level", ZN)
        _set(s, "goals_script", f"{ZN}_Goals")  # the zone's scripts are renamed z_ja -> zn (zone_rename)
        _set(s, "setup_script", setup or f"{ZN}_Setup")  # THUG2's own <code>_setup when the level has one
        if os.environ.get("NO_PEDS"):  # experiment: with pedlife off the load never finished
            _set(s, "pedlife_allowed", 0)
            _drop(s, "classic_mode_navmesh")
        items.append(lv)
        # SkaterCareerParams.level_table: a level missing from it is handled like "default" (the load took a
        # different path - CAS assets, no ped/navmesh - and never finished). Appended so indices stay put.
        lt = next(v for k, v in _get(items, "SkaterCareerParams").value.items if k == H("level_table"))
        ent = copy.deepcopy(next(e for e in lt.items if any(
            k == H("names") and any(isinstance(x, str) and x.lower() == "z_ja" for x in v.items) for k, v in e.items)))
        for i, (k, v) in enumerate(ent.items):
            if k == H("names"):
                v.items = [type(v.items[0])(zn), type(v.items[1])(zn[2:])]
            elif k == H("include_in_all_gaps_check"):
                ent.items[i] = (k, 0)
        lt.items.append(ent)
        ld = copy.deepcopy(_get(items, "load_Z_JA"))
        crc, code = lzss.unpack_body(ld.value)
        old, new = struct.pack("<I", H("Level_Z_JA")), struct.pack("<I", H(f"Level_{ZN}"))
        assert code.count(old) == 1
        ld.name = H(f"load_{ZN}")
        ld.value = C.script_body(code.replace(old, new))
        items.append(ld)

    def unlock(items):
        # the sandbox boot calls cheat_reallygivelevels, which marks every level in its list as visited
        # (unlocked); a level not in it shows as ????????? and cannot be picked
        it = _get(items, "cheat_reallygivelevels")
        crc, code = lzss.unpack_body(it.value)
        tok = b"\x16" + struct.pack("<I", H("load_Z_JA"))
        assert code.count(tok) == 1
        i = code.index(tok) + 5
        while code[i] == 0x01:  # keep the newline after the entry
            i += 1
        code = code[:i] + b"\x16" + struct.pack("<I", H(f"load_{ZN}")) + b"\x01" + code[i:]
        it.value = C.script_body(code)

    def menu(items):
        arr = _get(items, "level_select_menu_level_info").value
        i = next(k for k, e in enumerate(arr.items)
                 if any(kk == H("Level") and getattr(v, "crc", 0) == H("load_Z_JA") for kk, v in e.items))
        e = copy.deepcopy(arr.items[i])
        _set(e, "text", display.upper())
        _set(e, "Level", f"load_{ZN}")
        poster = next(v for k, v in arr.items[i].items if k == H("poster"))
        j = i + 1
        while j < len(arr.items) and any(k == H("poster") and getattr(v, "crc", None) == poster.crc
                                         for k, v in arr.items[j].items):
            j += 1  # earlier added levels (copies of Kyoto's entry) stay in order
        arr.items.insert(j, e)

    def zones(items):
        sz = _get(items, "SkateZones").value
        e = copy.deepcopy(next(v for k, v in sz.items if k == H("z_ja")))
        _set(e, "name", ZN)
        sz.items.append((H(zn), e))
        if trim_net_zones:  # more room if needed: online zone links are unused in the sandbox
            _get(items, "NetSkateZones").value.items = []

    def sizes(items):
        zs = _get(items, "zone_sizes_ps2").value
        # room: qb.pab may not grow; drop budgets of online (_net) and test/viewer zones (the sandbox has no
        # online play and never loads test zones)
        if os.environ.get("TRIM"):  # optional; qb.pab can grow (the old crash came from the append repack)
            zs.items = [(k, v) for k, v in zs.items
                        if not (nt.get(k).lower().endswith("_net") or "test" in nt.get(k).lower())]
        for key, size in ((zn, zone_size), (f"{zn}ped", ped_size)):
            tmpl = copy.deepcopy(next(v for k, v in zs.items if k == H("z_ja")))
            tmpl.items = [(k, size) for k, _ in tmpl.items]
            zs.items.append((H(key), tmpl))

    def zones_swap(items):  # experiment: reuse an existing SkateZones slot so the file does not grow
        sz = _get(items, "SkateZones").value
        e = copy.deepcopy(next(v for k, v in sz.items if k == H("z_ja")))
        _set(e, "name", ZN)
        idx = next(i for i, (k, v) in enumerate(sz.items) if k not in (H("z_ja"),) and i > 5)
        sz.items[idx] = (H(zn), e)

    only = os.environ.get("QB_ONLY", "levels,menu,zones,sizes,unlock").split(",")  # experiment switch
    for key, fn, f in (("levels", "levels.qb.ps2", levels), ("menu", "gamemenu_levelselect.qb.ps2", menu),
                       ("zones", "zone_links.qb.ps2", zones), ("sizes", "zone_sizes_ps2.qb.ps2", sizes),
                       ("unlock", "cheats.qb.ps2", unlock),
                       ("noop", "zone_links.qb.ps2", lambda items: None),
                       ("zswap", "zone_links.qb.ps2", zones_swap)):
        if key in only:
            rw(_find(src, fn), f)


def _find(root, fn):
    for r, _, fs in os.walk(root):
        if fn in fs:
            return os.path.relpath(os.path.join(r, fn), root)
    raise FileNotFoundError(fn)


def add_one(d, code, zn, display):
    zone = B.build_zone(f"_workspace/thug2/{code}", code, "z_ja", "convert",
                        ("tex", "geom", "col", "nqb", "scripts", "peds"), None, NO_CREATE, na_zone=zn)
    # everything copied from Kyoto is renamed to the new zone (scene/record lookups go by zone name)
    from thaw_sandbox.zone_rename import rename_zone
    nt = Q.NameTable.load("_workspace/qbwork/names.pkl")
    zone, st = rename_zone(zone, "z_ja", zn, nt)
    ped, _ = rename_zone(d.read("\\worlds\\worldzones\\z_ja\\z_japed.pak.ps2"), "z_ja", zn, nt)
    sfx, _ = rename_zone(d.read("\\sounds\\pak\\z_ja_sfx.pak.ps2"), "z_ja", zn, nt)
    d.add(f"\\worlds\\worldzones\\{zn}\\{zn}.pak.ps2", zone)
    d.add(f"\\worlds\\worldzones\\{zn}\\{zn}ped.pak.ps2", ped)
    d.add(f"\\sounds\\pak\\{zn}_sfx.pak.ps2", sfx)
    with tempfile.TemporaryDirectory(dir="_workspace") as tmp:
        # edit the QB files as they are on THIS image (sandbox boot patches, earlier added levels)
        src = os.path.join(tmp, "qb")
        open(os.path.join(tmp, "in.pak"), "wb").write(d.read("\\pak\\qb.pak.ps2"))
        open(os.path.join(tmp, "in.pab"), "wb").write(d.read("\\pak\\qb.pab.ps2"))
        pak.unpack(os.path.join(tmp, "in.pak"), os.path.join(tmp, "in.pab"), src)
        setup = None
        if not os.environ.get("NO_LEVEL_SCRIPTS"):
            from thaw_sandbox import thug2_qb
            sq = thug2_qb.parse(open(f"_workspace/thug2/{code}/{code}_scripts.qb", "rb").read())
            if H(f"{code}_setup") in sq.scripts:
                setup = f"{code}_setup"
        edit_qbs(src, zn, display, len(zone), len(ped), trim_net_zones=bool(os.environ.get("TRIM_NET")), setup=setup)
        print(f"  setup script: {setup or 'none (empty ' + zn.upper() + '_Setup)'}")
        old_pak, old_pab = d.read("\\pak\\qb.pak.ps2"), d.read("\\pak\\qb.pab.ps2")
        new_pak, new_pab = pak.repack_compact(old_pak, old_pab, src)
        print(f"  qb.pab: {len(old_pab)} -> {len(new_pab)} bytes")
        d.put("\\pak\\qb.pak.ps2", new_pak)
        d.put("\\pak\\qb.pab.ps2", new_pab)
    d.save()
    print(f"added {display} as {zn}: zone {len(zone)} bytes")


def main(base, out, specs):
    """specs: [(thug2 code, zone, display name)]"""
    I.stage_copy(base, out)
    for code, zn, display in specs:
        d = Disc(out)
        add_one(d, code, zn, display)
    print("built", out)
    import rotate_isos
    rotate_isos.rotate(3)


if __name__ == "__main__":
    # add_level.py BASE OUT CODE ZONE "Name"   or   add_level.py BASE OUT code:zone:Name [code:zone:Name ...]
    a = sys.argv[1:]
    if len(a) == 5 and ":" not in a[2]:
        main(a[0], a[1], [(a[2], a[3], a[4])])
    else:
        main(a[0], a[1], [tuple(x.split(":", 2)) for x in a[2:]])
