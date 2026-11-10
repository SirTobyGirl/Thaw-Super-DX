"""Register a new level with THAW's scripts (qb.pak/qb.pab), with Kyoto (z_ja) as the template for everything.

    files = register(qb_pak, qb_pab, zone, display, zone_size, ped_size, setup_script)  -> (new pak, new pab)

Edits (each one was needed in game; see the notes):
  levels.qb               Level_<ZONE> struct + load_<ZONE> script; SkaterCareerParams.level_table entry (a level
                          missing from it takes the "default" load path and never finishes loading)
  cheats.qb               cheat_reallygivelevels unlocks it (else the list shows ????????? and it can't be picked)
  gamemenu_levelselect.qb level-select entry after Kyoto and earlier added levels
  zone_links.qb           SkateZones.<zone>
  zone_sizes_ps2.qb       memory budgets for <zone> and <zone>ped
qb.pab is rebuilt back to back (pak.repack_compact): it may grow.
"""
import copy
import os
import struct
import tempfile

from thaw_sandbox import convert_thug2 as C, lzss, pak, qb_data as QD, qb_file as F, qb_parser as Q

H = Q.qbcrc
TEMPLATE = "z_ja"


def _get(items, name):
    return next(it for it in items if it.name == H(name))


def _set(struct_v, key, value):
    """Replace a struct field keeping its value type (str vs LStr etc.)."""
    for i, (k, v) in enumerate(struct_v.items):
        if k == H(key):
            struct_v.items[i] = (k, type(v)(value) if not isinstance(v, QD.Name) else QD.Name(H(value)))
            return
    raise KeyError(key)


def _edits(zn, display, zone_size, ped_size, setup):
    ZN, TZ = zn.upper(), TEMPLATE.upper()

    def levels(items):
        lv = copy.deepcopy(_get(items, f"Level_{TZ}"))
        lv.name = H(f"Level_{ZN}")
        s = lv.value
        _set(s, "structure_name", f"Level_{ZN}")
        _set(s, "load_script", f"load_{ZN}")
        _set(s, "name", display)
        _set(s, "Level", ZN)
        _set(s, "goals_script", f"{ZN}_Goals")  # the zone's scripts are renamed z_ja -> zn (zone_rename)
        _set(s, "setup_script", setup or f"{ZN}_Setup")
        items.append(lv)
        lt = next(v for k, v in _get(items, "SkaterCareerParams").value.items if k == H("level_table"))
        ent = copy.deepcopy(next(e for e in lt.items if any(
            k == H("names") and any(isinstance(x, str) and x.lower() == TEMPLATE for x in v.items) for k, v in e.items)))
        for i, (k, v) in enumerate(ent.items):
            if k == H("names"):
                v.items = [type(v.items[0])(zn), type(v.items[1])(zn[2:])]
            elif k == H("include_in_all_gaps_check"):
                ent.items[i] = (k, 0)
        lt.items.append(ent)  # appended so existing indices stay put
        ld = copy.deepcopy(_get(items, f"load_{TZ}"))
        _, code = lzss.unpack_body(ld.value)
        old, new = struct.pack("<I", H(f"Level_{TZ}")), struct.pack("<I", H(f"Level_{ZN}"))
        assert code.count(old) == 1
        ld.name = H(f"load_{ZN}")
        ld.value = C.script_body(code.replace(old, new))
        items.append(ld)

    def unlock(items):
        it = _get(items, "cheat_reallygivelevels")
        _, code = lzss.unpack_body(it.value)
        tok = b"\x16" + struct.pack("<I", H(f"load_{TZ}"))
        assert code.count(tok) == 1
        i = code.index(tok) + 5
        while code[i] == 0x01:  # keep the newline after the entry
            i += 1
        code = code[:i] + b"\x16" + struct.pack("<I", H(f"load_{ZN}")) + b"\x01" + code[i:]
        it.value = C.script_body(code)

    def menu(items):
        arr = _get(items, "level_select_menu_level_info").value
        i = next(k for k, e in enumerate(arr.items)
                 if any(kk == H("Level") and getattr(v, "crc", 0) == H(f"load_{TZ}") for kk, v in e.items))
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
        e = copy.deepcopy(next(v for k, v in sz.items if k == H(TEMPLATE)))
        _set(e, "name", ZN)
        sz.items.append((H(zn), e))

    def sizes(items):
        zs = _get(items, "zone_sizes_ps2").value
        for key, size in ((zn, zone_size), (f"{zn}ped", ped_size)):
            tmpl = copy.deepcopy(next(v for k, v in zs.items if k == H(TEMPLATE)))
            tmpl.items = [(k, size) for k, _ in tmpl.items]
            zs.items.append((H(key), tmpl))

    return (("levels.qb.ps2", levels), ("gamemenu_levelselect.qb.ps2", menu), ("zone_links.qb.ps2", zones),
            ("zone_sizes_ps2.qb.ps2", sizes), ("cheats.qb.ps2", unlock))


def _find(root, fn):
    for r, _, fs in os.walk(root):
        if fn in fs:
            return os.path.join(r, fn)
    raise FileNotFoundError(fn)


def register(qb_pak, qb_pab, zn, display, zone_size, ped_size, setup=None, tmp_dir=None):
    with tempfile.TemporaryDirectory(dir=tmp_dir) as tmp:
        src = os.path.join(tmp, "qb")
        open(os.path.join(tmp, "in.pak"), "wb").write(qb_pak)
        open(os.path.join(tmp, "in.pab"), "wb").write(qb_pab)
        pak.unpack(os.path.join(tmp, "in.pak"), os.path.join(tmp, "in.pab"), src)
        for fn, edit in _edits(zn, display, zone_size, ped_size, setup):
            p = _find(src, fn)
            crc, items = F.read(open(p, "rb").read())
            edit(items)
            open(p, "wb").write(F.write(crc, items))
        return pak.repack_compact(qb_pak, qb_pab, src)
