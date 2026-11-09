"""Reader/writer for Neversoft HED/WAD archives (THAW PS2: DATAP.HED + DATAP.WAD).

HED layout (see tools/LegacyTHPS/formats/thps3_ps2_hed.ksy), little endian:
    repeat: s32 offset (in 2048-byte sectors), u32 size, strz name, pad to 4
    terminated by offset == -1
The WAD is the entries' data, each starting on a sector boundary.
"""
import os
import struct
from dataclasses import dataclass

SECTOR = 2048


@dataclass
class Entry:
    offset: int  # sectors
    size: int  # bytes
    name: str  # e.g. "\\worlds\\worldzones\\z_oi\\z_oi.pak.ps2"


def parse_hed(data: bytes) -> tuple[list[Entry], bytes]:
    """Return (entries, trailer). trailer is everything after the -1 terminator's 4 bytes."""
    ents, p = [], 0
    while True:
        (off,) = struct.unpack_from("<i", data, p)
        if off == -1:
            return ents, data[p + 4:]
        (size,) = struct.unpack_from("<I", data, p + 4)
        e = data.index(b"\0", p + 8)
        ents.append(Entry(off, size, data[p + 8:e].decode("latin1")))
        p = e + 1
        p += -p % 4


def build_hed(ents: list[Entry], trailer: bytes = b"") -> bytes:
    out = bytearray()
    for e in ents:
        out += struct.pack("<iI", e.offset, e.size) + e.name.encode("latin1") + b"\0"
        out += b"\0" * (-len(out) % 4)
    out += struct.pack("<i", -1) + trailer
    return bytes(out)


def _local(root: str, name: str) -> str:
    return os.path.join(root, *[p for p in name.split("\\") if p])


def unpack(hed_path: str, wad_path: str, out_dir: str) -> list[Entry]:
    with open(hed_path, "rb") as f:
        ents, _ = parse_hed(f.read())
    with open(wad_path, "rb") as w:
        for e in ents:
            dst = _local(out_dir, e.name)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            w.seek(e.offset * SECTOR)
            with open(dst, "wb") as o:
                o.write(w.read(e.size))
    return ents


def repack(hed_path: str, src_dir: str, out_hed: str, out_wad: str) -> list[Entry]:
    """Rebuild HED+WAD from src_dir, keeping the original layout wherever possible.

    The vanilla layout has zero-filled gaps whose rule is unknown, so instead of
    repacking back to back we keep each file at its original offset when it still
    fits its slot (space up to the next file). Files that grew are appended past the
    end of the original WAD. Unchanged input reproduces the original byte for byte.
    """
    with open(hed_path, "rb") as f:
        ents, trailer = parse_hed(f.read())
    by_off = sorted(range(len(ents)), key=lambda i: ents[i].offset)
    slot_end = {}
    for a, b in zip(by_off, by_off[1:]):
        slot_end[a] = ents[b].offset
    last = by_off[-1]
    orig_end = ents[last].offset + -(-ents[last].size // SECTOR)
    slot_end[last] = orig_end
    end = orig_end  # next free sector for relocated files
    with open(out_wad, "wb") as w:
        for i in by_off:
            e = ents[i]
            with open(_local(src_dir, e.name), "rb") as f:
                data = f.read()
            need = -(-len(data) // SECTOR)
            if e.offset + need > slot_end[i]:
                e.offset, end = end, end + need
            w.seek(e.offset * SECTOR)
            w.write(data)
            w.write(b"\0" * (need * SECTOR - len(data)))
            e.size = len(data)
        w.truncate(max(end, orig_end) * SECTOR)
    with open(out_hed, "wb") as f:
        f.write(build_hed(ents, trailer))
    return ents
