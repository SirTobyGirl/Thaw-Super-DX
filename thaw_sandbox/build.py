"""The whole pipeline: the user's THAW disc + source discs -> a new THAW image.

    build(thaw_disc, [(source_disc, [level codes] or None for all)], out_iso, work_dir)

1. disc images: .chd is extracted with chdman (MAME tools) into work_dir; .iso is used as is (never modified)
2. copy THAW, make room (iso_build: DATAP.WAD grows over the movies), apply the free-skate boot patches
3. names table from THAW's own scripts and debug names (zone renaming needs the original strings)
4. per level: convert (level_convert), rename Kyoto's internals to the new zone (zone_rename), add the zone, ped and
   sfx packs, register it in the scripts (level_register)
"""
import os
import shutil
import subprocess

from thaw_sandbox import elf_patch, iso_build, iso_manager as I, level_convert, level_register, qb_parser as Q, sandbox_patch
from thaw_sandbox import sources, thug2_qb
from thaw_sandbox.disc import Disc
from thaw_sandbox.zone_rename import rename_zone

THAW_SERIALS = ("SLUS_212.95",)
TEMPLATE = "z_ja"
MAX_NEW_LEVELS = 64  # past 20 new levels some share a career slot (level_register: 40 slots in THAW's career)
NAME_SOURCES = ("\\pak\\dbg.pak.ps2", "\\pak\\dbgq.pak.ps2", "\\pak\\dbgq.pab.ps2", "\\pak\\qb.pab.ps2",
                f"\\worlds\\worldzones\\{TEMPLATE}\\{TEMPLATE}.pak.ps2",
                f"\\worlds\\worldzones\\{TEMPLATE}\\{TEMPLATE}ped.pak.ps2", f"\\sounds\\pak\\{TEMPLATE}_sfx.pak.ps2")
log = print


