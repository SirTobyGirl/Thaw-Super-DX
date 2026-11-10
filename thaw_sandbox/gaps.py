"""THAW gap list (.gap, zone PAK entry type 0xff2d0e91): the level's gap checklist (names + scores).

file   = u32 1 | u32 qbcrc(zone name) | u16 count | count x {u32 score, u8 length, name (no terminator)}
         sorted by score, then name case-insensitively (checked on every THAW zone's list)
The template's list names Kyoto's gaps under z_ja; each converted level gets its own from the EndGap calls in its
level scripts (EndGap GapID=<id> text="<name>" score=<n>; one entry per GapID).
"""
import struct

from thaw_sandbox import lzss, qb_tokens as T
from thaw_sandbox.qb_parser import qbcrc as H

GAP_TYPE = 0xFF2D0E91
END_GAP, GAP_ID, TEXT, SCORE = H("EndGap"), H("GapID"), H("text"), H("score")


def _args(code, toks, k):
    """key=value pairs after the call token toks[k], up to the end of the line."""
    out = {}
    j = k + 1
    while j + 2 < len(toks) and toks[j].id not in (1, 2):
        a, eq, v = toks[j], toks[j + 1], toks[j + 2]
        if a.id == 22 and eq.id == 7:
            key = struct.unpack_from("<I", code, a.off + 1)[0]
            if v.id in (27, 28):
                n = struct.unpack_from("<I", code, v.off + 1)[0]
                out[key] = code[v.off + 5:v.off + 5 + n].rstrip(b"\0").decode("latin1")
            elif v.id in (22, 23):
                out[key] = struct.unpack_from("<I" if v.id == 22 else "<i", code, v.off + 1)[0]
            j += 3
        else:
            j += 1
    return out


def collect(script_items) -> list[tuple[int, str]]:
    """script_items: qb_file items of converted (THAW form) level scripts -> [(score, name)]."""
    seen, out = set(), []
    for it in script_items:
        if it.vtype != 7:
            continue
        code = lzss.unpack_body(it.value)[1]
        try:
            toks = T.tokenize(code)
        except Exception:
            continue
        for k, t in enumerate(toks):
            if t.id == 22 and struct.unpack_from("<I", code, t.off + 1)[0] == END_GAP:
                a = _args(code, toks, k)
                gid = a.get(GAP_ID)
                if TEXT in a and isinstance(a.get(SCORE), int) and gid not in seen:
                    seen.add(gid)
                    out.append((a[SCORE], a[TEXT]))
    return out


def build(entries, zone_name: str) -> bytes:
    entries = sorted(entries, key=lambda e: (e[0], e[1].lower()))[:0xFFFF]
    out = bytearray(struct.pack("<IIH", 1, H(zone_name), len(entries)))
    for score, name in entries:
        b = name.encode("latin1", "replace")[:255]
        out += struct.pack("<IB", score & 0xFFFFFFFF, len(b)) + b
    return bytes(out)
