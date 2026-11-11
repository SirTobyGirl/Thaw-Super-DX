"""Tokenizer for decompressed THAW QB script bytecode (see lzss.py for decompression).

Token ids and sizes follow THUG2 (tools/QScript/Source/QToken.h, QBinary.cpp) with one THAW
addition found by testing:
    0x4a  serialized parameter block: ends at k-2+size, k = payload header offset (2 mod 4)
Verified: every script of the vanilla disc tokenizes exactly to its end (terminator 0x24), and the
statement offsets from the .dbg [LineNumbers] tables land on token boundaries.
"""
import shlex
import struct
from dataclasses import dataclass

NAME = {
    0: "EOF", 1: "EOL", 2: "EOLN", 3: "{", 4: "}", 5: "[", 6: "]", 7: "=", 8: ".", 9: ",", 10: "-", 11: "+",
    12: "/", 13: "*", 14: "(", 15: ")", 16: "DEBUGINFO", 17: "==", 18: "<", 19: "<=", 20: ">", 21: ">=",
    22: "name", 23: "int", 24: "hex", 25: "enum", 26: "float", 27: "string", 28: "lstring", 29: "array",
    30: "vector", 31: "pair", 32: "begin", 33: "repeat", 34: "break", 35: "script", 36: "endscript",
    37: "if", 38: "else", 39: "elseif", 40: "endif", 41: "return", 42: "undefined", 43: "checksumname",
    44: "<...>", 45: "arg", 46: "jump", 47: "random", 48: "randomrange", 49: "at", 50: "|", 51: "&", 52: "^",
    53: "<<", 54: ">>", 55: "random2", 56: "randomrange2", 57: "not", 58: "and", 59: "or", 60: "switch",
    61: "endswitch", 62: "case", 63: "default", 64: "randomnorepeat", 65: "randompermute", 66: ":",
    71: "fastif", 72: "fastelse", 73: "shortjump", 74: "blob",
}
ONE = {1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 19, 20, 21, 32, 33, 34, 35, 36, 37, 38, 39,
       40, 41, 44, 45, 50, 51, 52, 53, 54, 48, 56, 57, 58, 59, 60, 61, 62, 63, 66}
FIVE = {2, 22, 23, 24, 26, 46}


@dataclass
class Tok:
    off: int
    id: int
    end: int  # offset just past this token


def tokenize(code: bytes, random_entry: int = 6) -> list[Tok]:
    """random_entry: bytes per random choice (THUG2/THAW: u16 weight + u32 offset; THPS4: u32 offset only)."""
    out, i, n = [], 0, len(code)
    while i < n:
        t = code[i]
        if t == 0:
            j = i + 1
        elif t in ONE:
            j = i + 1
        elif t in FIVE:
            j = i + 5
        elif t == 30:
            j = i + 13
        elif t == 31:
            j = i + 9
        elif t in (27, 28):
            j = i + 5 + struct.unpack_from("<I", code, i + 1)[0]
        elif t == 74:
            # serialized parameter block: 4a | u32 size | zero pad | payload header 01 00 08 00 00 00 00 ...
            # The payload header sits at k = x + ((2 - x) % 4) with x = i + 5, and the block (which
            # starts 2 bytes before k, possibly inside the size field) is `size` bytes long.
            x = i + 5
            k = x + ((2 - x) % 4)
            j = k - 2 + struct.unpack_from("<I", code, i + 1)[0]
        elif t == 43:
            j = code.index(b"\0", i + 5) + 1
        elif t in (47, 55, 64, 65):
            j = i + 5 + random_entry * struct.unpack_from("<I", code, i + 1)[0]
        elif t in (71, 72, 73):
            j = i + 3
        else:
            raise ValueError(f"unknown token {t:#x} at {i}")
        if j > n:
            raise ValueError(f"token {t:#x} at {i} runs past end")
        out.append(Tok(i, t, j))
        i = j
    return out


