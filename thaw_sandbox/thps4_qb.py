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
SWITCH, ENDSWITCH, CASE, DEFAULT, SHORTJUMP = 60, 61, 62, 63, 73


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
    # switches: THAW (like THUG2) compiles each case/default with a short jump to the next clause and ends each
    # case body with a short jump past endswitch; THPS4/THUG streams have neither (a THUG Manhattan goal script
    # and Moscow's setup hung the load). Offsets: target - (opcode + 1), as fast ifs.
    sw_stack, clause_of, sw_end_of = [], {}, {}
    has_jumps = any(t.id == SHORTJUMP for t in toks)
    for t in toks:
        if has_jumps:
            break
        if t.id == SWITCH:
            sw_stack.append({"clauses": [], "end": None})
        elif t.id in (CASE, DEFAULT) and sw_stack:
            sw = sw_stack[-1]
            clause_of[t.off] = (sw, len(sw["clauses"]))
            sw["clauses"].append(t)
        elif t.id == ENDSWITCH and sw_stack:
            sw = sw_stack.pop()
            sw["end"] = t
            sw_end_of[t.off] = sw
    clause_pos = {}  # old clause/endswitch offset -> new offset of that token
    jumps = []  # (new opcode offset, kind, data)
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
        elif t.off in clause_of:
            sw, k = clause_of[t.off]
            if k and sw["clauses"][k - 1].id == CASE:  # end of the previous case body: jump past endswitch
                jumps.append((len(out), "end", sw))
                out += b"\x49\0\0"
            clause_pos[t.off] = len(out)
            out += bytes([t.id])
            jumps.append((len(out), "next", (sw, k)))
            out += b"\x49\0\0"
        elif t.off in sw_end_of:
            sw = sw_end_of[t.off]
            if sw["clauses"] and sw["clauses"][-1].id == CASE:
                jumps.append((len(out), "end", sw))
                out += b"\x49\0\0"
            clause_pos[t.off] = len(out)
            out += bytes([t.id])
        elif t.id in (IF, ELSE) and t.off in match:
            ifs.append((len(out), match[t.off]))
            out += bytes([FASTIF if t.id == IF else FASTELSE]) + b"\0\0"
        else:
            out += code[t.off:t.end]
        end[t.off] = len(out)
    pos[len(code)] = len(out)
    for field, target in fixups:
        struct.pack_into("<i", out, field, pos[target] - (field + 4))
    for op, kind, data in jumps:
        if kind == "end":
            target = clause_pos[data["end"].off] + 1
        else:
            sw, k = data
            nxt = sw["clauses"][k + 1] if k + 1 < len(sw["clauses"]) else sw["end"]
            target = clause_pos[nxt.off]
        struct.pack_into("<h", out, op + 1, target - (op + 1))
    for op, m in ifs:
        off = end[m] - (op + 1)
        assert off < 0x8000, "if block too long for a fast if"
        struct.pack_into("<h", out, op + 1, off)
    return bytes(out)
