"""Node name-prefix table (zone PAK entry type 0xa7dea591), one per node array.

THAW scripts find nodes by name prefix (Kill / Create / Shatter ... prefix = "TRG_Dalek_"); instead of scanning
names at run time the engine looks the prefix's checksum up in this table (FUN_00250f38 -> FUN_00250d00, binary
search) and gets node indices. The template zone's table lists Kyoto's prefixes and Kyoto's node indices, so a
converted level's prefix lookups returned unrelated or out-of-range nodes (null structs read later on; crashes
that depend on what the level's scripts do and on what was loaded before). Each converted level gets its own.

file = u32 qbcrc(<zone>_NodeArray) | u32 count | count x {u32 prefix checksum, u32 byte offset into the index
       area, u32 index count} sorted by checksum | u16 node indices (ascending per prefix)
Checked on Kyoto: every key is a prefix used by the zone's scripts; lists are sorted subsets of the nodes whose
names start with it (we list all of them).
"""
import struct

from thaw_sandbox import lzss, qb_tokens as T
from thaw_sandbox.qb_parser import qbcrc as H

TYPE = 0xA7DEA591
PREFIX = H("prefix")


def script_prefixes(script_items, names):
    """Prefix strings used by the scripts (string arguments, or checksums resolved through names)."""
    out = set()
    for it in script_items:
        if it.vtype != 7:
            continue
        try:
            code = lzss.unpack_body(it.value)[1]
            toks = T.tokenize(code)
        except Exception:
            continue
        for k in range(len(toks) - 2):
            a, eq, v = toks[k], toks[k + 1], toks[k + 2]
            if a.id != 22 or eq.id != 7 or struct.unpack_from("<I", code, a.off + 1)[0] != PREFIX:
                continue
            if v.id in (27, 28):
                n = struct.unpack_from("<I", code, v.off + 1)[0]
                out.add(code[v.off + 5:v.off + 5 + n].rstrip(b"\0").decode("latin1"))
            elif v.id == 22:
                s = names.get(struct.unpack_from("<I", code, v.off + 1)[0])
                if s:
                    out.add(s)
    return out


def build(node_items, names, prefixes, zone_name):
    """node_items: the node array's structs; names: checksum -> string (debug names)."""
    NAME = H("name")
    node_names = []
    for s in node_items:
        c = next((v.crc for k, v in s.items if k == NAME and hasattr(v, "crc")), None)
        node_names.append((names.get(c) or "").lower())
    recs = []
    for p in prefixes:
        pl = p.lower()
        idx = [i for i, n in enumerate(node_names) if n and n.startswith(pl)]
        recs.append((H(p), idx))
    recs.sort(key=lambda r: r[0])
    head = struct.pack("<2I", H(f"{zone_name}_NodeArray"), len(recs))
    body, area = bytearray(), bytearray()
    for key, idx in recs:
        body += struct.pack("<3I", key, len(area), len(idx))
        area += struct.pack(f"<{len(idx)}H", *idx)
    return head + bytes(body) + bytes(area)
