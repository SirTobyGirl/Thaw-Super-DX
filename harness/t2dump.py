"""Dump a THUG2/THUG .qb (uncompressed token stream) as text.  PYTHONPATH=. python harness/t2dump.py FILE [regex]"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
import qbdump
from thaw_sandbox import qb_parser as Q, qb_tokens as T, thug2_qb


def dump(path, pattern=None):
    b = open(path, "rb").read()
    q = thug2_qb.parse(b)
    names = Q.NameTable.load(qbdump.NAMES)
    names.names.update(q.names)
    out = []
    for kind, crc in q.order:
        n = names.get(crc)
        if pattern and not re.search(pattern, n, re.I):
            continue
        if kind == "data":
            out.append(f"{n} = {qbdump.fmt(q.data[crc], names.get)}\n")
        else:
            out.append(f"script {n}" + T.disasm(q.scripts[crc], names.names) + "\n")
    return "\n".join(out)


if __name__ == "__main__":
    print(dump(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
