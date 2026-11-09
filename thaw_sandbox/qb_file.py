"""Read and write whole THAW .qb files (header, records, data values, script bodies).

file    = u32 0 | u32 file size | 20 constant bytes (type size table) | records ...
record  = [00 04 vt 00][name crc][file crc][value][0]  (20 bytes), followed by its out-of-line data:
          vt 1 int / 2 float / 13 name: value inline, nothing follows
          vt 3 string, 10 struct, 12 array, ...: value = offset of the data that follows (qb_data)
          vt 7 script: value = offset of the body that follows ([crc][A][B][stream], padded to 4)
"""
import struct
from dataclasses import dataclass

from thaw_sandbox import qb_data as QD
from thaw_sandbox.qb_parser import parse as parse_records

HEADER_TABLE = bytes.fromhex("1c0802041004080c0c0802041402040c10100c00")
INLINE = (1, 2, 13)


@dataclass
class Item:
    vtype: int
    name: int
    value: object  # decoded data (qb_data objects / int / float / Name) or raw script body bytes


def read(b: bytes) -> tuple[int, list[Item]]:
    """Return (file crc, items)."""
    q = parse_records(b)
    items = []
    for r in q.records:
        if r.vtype == 7:
            crc, a, s = struct.unpack_from("<3I", b, r.value)
            body = b[r.value:r.value + 12 + s]
            items.append(Item(7, r.name, body))
        elif r.vtype in INLINE:
            items.append(Item(r.vtype, r.name, QD.decode_record_value(b, r.vtype, r.value)))
        else:
            items.append(Item(r.vtype, r.name, QD.decode_record_value(b, r.vtype, r.value)))
    return q.file_crc, items


def write(file_crc: int, items: list[Item]) -> bytes:
    out = bytearray(b"\0" * 8 + HEADER_TABLE)
    for it in items:
        pos = len(out)
        if it.vtype in INLINE:
            v = QD._inline(it.vtype, it.value)
            out += struct.pack("<5I", (it.vtype << 16) | 0x400, it.name, file_crc, v, 0)
            continue
        out += struct.pack("<5I", (it.vtype << 16) | 0x400, it.name, file_crc, pos + 20, 0)
        if it.vtype == 7:
            body = bytes(it.value)
            out += body + b"\0" * (-len(body) % 4)
        else:
            out += QD.encode_value(it.value, pos + 20)
    struct.pack_into("<I", out, 4, len(out))
    return bytes(out)
