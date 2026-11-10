"""Older (THPS4 / THUG) .qb token streams -> THUG2 form, so thug2_qb / convert_thug2 handle them.

Differences found on the discs:
  THPS4 0x02  newline + u32 line number          -> 0x01 newline
  THPS4 0x2f/0x37/0x40/0x41 random: u32 count + count u32 offsets  -> THUG2 adds count u16 weights (1) first
  both  0x25/0x26/0x28 if/else/endif (the interpreter scans for the match) -> 0x47/0x48 fast if/else with a u16
        offset + 0x28 endif, as THUG2/THAW compile them. Rule (from THUG2 scripts): offset = end of the matching
        else/endif - (opcode offset + 1). With old ifs left in, a one-line gap script hung Alcatraz's load.
Relative offsets (random choices, 0x2e jump; relative to the end of their field) are recomputed after the rewrite.
"""
import struct

from thaw_sandbox.qb_tokens import tokenize

RANDOM = (47, 55, 64, 65)
IF, ELSE, ELSEIF, ENDIF, FASTIF, FASTELSE = 37, 38, 39, 40, 71, 72


def to_thug2(code: bytes, random_entry: int = 4) -> bytes:
    """random_entry: bytes per random choice in the input (THPS4 4, THUG 6 = already THUG2's)."""
    toks = tokenize(code, random_entry=random_entry)
    out = bytearray()
    pos, end = {}, {}  # old token offset -> new start / new end
    fixups = []  # (new field offset, old target offset)
    ifs = []  # (new opcode offset, old offset of the matching else/endif)
    stack = []
    match = {}
    for t in toks:  # pair if/else/endif (nesting)
        if t.id == IF:
            stack.append(t.off)
        elif t.id == ELSE and stack:
            match[stack[-1]] = t.off
            stack[-1] = t.off
        elif t.id == ENDIF and stack:
            match[stack.pop()] = t.off
        elif t.id == ELSEIF:
            raise ValueError("elseif not handled")
    for t in toks:
        pos[t.off] = len(out)
        if t.id == 2:
            out += b"\x01"
        elif t.id in RANDOM:
            c = struct.unpack_from("<I", code, t.off + 1)[0]
            out += code[t.off:t.off + 5]
            if random_entry == 4:
                out += struct.pack("<H", 1) * c
            else:
                out += code[t.off + 5:t.off + 5 + 2 * c]
            for k in range(c):
                fo = t.off + 5 + (2 * c if random_entry == 6 else 0) + 4 * k
                fixups.append((len(out), fo + 4 + struct.unpack_from("<i", code, fo)[0]))
                out += b"\0\0\0\0"
        elif t.id == 46:
            out += b"\x2e"
            fixups.append((len(out), t.end + struct.unpack_from("<i", code, t.off + 1)[0]))
            out += b"\0\0\0\0"
        elif t.id in (IF, ELSE) and t.off in match:
            ifs.append((len(out), match[t.off]))
            out += bytes([FASTIF if t.id == IF else FASTELSE]) + b"\0\0"
        else:
            out += code[t.off:t.end]
        end[t.off] = len(out)
    pos[len(code)] = len(out)
    for field, target in fixups:
        struct.pack_into("<i", out, field, pos[target] - (field + 4))
    for op, m in ifs:
        off = end[m] - (op + 1)
        assert off < 0x8000, "if block too long for a fast if"
        struct.pack_into("<h", out, op + 1, off)
    return bytes(out)
