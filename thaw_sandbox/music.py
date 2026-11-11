"""Mega merge, music: add the soundtracks of the user's other Tony Hawk discs to THAW's playlist.

THAW plays songs from /MUSIC/MUSICP.WAD (index MUSICP.HED + lookup tables MUSICPD.HDP / MUSICPF.HDP, same rules
as DATAP's: see disc.py) listed in scripts\\game\\sfx\\music.qb playlist_tracks {artist, title, genre, path}.
All four games store songs the same way (headerless PS2 ADPCM streams), THUG2 and THUG list theirs in the same
playlist_tracks form, THPS4 in a script of (path, "Artist: Title") pairs.

merge(iso, discs) writes a new MUSICP.WAD (THAW's songs + the new ones) and new index files at the end of the
image (the old copies are left as dead space; shrinking packs them away), points the ISO9660 records at them and
appends the tracks to the playlist. THAW's HED offsets are sector numbers with 0x0F in the top byte.
"""
import re
import struct

from thaw_sandbox import iso_manager as I, level_register as LR, qb_data as QD, wad
from thaw_sandbox.qb_parser import qbcrc as H

SECTOR = 2048
ALIGN = 0x10000                 # THAW's songs start on 64 KB boundaries
FLAG = 0x0F000000
K_ARTIST, K_TITLE, K_GENRE, K_PATH = 3072351508, 2755536179, 2091895815, 4104877296
GENRES = {"PUNK": 0, "HIP HOP": 1, "ROCK/OTHER": 2}
SOURCES = {  # serial -> (music HED, WAD, playlist script, kind)
    "SLUS_209.65": ("/MUSIC/MUSICP.HED;1", "/MUSIC/MUSICP.WAD;1", "\\scripts\\game\\skater\\skater_sfx.qb", "playlist"),
    "SLUS_207.31": ("/MUSIC/MUSIC.HED;1", "/MUSIC/MUSIC.WAD;1", "\\scripts\\game\\skater\\skater_sfx.qb", "playlist"),
    "SLUS_205.04": ("/MUSIC/MUSIC.HED;1", "/MUSIC/MUSIC.WAD;1", "\\scripts\\skater_sfx.qb", "pairs"),
}
GAME = {"SLUS_209.65": "THUG2", "SLUS_207.31": "THUG", "SLUS_205.04": "THPS4"}


def _serial(iso):
    cnf = I.read_file(iso, "/SYSTEM.CNF;1")
    return next((s for s in SOURCES if s.encode() in cnf), None)


def tracks(iso, source):
    """[(artist, title, genre name, (wad offset, size))] of a source disc's soundtrack."""
    serial = _serial(iso)
    if serial is None:
        return []
    hed_p, wad_p, script, kind = SOURCES[serial]
    ents, _ = wad.parse_hed(I.read_file(iso, hed_p))
    by = {e.name.lower().lstrip("\\"): e for e in ents}
    woff, _ = I.file_extent(iso, wad_p)
    b = source.read(script)
    out = []
    if kind == "playlist":
        from thaw_sandbox import thug2_qb
        q = thug2_qb.parse(b)
        genres = q.data.get(H("playlist_genres"))
        gnames = list(genres.items) if isinstance(genres, QD.Array) else list(GENRES)
        for it in q.data[H("playlist_tracks")].items:
            d = dict(it.items)
            e = by.get(str(d.get(K_PATH, "")).lower())
            if e is None:
                continue
            g = d.get(K_GENRE, 2)
            gname = gnames[g] if isinstance(g, int) and 0 <= g < len(gnames) else "ROCK/OTHER"
            out.append((d.get(K_ARTIST, ""), d.get(K_TITLE, ""), str(gname).upper(), (woff + e.offset, e.size)))
    else:  # THPS4: ... 'music\\name' ... 'Artist: Title' ...
        strs = [m.group(1).decode("latin1") for m in re.finditer(rb"\x1b.\x00\x00\x00([^\x00]+)\x00", b)]
        seen = set()
        for i, s in enumerate(strs[:-1]):
            e = by.get(s.lower())
            if e is None or ":" not in strs[i + 1] or s.lower() in seen:
                continue
            seen.add(s.lower())
            artist, title = (x.strip() for x in strs[i + 1].split(":", 1))
            out.append((artist, title, "ROCK/OTHER", (woff + e.offset, e.size)))
    return out


def _hdpd(ents):
    """MUSICPD.HDP from the HED (same layout as DATAPD.HDP)."""
    import collections
    order, groups = [], collections.defaultdict(list)
    for e in ents:
        p = e.name.lstrip("\\")
        d = p.rsplit("\\", 1)[0].lower() if "\\" in p else ""
        if d not in groups:
            order.append(d)
        groups[d].append(e)
    ftab = 16 + 12 * (len(order) + 1)
    out = bytearray(struct.pack("<4I", len(ents), ftab, 16, 0))
    recs = bytearray()
    for d in order:
        out += struct.pack("<3I", len(groups[d]), 0xFFFFFFFF if d == "" else H(d), ftab + len(recs))
        for e in groups[d]:
            recs += struct.pack("<3I", e.offset, e.size, H(e.name.rsplit("\\", 1)[-1]))
    return bytes(out + struct.pack("<3I", 0xFFFFFFFF, 0, 0) + recs)