def argblock(p: bytes, nm) -> str:
    """Render a 0x4a parameter block: 7 byte header, then 16 byte entries [type][00 00][name][value][next]."""
    parts, o = [], 7
    while o + 13 <= len(p):
        typ = p[o]
        name, val = struct.unpack_from("<2I", p, o + 3)
        key = "" if name == 0 else nm(name) + " = "
        if typ == 0x03:
            parts.append(f"{key}{struct.unpack_from('<i', p, o + 7)[0]}")
        elif typ == 0x05:
            parts.append(f"{key}{struct.unpack_from('<f', p, o + 7)[0]:g}f")
        elif typ == 0x1b:
            parts.append(f"{key}{nm(val)}")
        else:
            parts.append(f"{key}<t{typ:02x}:{val:#x}>")
        nxt = struct.unpack_from("<I", p, o + 11)[0] if o + 15 <= len(p) else 0
        if not nxt:
            break
        o += 16
    return "{" + ", ".join(parts) + "}"


def disasm(code: bytes, names=None, start: int = 0, stop: int | None = None) -> str:
    """Lenient text view of bytecode: resolves names, shows 0x4a blocks, stops at unknown tokens."""
    stop = len(code) if stop is None else stop
    nm = (lambda h: names.get(h) or f"0x{h:08x}") if names else (lambda h: f"0x{h:08x}")
    out, i = [], start
    while i < stop:
        t = code[i]
        try:
            if t == 0:
                out.append("<00>"); i += 1
            elif t == 22:
                out.append(nm(struct.unpack_from("<I", code, i + 1)[0])); i += 5
            elif t == 23:
                out.append(str(struct.unpack_from("<i", code, i + 1)[0])); i += 5
            elif t == 26:
                out.append(f"{struct.unpack_from('<f', code, i + 1)[0]:g}f"); i += 5
            elif t in FIVE:
                out.append(f"{NAME[t]}:{code[i+1:i+5].hex()}"); i += 5
            elif t == 1:
                out.append(f"\n{i:4d}:"); i += 1
            elif t in ONE:
                out.append(NAME[t]); i += 1
            elif t in (27, 28):
                n = struct.unpack_from("<I", code, i + 1)[0]
                out.append(repr(code[i + 5:i + 5 + n].rstrip(b"\0").decode("latin1"))); i += 5 + n
            elif t == 30:
                out.append("vec" + str(struct.unpack_from("<3f", code, i + 1))); i += 13
            elif t == 31:
                out.append("pair" + str(struct.unpack_from("<2i", code, i + 1))); i += 9
            elif t in (47, 55, 64, 65):
                c = struct.unpack_from("<I", code, i + 1)[0]; out.append(f"random[{c}]"); i += 5 + 6 * c
            elif t in (71, 72, 73):
                out.append(f"{NAME[t]}:{struct.unpack_from('<h', code, i + 1)[0]}"); i += 3
            elif t == 74:
                x = i + 5
                k = x + ((2 - x) % 4)
                e = k - 2 + struct.unpack_from("<I", code, i + 1)[0]
                out.append(argblock(code[k:e], nm)); i = e
            else:
                out.append(f"??{t:02x}[{code[i:i+10].hex()}]"); break
        except Exception as e:
            out.append(f"!!{e}"); break
    return " ".join(out)


def assemble(text: str, qbcrc) -> bytes:
    """Tiny assembler: one statement per line; words become name tokens, '=' '{' '}' '[' ']' ',' map to
    their tokens, integers become int tokens, 'endscript' ends. Adds the leading/trailing EOL like the
    originals:  01 <statement tokens> 01 24.
    """
    sym = {"=": 7, "{": 3, "}": 4, "[": 5, "]": 6, ",": 9, "arg": 45, "<...>": 44}
    out = bytearray()
    for line in text.strip().splitlines():
        out.append(1)
        for w in shlex.split(line):
            if w in sym:
                out.append(sym[w])
            elif w.lstrip("-").isdigit():
                out += b"\x17" + struct.pack("<i", int(w))
            elif w.startswith("str:"):
                b = w[4:].encode("latin1") + b"\0"
                out += b"\x1b" + struct.pack("<I", len(b)) + b
            else:
                out += b"\x16" + struct.pack("<I", qbcrc(w))
    out += b"\x01\x24"
    return bytes(out)
