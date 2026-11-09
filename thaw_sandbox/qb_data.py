"""Decoder for THAW QB *data* (records of type struct/array/int/... as opposed to scripts).

Layout (all pointers are offsets from the start of the .qb file):
  record value -> for arrays:  [00 01 ET 00][u32 count][u32 ptr] ...  ET = raw element type
                  for structs: [00 00 01 00][u32 ptr to first component]
  component (16 bytes): [00 TT 00 00][u32 name crc (0 = unnamed flag)][u32 value or ptr][u32 next or 0]
      TT = (raw type << 1) | 1, i.e. 0x03 int, 0x05 float, 0x07 string, 0x0d vector, 0x0b pair,
      0x15 struct, 0x19 array, 0x1b name (checksum)
  vector data: [00 01 00 00] f32 x3      pair data: [00 01 00 00] f32 x2     string: bytes + NUL (4-aligned)
  array: element values follow the header; for arrays of structs/arrays/vectors/strings the ptr points to
         a table of per-element pointers (count == 1 may point straight at the element; see decode).
Raw types: 1 int, 2 float, 3 string, 4 local string, 5 pair, 6 vector, 7 script, 10 struct, 12 array,
13 name.
"""
import struct
from dataclasses import dataclass, field

RAW = {1: "int", 2: "float", 3: "string", 4: "lstring", 5: "pair", 6: "vector", 7: "script",
       10: "struct", 12: "array", 13: "name"}


class LStr(str):
    """A localised string (raw type 4); kept distinct so it re-encodes as type 4, not 3."""


@dataclass
class Name:
    crc: int


@dataclass
class Struct:
    items: list = field(default_factory=list)  # [(name_crc or 0, value)]


@dataclass
class Array:
    etype: int
    items: list = field(default_factory=list)


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _string(b, o):
    return b[o:b.index(b"\0", o)].decode("latin1")


def _scalar(b, raw, v):
    """Decode a value stored directly in a 4 byte slot, or behind a pointer for vector/pair/string."""
    if raw == 1:
        return struct.unpack("<i", struct.pack("<I", v))[0]
    if raw == 2:
        return struct.unpack("<f", struct.pack("<I", v))[0]
    if raw == 13:
        return Name(v)
    if raw == 3:
        return _string(b, v)
    if raw == 4:
        return LStr(_string(b, v))
    if raw == 6:
        assert u32(b, v) == 0x100, f"vector header at {v:#x}"
        return struct.unpack_from("<3f", b, v + 4)
    if raw == 5:
        assert u32(b, v) == 0x100, f"pair header at {v:#x}"
        return struct.unpack_from("<2f", b, v + 4)
    if raw == 10:
        return decode_struct(b, v)
    if raw == 12:
        return decode_array(b, v)
    raise ValueError(f"raw type {raw}")


def decode_struct(b: bytes, o: int) -> Struct:
    assert u32(b, o) == 0x10000, f"struct header {u32(b, o):#x} at {o:#x}"
    s = Struct()
    p = u32(b, o + 4)
    while p:
        tw, name, val, nxt = struct.unpack_from("<4I", b, p)
        tt = (tw >> 8) & 0xFF
        assert tw & 0xFFFF00FF == 0 and tt & 1, f"component word {tw:#x} at {p:#x}"
        s.items.append((name, _scalar(b, tt >> 1, val)))
        p = nxt
    return s


def decode_array(b: bytes, o: int) -> Array:
    tw = u32(b, o)
    assert tw & 0xFF00FFFF == 0x100, f"array header {tw:#x} at {o:#x}"
    et = (tw >> 16) & 0xFF
    n = u32(b, o + 4)
    a = Array(et)
    if n == 0:
        return a
    p = u32(b, o + 8)
    if et in (1, 2, 13):  # values inline (count 1: the value itself sits in the ptr slot)
        vals = [p] if n == 1 else [u32(b, p + 4 * i) for i in range(n)]
        a.items = [_scalar(b, et, v) for v in vals]
    else:  # pointers to elements
        ptrs = [p] if n == 1 else [u32(b, p + 4 * i) for i in range(n)]
        a.items = [_scalar(b, et, q) for q in ptrs]
    return a


