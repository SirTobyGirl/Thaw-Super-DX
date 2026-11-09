"""Convert a THUG2 (PS2) .qb file into a THAW .qb file.

Data statements become THAW data records (qb_data encoding); scripts become THAW script records whose
body is the THUG2 token stream, compressed with the game's own LZSS encoder (lzss.pack_body). Both games
share the token set for script code. Storing scripts in any other way (raw when compressible, or as an
all-literal stream) crashed the game in tests; the body header checksum is not checked.
"""
import struct
import zlib

from thaw_sandbox import lzss, qb_data as QD, qb_file as F, thug2_qb as T2
from thaw_sandbox.qb_parser import qbcrc


def _vtype(v) -> int:
    return QD._raw_of(v)


def script_body(code: bytes) -> bytes:
    """Store like the original compiler (lzss.pack_body: real encoder, raw only if not smaller).
    The header checksum is not checked by the game (verified in PCSX2), so crc32 of the code is used."""
    return lzss.pack_body(zlib.crc32(code) & 0xFFFFFFFF, code)


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
