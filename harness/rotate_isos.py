"""Keep the build folder small: keep the base sandbox ISO plus the KEEP newest other ISOs, delete the rest.
usage: rotate_isos.py [KEEP=3]   (also called automatically by build_level_test.py)"""
import glob
import os
import sys

BUILD = os.path.join(os.path.dirname(__file__), "..", "_workspace", "build")
BASE = {"sandbox.iso"}


def rotate(keep=3):
    isos = [p for p in glob.glob(os.path.join(BUILD, "*.iso")) if os.path.basename(p) not in BASE]
    isos.sort(key=os.path.getmtime, reverse=True)
    for p in isos[keep:]:
        os.remove(p)
        print("rotated out", os.path.basename(p))


if __name__ == "__main__":
    rotate(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