def _hdpf(ents):
    recs = sorted(((e.offset, e.size, H(e.name.rsplit("\\", 1)[-1])) for e in ents), key=lambda r: r[2])
    return struct.pack("<4I", len(recs), 16, 0, 0) + b"".join(struct.pack("<3I", *r) for r in recs)


def merge(iso, discs, log=print, max_bytes=None):
    """Add the soundtracks of discs [(iso path, source adapter)] to the THAW image iso. Returns tracks added.
    max_bytes: stop adding songs past this many bytes of new music (image size limits)."""
    from thaw_sandbox.disc import Disc
    from thaw_sandbox.iso_build import _all_files, _set_both
    ents, trailer = wad.parse_hed(I.read_file(iso, "/MUSIC/MUSICP.HED;1"))
    trailer = trailer.rstrip(b"\0")
    woff, wlen = I.file_extent(iso, "/MUSIC/MUSICP.WAD;1")
    d = Disc(iso)
    music_qb = None
    # THAW's playlist (to skip songs it already has)
    from thaw_sandbox import pak, qb_file as F
    idx, pab = d.read("\\pak\\qb.pak.ps2"), d.read("\\pak\\qb.pab.ps2")
    for e in pak.parse_pak(idx):
        if e.name.endswith("music.qb.ps2"):
            p = pak.data_pos(e, len(idx))
            _, items = F.read(pab[p:p + e.size])
            music_qb = items
    have = set()
    for it in next(i for i in music_qb if i.name == H("playlist_tracks")).value.items:
        dd = dict(it.items)
        have.add((str(dd.get(K_ARTIST, "")).lower(), str(dd.get(K_TITLE, "")).lower()))
    new, used = [], 0
    for path, src in discs:
        serial = _serial(path)
        for artist, title, genre, (off, size) in tracks(path, src):
            key = (artist.lower(), title.lower())
            if key in have:
                continue
            if max_bytes is not None and used + size > max_bytes:
                log(f"music: no more room, stopping at {len(new)} added songs")
                break
            have.add(key)
            new.append((artist, title, genre, path, off, size, GAME.get(serial, "X")))
            used += size + ALIGN
    if not new:
        return 0
    log(f"music: adding {len(new)} songs ({used / 2**20:.0f} MB) ...")
    # new WAD at the end of the image: THAW's WAD as is, then the new songs, 64 KB aligned
    with open(iso, "r+b") as f:
        f.seek(0, 2)
        end = f.tell()
        start = -(-end // ALIGN) * ALIGN
        pos = start

        def copy(src_iso, src_off, n, dst):
            with open(src_iso, "rb") as s:
                s.seek(src_off)
                f.seek(dst)
                left = n
                while left:
                    k = min(left, 16 * 2**20)
                    f.write(s.read(k))
                    left -= k
        copy(iso, woff, wlen, pos)
        cur = -(-wlen // ALIGN) * ALIGN
        for k, (artist, title, genre, path, off, size, game) in enumerate(new):
            name = f"\\Music\\vag\\songs\\sdx_{game.lower()}_{k:03d}"
            copy(path, off, size, start + cur)
            ents.append(wad.Entry(FLAG | (cur // SECTOR), size, name))
            cur += -(-size // ALIGN) * ALIGN
        wad_len = cur
        hed = wad.build_hed(ents, trailer)
        tail = start + wad_len
        files = {"/MUSIC/MUSICP.WAD;1": (start, wad_len)}
        for nm, data in (("/MUSIC/MUSICP.HED;1", hed), ("/MUSIC/MUSICPD.HDP;1", _hdpd(ents)),
                         ("/MUSIC/MUSICPF.HDP;1", _hdpf(ents))):
            f.seek(tail)
            f.write(data + bytes(-len(data) % SECTOR))
            files[nm] = (tail, len(data))
            tail += -(-len(data) // SECTOR) * SECTOR
        recs = {p: (o, lba, s) for o, lba, s, p in _all_files(f)}
        for nm, (pos_, n) in files.items():
            o = recs[nm][0]
            _set_both(f, o + 2, pos_ // SECTOR)
            _set_both(f, o + 10, n)
        total = tail // SECTOR + 1  # + the closing UDF anchor
        f.truncate(total * SECTOR)
        f.seek(16 * SECTOR + 80)
        f.write(struct.pack("<I", total) + struct.pack(">I", total))
        from thaw_sandbox.iso_compact import sync_udf
        sync_udf(f, total)
    # playlist entries
    def edit(items):
        arr = next(i for i in items if i.name == H("playlist_tracks")).value
        for k, (artist, title, genre, path, off, size, game) in enumerate(new):
            arr.items.append(QD.Struct([(K_ARTIST, artist), (K_TITLE, title), (K_GENRE, GENRES.get(genre, 2)),
                                        (K_PATH, f"music\\vag\\songs\\sdx_{game.lower()}_{k:03d}")]))
    d = Disc(iso)
    new_pak, new_pab = LR.edit_files(d.read("\\pak\\qb.pak.ps2"), d.read("\\pak\\qb.pab.ps2"),
                                     (("music.qb.ps2", edit),))
    d.put("\\pak\\qb.pak.ps2", new_pak)
    d.put("\\pak\\qb.pab.ps2", new_pab)
    d.save()
    return len(new)
