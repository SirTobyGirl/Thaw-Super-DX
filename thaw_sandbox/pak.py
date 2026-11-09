"""Reader/writer for THAW PAK/PAB pairs (e.g. pak/qb.pak.ps2 + pak/qb.pab.ps2).

The .pak is an index of entries, the .pab holds the data. Entry layout (little endian):
    u32 type | u32 offset | u32 size | u32 crc | 4*u32 more hashes/zeros... (32 bytes)
    if flags (u32 at +0x1c) & 0x20: 160-byte NUL-padded path follows (entry is 192 bytes)
The last entry is an unnamed marker whose data lies past the end of the .pab.
Entry offsets are relative to the entry's own position in a combined address space (the
.pak first, then the .pab), so the data position inside the .pab is
    offset - len(pak) + entry.pos
Unchanged input reproduces both files byte for byte.
"""
import os
import struct
from dataclasses import dataclass

HDR = 32
NAME = 160
FLAG_NAME = 0x20


@dataclass
class PakEntry:
    pos: int  # byte position of this entry's header in the .pak
    offset: int
    size: int
    flags: int
    name: str  # "" for the marker entry


def parse_pak(pak: bytes) -> list[PakEntry]:
    ents, p = [], 0
    while p + HDR <= len(pak):
        _, off, size = struct.unpack_from("<3I", pak, p)
        (flags,) = struct.unpack_from("<I", pak, p + 0x1C)
        name, ln = "", HDR
        if flags & FLAG_NAME:
            name = pak[p + HDR:p + HDR + NAME].split(b"\0")[0].decode("latin1")
            ln = HDR + NAME
        ents.append(PakEntry(p, off, size, flags, name))
        p += ln
    return ents


def data_pos(e: "PakEntry", pak_len: int) -> int:
    """Position of the entry's data inside the .pab."""
    return e.offset - pak_len + e.pos


def _local(root: str, name: str) -> str:
    return os.path.join(root, *[s for s in name.split("\\") if s])


def unpack(pak_path: str, pab_path: str, out_dir: str) -> list[PakEntry]:
    with open(pak_path, "rb") as f:
        pk = f.read()
    ents = parse_pak(pk)
    base = len(pk)
    with open(pab_path, "rb") as f:
        pab = f.read()
    seen = set()
    for e in ents:
        if not e.name:
            continue
        assert e.name not in seen, f"duplicate entry {e.name}"
        seen.add(e.name)
        dst = _local(out_dir, e.name)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as o:
            o.write(pab[data_pos(e, base):data_pos(e, base) + e.size])
    return ents


def repack(pak_path: str, pab_path: str, src_dir: str, out_pak: str, out_pab: str) -> list[PakEntry]:
    """Apply src_dir's files on top of the original .pab, updating the .pak index.

    A file that still fits its slot (space up to the next entry's data) is written in
    place; one that grew is appended to the end of the .pab, 16-byte aligned.
    """
    with open(pak_path, "rb") as f:
        pak = bytearray(f.read())
    with open(pab_path, "rb") as f:
        pab = bytearray(f.read())
    ents = parse_pak(bytes(pak))
    base = len(pak)
    orig = bytes(pab)  # compare against this, never the growing buffer
    orig_len = len(orig)
    offsets = sorted({data_pos(e, base) for e in ents if e.name})
    for e in ents:
        if not e.name:
            continue
        with open(_local(src_dir, e.name), "rb") as f:
            data = f.read()
        if data == orig[data_pos(e, base):data_pos(e, base) + e.size]:
            continue  # unchanged
        pos = data_pos(e, base)
        nxt = next((o for o in offsets if o > pos), orig_len)
        if pos + len(data) <= nxt:
            pab[pos:pos + len(data)] = data
            pab[pos + len(data):pos + e.size] = b"\0" * max(0, e.size - len(data))
        else:
            pab += b"\0" * (-len(pab) % 16)
            e.offset = base + len(pab) - e.pos
            pab += data
        e.size = len(data)
        struct.pack_into("<2I", pak, e.pos + 4, e.offset, e.size)
    with open(out_pak, "wb") as f:
        f.write(pak)
    with open(out_pab, "wb") as f:
        f.write(pab)
    return ents
