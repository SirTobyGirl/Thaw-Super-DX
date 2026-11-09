"""ISO helpers. Strategy: never rebuild the disc; patch same-size data in place.

The vanilla disc is copied to a staging path first (the original is never written to).
LBAs, UDF structures and SYSTEM.CNF stay untouched because only file contents change.
"""
import io
import os
import shutil

import pycdlib

SECTOR = 2048


def file_extent(iso_path: str, inner_path: str) -> tuple[int, int]:
    """Return (byte offset in the ISO, length) of a file, e.g. '/DATAP.WAD;1'."""
    iso = pycdlib.PyCdlib()
    iso.open(iso_path)
    try:
        rec = iso.get_record(iso_path=inner_path)
        return rec.extent_location() * SECTOR, rec.get_data_length()
    finally:
        iso.close()


def stage_copy(vanilla: str, staging: str) -> str:
    """Copy the vanilla ISO to a staging path (refuses to touch the original)."""
    if os.path.abspath(vanilla) == os.path.abspath(staging):
        raise ValueError("staging path must differ from the vanilla ISO")
    os.makedirs(os.path.dirname(staging), exist_ok=True)
    if os.path.exists(staging):
        os.remove(staging)  # a reflinked file must not be patched in place by an older copy
    # reflink (btrfs/xfs): the copy shares unchanged data with its source, so a 4 GB test ISO costs only
    # the bytes we patch. Falls back to a normal copy elsewhere.
    import subprocess
    if subprocess.run(["cp", "--reflink=auto", vanilla, staging]).returncode != 0:
        shutil.copyfile(vanilla, staging)
    return staging


def patch_in_place(iso_path: str, abs_offset: int, data: bytes):
    with open(iso_path, "r+b") as f:
        f.seek(abs_offset)
        f.write(data)


def read_file(iso_path: str, inner_path: str) -> bytes:
    iso = pycdlib.PyCdlib()
    iso.open(iso_path)
    try:
        buf = io.BytesIO()
        iso.get_file_from_iso_fp(buf, iso_path=inner_path)
        return buf.getvalue()
    finally:
        iso.close()
