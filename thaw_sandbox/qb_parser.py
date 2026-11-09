"""Parser for THAW compiled QB scripts (.qb.ps2 / .qb.wpc).

What is understood so far (verified on engine_params.qb and classic_mode_menu.qb):

  file   = u32 0 | u32 file_size | type-size table (up to 0x1c) | records / bodies ...
  record = 5 dwords: [type word 00 04 vt 00][name crc][file crc][value][next]
           vt: 0x01 int, 0x05 float, 0x0d name(crc), 0x07 script (value = offset of body),
               0x0c struct/array (value = offset of nested data)
  file crc = CRC of the script's own path (identical in every record of a file), which
             makes record starts easy to resync on.
  body   = byte code. Token 0x16 is followed by a 4 byte name CRC. Other tokens are only
           partly understood (strings carry extra marker bytes), so bodies are kept
           as raw bytes; names inside are resolved for reading and for searching.

Hashing: qbcrc() = ~crc32(lower(path with / -> \\)), checked against the PAK index.
"""
import os
import pickle
import re
import struct
import zlib
from dataclasses import dataclass, field

HEADER_END = 0x1C
VT = {0x01: "int", 0x05: "float", 0x07: "script", 0x0C: "struct", 0x0D: "name"}


def qbcrc(s: str) -> int:
    return (~zlib.crc32(s.lower().replace("/", "\\").encode("latin1"))) & 0xFFFFFFFF


class NameTable:
    """crc -> name. Built from strings found in files; cached as a pickle."""

    def __init__(self, names: dict[int, str] | None = None):
        self.names = names or {}

    def add_file(self, path: str):
        with open(path, "rb") as f:
            data = f.read()
        for m in re.finditer(rb"[\x20-\x7e]{3,200}", data):
            s = m.group().decode("latin1")
            for t in {s} | set(re.split(r"[\\/ .,:;=()\[\]\"'%]+", s)):
                if t and 2 < len(t) < 120:
                    self.names.setdefault(qbcrc(t), t)

    def add_names(self, names):
        for n in names:
            self.names.setdefault(qbcrc(n), n)

    def get(self, crc: int) -> str:
        return self.names.get(crc, f"0x{crc:08x}")

    def save(self, path):
        with open(path, "wb") as f:
            pickle.dump(self.names, f)

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            return cls(pickle.load(f))


@dataclass
class Record:
    pos: int
    vtype: int
    name: int
    value: int
    nxt: int
    body: bytes = b""
    body_pos: int = 0


@dataclass
class QBFile:
    size: int
    file_crc: int
    records: list[Record] = field(default_factory=list)
    data: bytes = b""


def _is_record(d: bytes, q: int, fcrc: int) -> bool:
    return (
        q + 20 <= len(d)
        and d[q] == 0
        and d[q + 1] == 0x04
        and d[q + 3] == 0
        and struct.unpack_from("<I", d, q + 8)[0] == fcrc
    )


def parse(d: bytes) -> QBFile:
    size = struct.unpack_from("<I", d, 4)[0]
    # file crc: dword at +8 of the first record, which starts at 0x1c (type word at 0x1c)
    fcrc = struct.unpack_from("<I", d, HEADER_END + 8)[0]
    qb = QBFile(size, fcrc, data=d)
    # record starts: every 4-aligned position that looks like one
    starts = [q for q in range(HEADER_END, len(d) - 19, 4) if _is_record(d, q, fcrc)]
    for i, q in enumerate(starts):
        vt = d[q + 2]
        name, _, value, nxt = struct.unpack_from("<4I", d, q + 4)
        r = Record(q, vt, name, value, nxt)
        if vt == 0x07 and q + 20 < len(d):  # script: body from value to next record
            end = starts[i + 1] if i + 1 < len(starts) else len(d)
            r.body_pos = value
            r.body = d[value:end]
        qb.records.append(r)
    return qb


def dump(path: str, names: NameTable) -> str:
    qb = parse(open(path, "rb").read())
    out = [f"{os.path.basename(path)}  size={qb.size}  file_crc={qb.file_crc:08x}  records={len(qb.records)}"]
    for r in qb.records:
        n = names.get(r.name)
        t = VT.get(r.vtype, f"vt{r.vtype:02x}")
        if r.vtype == 0x0D:
            out.append(f"  {r.pos:#06x} {t:6} {n} = {names.get(r.value)}")
        elif r.vtype == 0x05:
            out.append(f"  {r.pos:#06x} {t:6} {n} = {struct.unpack('<f', struct.pack('<I', r.value))[0]}")
        elif r.vtype == 0x01:
            out.append(f"  {r.pos:#06x} {t:6} {n} = {r.value}")
        elif r.vtype == 0x07:
            used = [names.get(struct.unpack_from('<I', r.body, i + 1)[0]) for i in range(len(r.body) - 4) if r.body[i] == 0x16]
            out.append(f"  {r.pos:#06x} {t:6} {n}  body@{r.body_pos:#x} len={len(r.body)} names: {[u for u in used if not u.startswith('0x')]}")
        else:
            out.append(f"  {r.pos:#06x} {t:6} {n} value={r.value:#x}")
    return "\n".join(out)