def decode_record_value(b: bytes, vtype: int, value: int):
    return _scalar(b, vtype, value)


# ---------------------------------------------------------------- encoder
def _raw_of(v) -> int:
    if isinstance(v, bool) or isinstance(v, int):
        return 1
    if isinstance(v, float):
        return 2
    if isinstance(v, LStr):
        return 4
    if isinstance(v, str):
        return 3
    if isinstance(v, Name):
        return 13
    if isinstance(v, Struct):
        return 10
    if isinstance(v, Array):
        return 12
    if isinstance(v, tuple):
        return 6 if len(v) == 3 else 5
    raise TypeError(type(v))


class _Writer:
    def __init__(self, base: int):
        self.base = base
        self.buf = bytearray()

    def here(self):
        return self.base + len(self.buf)

    def put(self, b: bytes):
        self.buf += b

    def patch(self, at: int, v: int):
        struct.pack_into("<I", self.buf, at - self.base, v)


def _inline(raw, v) -> int:
    if raw == 1:
        return v & 0xFFFFFFFF
    if raw == 2:
        return struct.unpack("<I", struct.pack("<f", v))[0]
    if raw == 13:
        return v.crc
    raise ValueError


def _out_of_line(w: _Writer, raw, v):
    """Write the data a pointer refers to; returns its offset."""
    at = w.here()
    if raw in (3, 4):
        b = v.encode("latin1") + b"\0"
        w.put(b + b"\0" * (-len(b) % 4))
    elif raw == 6:
        w.put(struct.pack("<I3f", 0x100, *v))
    elif raw == 5:
        w.put(struct.pack("<I2f", 0x100, *v))
    elif raw == 10:
        _struct(w, v)
    elif raw == 12:
        _array(w, v)
    else:
        raise ValueError(raw)
    return at


def _struct(w: _Writer, s: Struct):
    start = w.here()
    w.put(struct.pack("<2I", 0x10000, 0))
    prev_next = start + 4  # where to store the pointer to the next component
    for name, v in s.items:
        raw = _raw_of(v)
        comp = w.here()
        w.patch(prev_next, comp)
        w.put(struct.pack("<4I", ((raw << 1 | 1) << 8), name, 0, 0))
        if raw in (1, 2, 13):
            w.patch(comp + 8, _inline(raw, v))
        else:
            w.patch(comp + 8, _out_of_line(w, raw, v))
        prev_next = comp + 12
    if not s.items:
        w.patch(start + 4, 0)


def _array(w: _Writer, a: Array):
    start = w.here()
    n = len(a.items)
    w.put(struct.pack("<3I", 0x100 | (a.etype << 16), n, 0))
    if n == 0:
        return
    if a.etype in (1, 2, 13):
        if n == 1:
            w.patch(start + 8, _inline(a.etype, a.items[0]))
        else:
            w.patch(start + 8, w.here())
            w.put(b"".join(struct.pack("<I", _inline(a.etype, x)) for x in a.items))
        return
    if n == 1:
        w.patch(start + 8, _out_of_line(w, a.etype, a.items[0]))
        return
    table = w.here()
    w.patch(start + 8, table)
    w.put(b"\0" * (4 * n))
    if a.etype in (3, 4):  # strings in an array are packed back to back, padded once at the end
        for i, x in enumerate(a.items):
            w.patch(table + 4 * i, w.here())
            w.put(x.encode("latin1") + b"\0")
        w.put(b"\0" * (-len(w.buf) % 4))
        return
    for i, x in enumerate(a.items):
        w.patch(table + 4 * i, _out_of_line(w, a.etype, x))


def encode_value(v, base: int) -> bytes:
    """Encode a struct/array/vector/... value as it would sit at file offset `base`."""
    w = _Writer(base)
    _out_of_line(w, _raw_of(v), v)
    return bytes(w.buf)
