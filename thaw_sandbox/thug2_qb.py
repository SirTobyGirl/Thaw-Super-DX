"""Parser for THUG2 (PS2) .qb files: a plain token stream (no record table, no compression).

Top level statements:
    name = value            data (value: int, float, string, name, vector, pair, struct {..}, array [..])
    script name ... endscript
and a trailing table of 0x2b ChecksumName tokens (crc + NUL terminated name) for debugging.
Values are returned as thaw_sandbox.qb_data objects so they can be re-encoded in THAW's format.
"""
import struct
from dataclasses import dataclass, field

from thaw_sandbox.qb_data import Array, Name, Struct
from thaw_sandbox.qb_tokens import tokenize

# raw element types used by THAW arrays
_ETYPE = {int: 1, float: 2, str: 3, Name: 13, Struct: 10, Array: 12}


@dataclass
class QbFile:
    data: dict = field(default_factory=dict)      # name crc -> value
    order: list = field(default_factory=list)     # (kind, name crc) in file order; kind = "data" / "script"
    scripts: dict = field(default_factory=dict)   # name crc -> raw token bytes of the body (after the name)
    names: dict = field(default_factory=dict)     # crc -> string from the 0x2b table


class _P:
    def __init__(self, code: bytes):
        self.c = code
        self.t = tokenize(code)
        self.i = 0

    def peek(self):
        while self.i < len(self.t) and self.t[self.i].id in (1, 2):  # skip EOL / EOL+line number
            self.i += 1
        return self.t[self.i] if self.i < len(self.t) else None

    def next(self):
        tk = self.peek()
        self.i += 1
        return tk

    def u32(self, tk):
        return struct.unpack_from("<I", self.c, tk.off + 1)[0]

    def value(self):
        tk = self.next()
        t = tk.id
        if t == 22:
            return Name(self.u32(tk))
        if t == 23:
            return struct.unpack_from("<i", self.c, tk.off + 1)[0]
        if t == 26:
            return struct.unpack_from("<f", self.c, tk.off + 1)[0]
        if t in (27, 28):
            n = self.u32(tk)
            return self.c[tk.off + 5:tk.off + 5 + n].rstrip(b"\0").decode("latin1")
        if t == 30:
            return struct.unpack_from("<3f", self.c, tk.off + 1)
        if t == 31:
            return struct.unpack_from("<2f", self.c, tk.off + 1)
        if t == 10:  # unary minus before a number
            v = self.value()
            return -v
        if t == 3:
            return self.struct_body()
        if t == 5:
            return self.array_body()
        raise ValueError(f"unexpected token {t:#x} at {tk.off}")

    def struct_body(self):
        s = Struct()
        while True:
            tk = self.peek()
            if tk.id == 4:
                self.next()
                return s
            if tk.id == 22:
                self.next()
                nt = self.peek()
                if nt is not None and nt.id == 7:  # name = value
                    self.next()
                    s.items.append((self.u32(tk), self.value()))
                elif nt is not None and nt.id == 3:  # name { ... } (no '='; seen in Training's tr.qb)
                    s.items.append((self.u32(tk), self.value()))
                else:  # bare name = flag
                    s.items.append((0, Name(self.u32(tk))))
                continue
            if tk.id in (3, 5, 10, 23, 26, 27, 28, 30, 31):
                # bare value inside a struct (Training's breakable objects hold script-like lines such as
                # "Wait 10 seconds" in a Shatter { } block): keep it as an unnamed item
                s.items.append((0, self.value()))
                continue
            raise ValueError(f"unexpected token {tk.id:#x} in struct at {tk.off}")

    def array_body(self):
        items = []
        while True:
            tk = self.peek()
            if tk.id == 6:
                self.next()
                break
            if tk.id == 9:  # comma
                self.next()
                continue
            items.append(self.value())
        et = _ETYPE.get(type(items[0]), 6 if items and isinstance(items[0], tuple) and len(items[0]) == 3 else 5) \
            if items else 1
        return Array(et, items)


def parse(code: bytes) -> QbFile:
    f = QbFile()
    p = _P(code)
    while True:
        tk = p.peek()
        if tk is None or tk.id == 0:
            break
        if tk.id == 43:  # checksum name table entry
            p.next()
            crc = p.u32(tk)
            f.names[crc] = code[tk.off + 5:tk.end - 1].decode("latin1")
            continue
        if tk.id == 35:  # script
            p.next()
            nt = p.next()
            crc = p.u32(nt)
            start = nt.end
            depth = 0
            while True:
                t2 = p.t[p.i]
                p.i += 1
                if t2.id == 36:
                    break
            f.scripts[crc] = code[start:t2.end]
            f.order.append(("script", crc))
            continue
        if tk.id == 22:
            p.next()
            eq = p.next()
            if eq.id != 7:
                raise ValueError(f"expected '=' at {eq.off}")
            crc = p.u32(tk)
            f.data[crc] = p.value()
            f.order.append(("data", crc))
            continue
        raise ValueError(f"unexpected top-level token {tk.id:#x} at {tk.off}")
    return f
