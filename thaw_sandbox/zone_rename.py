"""Rename a THAW zone PAK's internals from one zone name to another (e.g. Kyoto's z_ja template -> z_tr).

A level is looked up by its zone name: scene/entry path hashes (qbcrc of the path without the platform suffix),
QB records such as <ZONE>_sfx_NodeArray, scripts and the names they refer to. Everything whose original string
is known (names table) and contains the old zone name is renamed: entry path hashes and parent links, embedded
full names (same length), QB record names, Name values inside data, and name tokens (0x16 + crc) in script code.
"""
import struct

from thaw_sandbox import lzss, qb_data as QD, qb_file as F, zone
from thaw_sandbox.convert_thug2 import script_body
from thaw_sandbox.qb_parser import NameTable, qbcrc

QB_TYPES = (0x49875607, 0x5D796624, 0xA7F505C4)  # .nqb, .sqb, .qb entries in zone PAKs


def _mapper(nt: NameTable, old: str, new: str, extra=()):
    m = {}

    def rename(crc):
        if crc in m:
            return m[crc]
        s = nt.get(crc)
        if s and not s.startswith("0x") and old in s.lower():
            i = s.lower().index(old)
            ns = s[:i] + (new.upper() if s[i:i + len(old)].isupper() else new) + s[i + len(old):]
            m[crc] = qbcrc(ns)
        else:
            m[crc] = crc
        return m[crc]
    return rename


def _rename_value(v, rn):
    if isinstance(v, QD.Name):
        return QD.Name(rn(v.crc))
    if isinstance(v, QD.Struct):
        v.items = [(rn(k) if k else k, _rename_value(x, rn)) for k, x in v.items]
        return v
    if isinstance(v, QD.Array):
        v.items = [_rename_value(x, rn) for x in v.items]
        return v
    return v


def _rename_code(code: bytes, rn) -> bytes:
    out = bytearray(code)
    i = 0
    while True:
        i = out.find(b"\x16", i)
        if i < 0 or i + 5 > len(out):
            break
        crc = struct.unpack_from("<I", out, i + 1)[0]
        n = rn(crc)
        if n != crc:
            struct.pack_into("<I", out, i + 1, n)
        i += 1
    return bytes(out)


def rename_zone(zb: bytes, old: str, new: str, nt: NameTable) -> tuple[bytes, dict]:
    assert len(old) == len(new)
    # paths of this zone's entries (for the entry header hashes)
    paths = [f"worlds\\worldzones\\{old}\\{old}{s}{e}" for s in ("", "_sfx", "_scripts", "_sfx_scripts", "_peds",
             "_level_particle_data", "_level_fast_particle_data", "_sfx_dat_ps2") for e in ("", ".qb", ".tex", ".geom",
             ".col", ".scn", ".mdl")]
    paths += [f"worlds\\worldzones\\{old}\\{old}ped{e}" for e in ("", ".qb", ".tex", ".geom", ".col", ".mdl", ".skin")]
    paths += [f"sounds\\pak\\{old}_sfx{e}" for e in ("", ".qb")]
    for e in zone.entries(zb):  # full names stored in the PAK (flag 0x20)
        if struct.unpack_from("<I", zb, e.pos + 28)[0] & 0x20:
            n = zb[e.pos + 32:e.pos + 192].split(b"\0")[0].decode("latin1")
            paths += [n, n.rsplit(".", 1)[0], n.rsplit(".", 2)[0]]
    nt.add_names(paths + [p.replace(old, new) for p in paths])
    rn = _mapper(nt, old, new)
    out = bytearray(zb)
    st = {"entries": 0, "names": 0, "qb records": 0}
    rep = {}
    for e in zone.entries(zb):
        w = list(struct.unpack_from("<8I", zb, e.pos))
        for k in (3, 6):
            n = rn(w[k])
            if n != w[k]:
                struct.pack_into("<I", out, e.pos + 4 * k, n)
                st["entries"] += 1
        if w[7] & 0x20:
            name = zb[e.pos + 32:e.pos + 192]
            if old.encode() in name.lower():
                lo = name.lower()
                fixed = bytearray(name)
                i = lo.find(old.encode())
                while i >= 0:
                    fixed[i:i + len(old)] = new.encode() if name[i:i + len(old)].islower() else new.upper().encode()
                    i = lo.find(old.encode(), i + 1)
                out[e.pos + 32:e.pos + 192] = fixed
                st["names"] += 1
        if w[0] in QB_TYPES and e.size < 0x40000000:
            from thaw_sandbox import pak
            p = pak.data_pos(e, 0)
            try:
                crc, items = F.read(zb[p:p + e.size])
            except Exception:
                continue
            for it in items:
                it.name = rn(it.name)
                if it.vtype == 7:
                    c, code = lzss.unpack_body(it.value)
                    nc = _rename_code(code, rn)
                    if nc != code:
                        it.value = script_body(nc)
                else:
                    it.value = _rename_value(it.value, rn)
                st["qb records"] += 1
            rep[e.pos] = F.write(crc, items)
    res = zone.rebuild(bytes(out), rep) if rep else bytes(out)
    return res, st
