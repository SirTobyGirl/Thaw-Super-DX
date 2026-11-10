"""The free-skate sandbox boot patches, applied in place to a THAW image (script sizes never change).

Boots straight to the level list with Tony Hawk, all levels unlocked, no intro movies, no attract-mode demo;
Quit returns to the level list. (Same edits as harness/build_sandbox.sh; verified in PCSX2.)
Whole-body script replacement is never used: the game silently did not run replaced bodies, so edits either
swap name hashes inside the compressed code (lzss.patch_code) or overwrite the first bytes (lzss.patch_prefix).
"""
import struct

from thaw_sandbox import lzss, pak, qb_parser as Q, qb_tokens as T
from thaw_sandbox.disc import Disc

PATCHES = [
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
CONTAINERS = [("\\worlds\\worldzones\\z_mainmenu\\z_mainmenu.pak.ps2", None), ("\\pak\\qb.pab.ps2", "\\pak\\qb.pak.ps2")]


def apply(iso):
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
    for script, kind, a, b in [(p + (None,))[:4] for p in PATCHES]:
        ci, bp, bl = where[Q.qbcrc(script)]
        data = conts[ci][1]
        body = bytes(data[bp:bp + bl])
        if kind == "prefix":
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
