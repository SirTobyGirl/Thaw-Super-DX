"""Rebuild THAW zone PAKs (worlds/worldzones/z_xx/z_xx.pak.ps2: table + inline data, base 0).

Entries keep their table records (type hash, name hashes, flags, optional path); only data offsets and
sizes change. Data is laid out in the original order. Each entry's data starts at the next 16-byte
boundary, except that the original gap before each entry is reproduced when the data before it is
unchanged in size, so an unmodified zone rebuilds byte for byte.
"""
import struct

from thaw_sandbox import pak


def entries(zone: bytes):
    pe = pak.parse_pak(zone)
    first = pe[0].offset
    return [e for e in pe if e.pos < first]


def rebuild(zone: bytes, replace: dict[int, bytes]) -> bytes:
    """replace: entry table position (e.pos) -> new data bytes."""
    tab = entries(zone)
    real = [e for e in tab if e.size < 0x40000000]          # skip the 0xcdcd... filler record
    order = sorted(real, key=lambda e: pak.data_pos(e, 0))
    out = bytearray(zone[:pak.data_pos(order[0], 0)])     # table (+ padding up to the first data)
    prev_end_orig = pak.data_pos(order[0], 0)
    for e in order:
        dp_orig = pak.data_pos(e, 0)
        gap = dp_orig - prev_end_orig                       # original padding before this entry
        data = replace.get(e.pos, zone[dp_orig:dp_orig + e.size])
        if len(out) % 16 or gap >= 16 or gap < 0:
            pad = (-len(out)) % 16 if gap < 16 else gap
        else:
            pad = gap
        out += b"\xcd" * pad  # the original tools fill padding with 0xCD
        new_pos = len(out)
        out += data
        struct.pack_into("<2I", out, e.pos + 4, new_pos - e.pos, len(data))
        prev_end_orig = dp_orig + e.size
    tail = zone[prev_end_orig:]                             # bytes after the last data (padding)
    out += tail
    return bytes(out)
