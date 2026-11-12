"""ISO helpers. Strategy: never rebuild the disc; patch data in place (iso_build moves DATAP.WAD/HED to the end
of the image with slack so they can grow).

The vanilla disc is copied to a staging path first (the original is never written to).
LBAs, UDF structures and SYSTEM.CNF stay untouched because only file contents change.
"""
import os
import shutil

SECTOR = 2048


def file_extent(iso_path: str, inner_path: str) -> tuple[int, int]:
    """Return (byte offset in the ISO, length) of a file, e.g. '/DATAP.WAD;1' or '/MUSIC/MUSICP.WAD;1'.
    Read straight from the ISO9660 directories (iso_build): pycdlib refuses images this tool has grown past
    single-layer DVD size or moved files in, and some original discs (THPS3)."""
    from thaw_sandbox.iso_build import _all_files, find_record
    with open(iso_path, "rb") as f:
        if inner_path.count("/") == 1:
            _, lba, size = find_record(f, inner_path[1:])
            return lba * SECTOR, size
        want = inner_path.upper()
        for _off, lba, size, path in _all_files(f):
            if path.upper() == want:
                return lba * SECTOR, size
    raise KeyError(inner_path)


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
    off, size = file_extent(iso_path, inner_path)
    with open(iso_path, "rb") as f:
        f.seek(off)
        return f.read(size)
