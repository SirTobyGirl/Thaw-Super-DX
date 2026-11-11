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

from thaw_sandbox import convert_thug2 as C, lzss, pak, qb_data as QD, qb_file as F, qb_parser as Q, qb_tokens as T

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


# The career keeps one flag object per level-table entry in a fixed array of 40 (CCareer+0x24: pointers at +8,
# the level lookup map right after at +0xa8; SetFlag/GetFlag FUN_002fb540/FUN_002fb600). Entries past 40 have no
# flags: LEVEL_VISITED never sticks and the level shows as ?????????.
LEVEL_SLOTS = 40
# base entries the sandbox can never reach (test, viewer and story-select zones): reused for new levels
DEAD_SLOTS = ("z_testlevel", "z_test_nn", "z_viewer", "z_storyselect")


def _names(e):
    return next(v for k, v in e.items if k == H("names"))


def _place_in_level_table(lt, ent, zn):
    """Append while there are free slots (indices of existing levels stay put), then take over a dead base entry,
    then share the last added entry (its names list gets this zone too: the levels share career flags, i.e. the
    visited flag, gap and high score records)."""
    if len(lt.items) < LEVEL_SLOTS:
        lt.items.append(ent)
        return "new"
    for i, e in enumerate(lt.items):
        nm = _names(e).items
        if nm and isinstance(nm[0], str) and nm[0].lower() in DEAD_SLOTS:
            lt.items[i] = ent
            return "reused"
    last = _names(lt.items[-1])
    last.items += [type(last.items[0])(zn), type(last.items[0])(zn[2:])]
    return "shared"


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
        _place_in_level_table(lt, ent, zn)
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
    return edit_files(qb_pak, qb_pab, _edits(zn, display, zone_size, ped_size, setup), tmp_dir)


def _no_special_locks(items):
    arr = _get(items, "level_select_menu_level_info").value
    for e in arr.items:
        e.items = [(k, v) for k, v in e.items if k != H("special_case_flag")]


# free skate: levels with an extra story lock (Skate Ranch: special_case_flag Z_SR_UNLOCKED_WITH_STORY) open too
UNLOCK_EDITS = (("gamemenu_levelselect.qb.ps2", _no_special_locks),)


def open_added_edits(zones):
    """Without unlock-all THAW's levels open as story mode visits them, which never happens for added levels:
    opening the level select (launch_level_select_menu, whose first call hide_current_goal is swapped for this
    script) marks them visited."""
    def edit(items):
        code = T.assemble("hide_current_goal\n" + "\n".join(
            f"SetFlag Level = load_{z.upper()} flag = LEVEL_VISITED" for z in zones), H)
        items.append(F.Item(7, H("sdx_open_added_levels"), C.script_body(code)))
        it = _get(items, "launch_level_select_menu")
        _, c = lzss.unpack_body(it.value)
        old, new = (b"\x16" + struct.pack("<I", H(n)) for n in ("hide_current_goal", "sdx_open_added_levels"))
        assert c.count(old) == 1
        try:
            it.value = lzss.patch_code(it.value, c.replace(old, new))
        except ValueError:
            it.value = C.script_body(c.replace(old, new))
    return (("gamemenu_levelselect.qb.ps2", edit),)


def edit_files(qb_pak, qb_pab, edits, tmp_dir=None):
    """Apply [(qb file name, edit(items))] to the global script pack -> (new pak, new pab)."""
    with tempfile.TemporaryDirectory(dir=tmp_dir) as tmp:
        src = os.path.join(tmp, "qb")
        open(os.path.join(tmp, "in.pak"), "wb").write(qb_pak)
        open(os.path.join(tmp, "in.pab"), "wb").write(qb_pab)
        pak.unpack(os.path.join(tmp, "in.pak"), os.path.join(tmp, "in.pab"), src)
        for fn, edit in edits:
            p = _find(src, fn)
            crc, items = F.read(open(p, "rb").read())
            edit(items)
            open(p, "wb").write(F.write(crc, items))
        return pak.repack_compact(qb_pak, qb_pab, src)