def disc_image(path, work_dir):
    """An ISO path for a disc given as .iso or .chd (extracted once into work_dir)."""
    if not path.lower().endswith(".chd"):
        return path
    out = os.path.join(work_dir, os.path.basename(path)[:-4] + ".iso")
    if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(path):
        return out
    if not shutil.which("chdman"):
        raise RuntimeError("a .chd needs chdman (MAME tools; e.g. 'sudo dnf install mame-tools') - or give an .iso")
    log(f"extracting {os.path.basename(path)} ...")
    info = subprocess.run(["chdman", "info", "-i", path], check=True, capture_output=True, text=True).stdout
    tmp = out + ".part"
    if "TRACK:" in info:  # stored as a CD (PS2 DVD dumps often are): units of sector data + subcode
        tracks = [ln for ln in info.splitlines() if "TRACK:" in ln]
        if len(tracks) != 1:
            raise ValueError(f"{path}: {len(tracks)} tracks; a PS2 DVD image has one")
        ttype = tracks[0].split("TYPE:")[1].split()[0]
        skip = {"MODE1": 0, "MODE1_RAW": 16, "MODE2_FORM1": 0}.get(ttype)
        if skip is None:
            raise ValueError(f"{path}: track type {ttype} not supported")
        unit = int(info.split("Unit Size:")[1].split()[0].replace(",", ""))
        raw = out + ".raw"
        subprocess.run(["chdman", "extractdvd", "-f", "-i", path, "-o", raw], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with open(raw, "rb") as fi, open(tmp, "wb") as fo:
            while True:
                chunk = fi.read(unit * 4096)
                if not chunk:
                    break
                fo.write(b"".join(chunk[i + skip:i + skip + 2048] for i in range(0, len(chunk), unit)))
        os.remove(raw)
    else:
        subprocess.run(["chdman", "extractdvd", "-f", "-i", path, "-o", tmp], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.replace(tmp, out)
    return out


def is_thaw(iso):
    try:
        cnf = I.read_file(iso, "/SYSTEM.CNF;1")
    except Exception:
        return False
    return any(s.encode() in cnf for s in THAW_SERIALS)


def names_table(d):
    nt = Q.NameTable()
    for n in NAME_SOURCES:
        nt.add_bytes(d.read(n))
    return nt


def zone_names(codes, taken, hints=None):
    """THAW zone names are z_ + 2 characters (the template's length; renaming is in place). -> {code: zone}"""
    out, used, hints = {}, set(taken), hints or {}
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    for code in codes:
        cands = [hints[code]] if code in hints else []
        cands += [f"z_{code}"] if len(code) == 2 else []
        cands += [f"z_{code[0]}{c}" for c in alphabet] + [f"z_{a}{b}" for a in alphabet for b in alphabet]
        z = next(c for c in cands if len(c) == 4 and c not in used)
        used.add(z)
        out[code] = z
    return out


ROOM_PER_LEVEL = 14 * 2**20  # zone (<= 10.4 MB) + ped + sfx packs + a re-appended qb.pab


def build(thaw, wanted, out, work_dir, level_scripts=True, keep_duplicates=False, sandbox=False, unlock_all=True):
    """wanted: [(source disc path, [codes] or None)]. Returns [(display name, zone)] added.
    sandbox: boot straight to the free-skate level list (for shrunk images: the movies' room is used);
    otherwise THAW boots and plays as normal (every file kept, the image grows) and the levels are in free skate.
    unlock_all: every level unlocked in free skate (always on with sandbox)."""
    os.makedirs(work_dir, exist_ok=True)
    thaw_iso = disc_image(thaw, work_dir)
    if not is_thaw(thaw_iso):
        raise ValueError(f"{thaw}: not Tony Hawk's American Wasteland (NTSC-U, {', '.join(THAW_SERIALS)})")
    srcs = []
    for path, codes in wanted:
        s = sources.open_source(disc_image(path, work_dir), os.path.join(work_dir, "cache"))
        avail = dict(getattr(s, "all_levels", s.levels)())
        codes = codes or [c for c, _ in s.levels()]
        bad = [c for c in codes if c not in avail]
        if bad:
            raise ValueError(f"{path}: unknown level(s) {bad}; available: {', '.join(avail)}")
        srcs.append((s, [(c, avail[c]) for c in codes]))
    if not keep_duplicates:  # a level in several games is imported once, from the newest engine
        srcs, skipped = sources.dedupe(srcs)
        for s, code, name, newer in skipped:
            log(f"skipping {s.GAME} {name}: the {newer.GAME} version of this level is included")
    n_new = sum(len(lv) for _, lv in srcs)
    if n_new > MAX_NEW_LEVELS:
        raise ValueError(f"{n_new} levels chosen; at most {MAX_NEW_LEVELS} can be added. Pick levels with DISC:code,code,...")
    if os.path.abspath(out) in (os.path.abspath(thaw_iso), os.path.abspath(thaw)):
        raise ValueError("the output must not be the input disc")
    log("copying THAW and making room ...")
    if sandbox:
        iso_build.build(thaw_iso, out)
    else:
        iso_build.build_keep_all(thaw_iso, out, n_new * ROOM_PER_LEVEL + 16 * 2**20)
    sandbox_patch.apply(out, boot=sandbox, unlock=unlock_all or sandbox)
    elf_patch.apply(out)  # rail tables unpack in place (no main-heap buffer)
    d = Disc(out)
    nt = names_table(d)
    taken = {e.name.lower().split("\\")[3] for e in d.ents if e.name.lower().startswith("\\worlds\\worldzones\\")
             and e.name.count("\\") >= 4}
    template = d.read(f"\\worlds\\worldzones\\{TEMPLATE}\\{TEMPLATE}.pak.ps2")
    ped0 = d.read(f"\\worlds\\worldzones\\{TEMPLATE}\\{TEMPLATE}ped.pak.ps2")
    sfx0 = d.read(f"\\sounds\\pak\\{TEMPLATE}_sfx.pak.ps2")
    if unlock_all or sandbox:
        new_pak, new_pab = level_register.edit_files(d.read("\\pak\\qb.pak.ps2"), d.read("\\pak\\qb.pab.ps2"),
                                                     level_register.UNLOCK_EDITS, tmp_dir=work_dir)
        d.put("\\pak\\qb.pak.ps2", new_pak)
        d.put("\\pak\\qb.pab.ps2", new_pab)
        d.save()
        d = Disc(out)
    added = []
    for s, levels in srcs:
        zones = zone_names([c for c, _ in levels], taken, getattr(s, "ZONE_HINTS", None))
        taken |= set(zones.values())
        for code, display in levels:
            zn = zones[code]
            log(f"{s.GAME} {display}: converting ...")
            if getattr(s, "PREBUILT", False):  # generated level (thaw_sandbox.mapgen)
                files = {}
                zb, st = s.build_zone(code, template, zn, TEMPLATE)
            else:
                files = s.level_files(code)
                zb, st = level_convert.convert_level(template, files, code, zn, s.resolve_texture_refs,
                                                     template=TEMPLATE, level_scripts=level_scripts)
            zb, _ = rename_zone(zb, TEMPLATE, zn, nt)
            ped, _ = rename_zone(ped0, TEMPLATE, zn, nt)
            sfx, _ = rename_zone(sfx0, TEMPLATE, zn, nt)
            d.add(f"\\worlds\\worldzones\\{zn}\\{zn}.pak.ps2", zb)
            d.add(f"\\worlds\\worldzones\\{zn}\\{zn}ped.pak.ps2", ped)
            d.add(f"\\sounds\\pak\\{zn}_sfx.pak.ps2", sfx)
            setup = None
            if level_scripts and files.get("scripts") and getattr(s, "USE_SETUP", True) and \
                    Q.qbcrc(f"{code}_setup") in thug2_qb.parse(files["scripts"]).scripts:
                setup = f"{code}_setup"
            new_pak, new_pab = level_register.register(d.read("\\pak\\qb.pak.ps2"), d.read("\\pak\\qb.pab.ps2"),
                                                       zn, display, len(zb), len(ped), setup, tmp_dir=work_dir)
            d.put("\\pak\\qb.pak.ps2", new_pak)
            d.put("\\pak\\qb.pab.ps2", new_pab)
            d.save()
            d = Disc(out)
            log(f"  added as {zn} ({len(zb) / 2**20:.1f} MB, {st['textures']} textures, {st['leaves']} leaves)")
            added.append((display, zn))
    if added and not (unlock_all or sandbox):
        new_pak, new_pab = level_register.edit_files(d.read("\\pak\\qb.pak.ps2"), d.read("\\pak\\qb.pab.ps2"),
                                                     level_register.open_added_edits([z for _, z in added]),
                                                     tmp_dir=work_dir)
        d.put("\\pak\\qb.pak.ps2", new_pak)
        d.put("\\pak\\qb.pab.ps2", new_pab)
        d.save()
    return added
