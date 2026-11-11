"""Dump a zone PAK's .qb entries as text into _workspace/qbtxt/zones/<zone>/.

    PYTHONPATH=. python harness/zonedump.py z_ja [z_hodt ...]   (or a path to a .pak.ps2)
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import qbdump
from thaw_sandbox import pak, qb_parser as Q, zone

ROOT = "_workspace/datap/worlds/worldzones"


def main(args):
    names = Q.NameTable.load(qbdump.NAMES)
    for z in args:
        path = z if os.path.exists(z) else f"{ROOT}/{z}/{z}.pak.ps2"
        b = open(path, "rb").read()
        names.add_bytes(b)
        out = f"_workspace/qbtxt/zones/{os.path.basename(path).split('.')[0]}"
        os.makedirs(out, exist_ok=True)
        for e in zone.entries(b):
            if not e.name.endswith(".qb.ps2"):
                continue
            dp = pak.data_pos(e, 0)
            with tempfile.NamedTemporaryFile(suffix=".qb") as t:
                t.write(b[dp:dp + e.size]); t.flush()
                try:
                    txt = qbdump.dump(t.name, names=names)
                except Exception as ex:
                    txt = f"!! {ex}"
            fn = os.path.join(out, e.name.split("\\")[-1].replace(".qb.ps2", ".txt"))
            open(fn, "w").write(txt)
            print(fn, len(txt))


if __name__ == "__main__":
    main(sys.argv[1:])
