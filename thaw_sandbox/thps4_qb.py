"""THPS4 (PS2) .qb token streams -> THUG2 form, so thug2_qb / convert_thug2 handle them.

Differences found on the THPS4 disc (SLUS-20504):
  0x02  newline + u32 line number          -> 0x01 newline
  0x2f/0x37/0x40/0x41 random: u32 count + count u32 offsets  -> THUG2 adds count u16 weights (1) before the offsets
Relative offsets (random choices, 0x2e jump; all relative to the end of their field) are recomputed after the
rewrite. if/else/endif are the old position-free tokens (0x25/0x26/0x28), which need no fixing.
"""
import struct

from thaw_sandbox.qb_tokens import tokenize

RANDOM = (47, 55, 64, 65)


def to_thug2(code: bytes) -> bytes:
    toks = tokenize(code, random_entry=4)
    out = bytearray()
    pos = {}  # old offset -> new offset (token starts)
    fixups = []  # (new field offset, old target offset, new field end)
    for t in toks:
        pos[t.off] = len(out)
        if t.id == 2:
            out += b"\x01"
        elif t.id in RANDOM:
            c = struct.unpack_from("<I", code, t.off + 1)[0]
            out += code[t.off:t.off + 5] + struct.pack("<H", 1) * c
            for k in range(c):
                fo = t.off + 5 + 4 * k
                fixups.append((len(out), fo + 4 + struct.unpack_from("<i", code, fo)[0]))
                out += b"\0\0\0\0"
        elif t.id == 46:
            out += b"\x2e"
            fixups.append((len(out), t.end + struct.unpack_from("<i", code, t.off + 1)[0]))
            out += b"\0\0\0\0"
        else:
            out += code[t.off:t.end]
    pos[len(code)] = len(out)
    for field, target in fixups:
        struct.pack_into("<i", out, field, pos[target] - (field + 4))
    return bytes(out)
