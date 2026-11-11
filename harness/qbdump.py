"""Dump a THAW .qb file as text (data records as nested structs, scripts disassembled).

    PYTHONPATH=. python harness/qbdump.py FILE.qb.ps2 [name filter regex]
"""
import re
import sys

from thaw_sandbox import lzss, qb_data as QD, qb_file as F, qb_parser as Q, qb_tokens as T

NAMES = "_workspace/qbwork/names.pkl"


def fmt(v, nm, ind=0):
    pad = "  " * ind
    if isinstance(v, QD.Struct):
        if not v.items:
            return "{}"
        rows = []
        for k, x in v.items:
            rows.append(f"{pad}  {nm(k) + ' = ' if k else ''}{fmt(x, nm, ind + 1)}")
        return "{\n" + "\n".join(rows) + f"\n{pad}}}"
    if isinstance(v, QD.Array):
        if all(not isinstance(x, (QD.Struct, QD.Array)) for x in v.items):
            return "[" + ", ".join(fmt(x, nm, ind) for x in v.items) + "]"
        return "[\n" + "\n".join(f"{pad}  {fmt(x, nm, ind + 1)}" for x in v.items) + f"\n{pad}]"
    if isinstance(v, QD.Name):
        return nm(v.crc)
    if isinstance(v, QD.LStr):
        return "L" + repr(str(v))
    return repr(v)


def dump(path, pattern=None, names=None):
    names = names or Q.NameTable.load(NAMES)
    nm = names.get
    _, items = F.read(open(path, "rb").read())
    out = []
    for it in items:
        n = nm(it.name)
        if pattern and not re.search(pattern, n, re.I):
            continue
        if it.vtype == 7:
            try:
                code = lzss.unpack_body(it.value)[1]
                out.append(f"script {n}" + T.disasm(code, names.names) + "\n")
            except Exception as e:
                out.append(f"script {n}  !! {e}\n")
        else:
            out.append(f"{n} = {fmt(it.value, nm)}\n")
    return "\n".join(out)


if __name__ == "__main__":
    print(dump(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
