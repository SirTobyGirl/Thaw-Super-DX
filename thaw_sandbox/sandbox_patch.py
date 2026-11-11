"""Script patches, applied in place to a THAW image (script sizes never change).

BOOT_PATCHES (shrunk images): boot straight to the free-skate level list with Tony Hawk, all levels unlocked, no
intro movies, no attract-mode demo; Quit returns to the level list. (Verified in PCSX2.)
UNLOCK_PATCHES: every level is unlocked in free skate: in IsLevelUnlocked's free-skate case (GetFlag LEVEL_VISITED)
the fastif's false jump lands on its own "return {unlocked = 1}"; story and classic progression are untouched.
Whole-body script replacement is never used: the game silently did not run replaced bodies, so edits either
swap name hashes inside the compressed code (lzss.patch_code) or overwrite the first bytes (lzss.patch_prefix).
"""
import struct

from thaw_sandbox import lzss, pak, qb_parser as Q, qb_tokens as T
from thaw_sandbox.disc import Disc

BOOT_PATCHES = [
    # the main menu's idle timer spawns NullScript instead of the attract-mode demo
    ("create_main_menu", "swap", "attract_mode_timer", "NullScript"),
    # the startup movie condition is false on PS2: ATVI logo and intro movie are skipped
    ("startup_loading_screen", "swap", 0xBA297025, "IsNGC"),
    # an Xbox-only script hosts our boot code: unlock all levels, load Tony Hawk, Free Skate, level list
    ("create_xbox_online_menu", "prefix",
     "cheat_reallygivelevels\nload_pro_skater name = hawk\nchange_gamemode_singlesession\nlaunch_level_select_menu"),
    # the main menu builder just runs that host
    ("create_base_main_menu", "prefix", "create_xbox_online_menu"),
    # pause/end-run QUIT goes back to the level list instead of the old main menu
    ("menu_confirm_quit", "prefix", "launch_level_select_menu"),
]
UNLOCK_PATCHES = [
    # career: LEVEL_UNLOCKED_STORY, classic: LEVEL_UNLOCKED_CLASSIC, default (free skate): LEVEL_VISITED - the last
    ("IsLevelUnlocked", "last_if_true"),
]
PATCHES = BOOT_PATCHES + UNLOCK_PATCHES
CONTAINERS = [("\\worlds\\worldzones\\z_mainmenu\\z_mainmenu.pak.ps2", None), ("\\pak\\qb.pab.ps2", "\\pak\\qb.pak.ps2")]


def apply(iso, boot=True, unlock=True):
    patches = (BOOT_PATCHES if boot else []) + (UNLOCK_PATCHES if unlock else [])
    if not patches:
        return
    d = Disc(iso)
    conts = []
    where = {}  # script name crc -> (container index, body position, body length)
    for ci, (name, index) in enumerate(CONTAINERS):
        data = bytearray(d.read(name))
        if index is None:
            ents, base = pak.parse_pak(bytes(data)), 0
        else:
            idx = d.read(index)
            ents, base = pak.parse_pak(idx), len(idx)
        conts.append([name, data, bytes(data)])
        for e in ents:
            if not e.name.endswith(".qb.ps2"):
                continue
            pos = pak.data_pos(e, base)
            qb = bytes(data[pos:pos + e.size])
            if len(qb) < 0x40:
                continue
            for r in Q.parse(qb).records:
                if r.vtype == 7:
                    where.setdefault(r.name, (ci, pos + r.body_pos, len(r.body)))
    for script, kind, a, b in [(p + (None, None))[:4] for p in patches]:
        ci, bp, bl = where[Q.qbcrc(script)]
        data = conts[ci][1]
        body = bytes(data[bp:bp + bl])
        if kind == "last_if_true":  # the last fastif jumps to the line after its condition when false
            code = bytearray(lzss.unpack_body(body)[1])
            toks = T.tokenize(bytes(code))
            k = max(i for i, t in enumerate(toks) if t.id == 0x47)
            nl = next(t for t in toks[k + 1:] if t.id == 1)
            struct.pack_into("<h", code, toks[k].off + 1, nl.off - (toks[k].off + 1))
            data[bp:bp + bl] = lzss.patch_code(body, bytes(code))
        elif kind == "prefix":
            data[bp:bp + bl] = lzss.patch_prefix(body, T.assemble(a, Q.qbcrc))
        else:
            code = lzss.unpack_body(body)[1]
            o = struct.pack("<I", a if isinstance(a, int) else Q.qbcrc(a))
            n = struct.pack("<I", Q.qbcrc(b))
            assert o in code, f"{a} not found in {script}"
            data[bp:bp + bl] = lzss.patch_code(body, code.replace(o, n))
    for name, data, orig in conts:
        if bytes(data) != orig:
            assert len(data) == len(orig)
            d.put(name, bytes(data))
    d.save()
