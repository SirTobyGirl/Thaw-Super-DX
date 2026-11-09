"""Convert a THUG2 (PS2) .qb file into a THAW .qb file.

Data statements become THAW data records (qb_data encoding); scripts become THAW script records whose
body is the THUG2 token stream stored uncompressed (header A == B). Both games share the token set for
script code. The 4-byte body header checksum's formula is unknown; converted scripts get crc32 of their
code, which is unique per body.
"""
import struct
import zlib

from thaw_sandbox import qb_data as QD, qb_file as F, thug2_qb as T2
from thaw_sandbox.qb_parser import qbcrc


def _vtype(v) -> int:
    return QD._raw_of(v)


def script_body(code: bytes) -> bytes:
    crc = zlib.crc32(code) & 0xFFFFFFFF
    return struct.pack("<3I", crc, len(code), len(code)) + code


def convert(thug2_bytes: bytes, thaw_path: str) -> tuple[bytes, T2.QbFile]:
    src = T2.parse(thug2_bytes)
    items = []
    for kind, crc in src.order:
        if kind == "data":
            v = src.data[crc]
            items.append(F.Item(_vtype(v), crc, v))
        else:
            items.append(F.Item(7, crc, script_body(src.scripts[crc])))
    return F.write(qbcrc(thaw_path), items), src
