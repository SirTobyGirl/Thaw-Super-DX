"""Prepare a THAW ISO for adding files: DATAP.WAD grows in place over the movies that follow it.

The original layout puts the movies right after DATAP.WAD. This tool (on a reflink copy of the base) sets every
/MOVIES file to size 0, extends DATAP.WAD over the freed space (954 MB of room) and moves DATAP.HED and its two
lookup indexes (DATAPD.HDP, DATAPF.HDP) to the top of that space with padding. The image keeps its size and every
other file its sector. Tried and rejected: rebuilding the image (genisoimage: the PS2 BIOS crashed in loadelf)
and appending past the end of the 4 GB image (new files beyond the single-layer DVD size were never read).

usage: python -m thaw_sandbox.iso_build BASE.iso OUT.iso
"""
import os
import struct
import subprocess
import sys

SECTOR = 2048
HED_SLACK = 64 * 1024


def _dir_records(f, lba, size):
    """Yield (absolute file offset of the record, record bytes) for one ISO9660 directory extent."""
    f.seek(lba * SECTOR)
    data = f.read(size)
    pos = 0
    while pos < len(data):
        n = data[pos]
        if n == 0:  # records never cross a sector: skip to the next one
            pos = (pos // SECTOR + 1) * SECTOR
            continue
        yield lba * SECTOR + pos, data[pos:pos + n]
        pos += n


def find_record(f, name):
    """(record offset, extent LBA, size) of a root-directory entry, e.g. 'DATAP.WAD;1'."""
    f.seek(16 * SECTOR + 156)
    root = f.read(34)
    lba, size = struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0]
    for off, rec in _dir_records(f, lba, size):
        nlen = rec[32]
        if rec[33:33 + nlen].decode("latin1") == name:
            return off, struct.unpack_from("<I", rec, 2)[0], struct.unpack_from("<I", rec, 10)[0]
    raise KeyError(name)


def _set_both(f, off, value):
    """ISO9660 both-endian 32-bit field."""
    f.seek(off)
    f.write(struct.pack("<I", value) + struct.pack(">I", value))


def _all_files(f):
    """[(record offset, lba, size, path)] for every file in the ISO9660 tree."""
    out = []

    def walk(lba, size, path):
        for off, rec in _dir_records(f, lba, size):
            name = rec[33:33 + rec[32]]
            if name in (b"\x00", b"\x01"):
                continue
            rl, rs = struct.unpack_from("<I", rec, 2)[0], struct.unpack_from("<I", rec, 10)[0]
            if rec[25] & 2:
                walk(rl, rs, f"{path}/{name.decode()}")
            else:
                out.append((off, rl, rs, f"{path}/{name.decode()}"))
    f.seek(16 * SECTOR + 156)
    root = f.read(34)
    walk(struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0], "")
    return out


DVD5_SECTORS = 2295104  # single-layer DVD


def _copy_up(f, src, dst, n):
    """Move n bytes from sector src to sector dst > src (overlapping: copy from the end down)."""
    chunk = 16 * 2**20
    left = n
    while left:
        k = min(chunk, left)
        left -= k
        f.seek(src * SECTOR + left)
        data = f.read(k)
        f.seek(dst * SECTOR + left)
        f.write(data)


def build_keep_all(base, out, room):
    """Make room bytes for DATAP.WAD without dropping anything: every file after the WAD moves up, the image
    grows (it must stay within a single-layer DVD), and the HED + lookup indexes go to the top of the new room.
    ISO9660 records, the volume size and UDF (entries, partition length, closing anchor) are updated."""
    from thaw_sandbox.iso_compact import sync_udf
    if os.path.abspath(base) == os.path.abspath(out):
        raise ValueError("output must differ from the base ISO")
    if os.path.exists(out):
        os.remove(out)
    if subprocess.run(["cp", "--reflink=auto", base, out]).returncode != 0:
        raise RuntimeError("copy failed")
    with open(out, "r+b") as f:
        files = _all_files(f)
        total = os.path.getsize(out) // SECTOR
        meta = ("/DATAP.HED;1", "/DATAPD.HDP;1", "/DATAPF.HDP;1")
        r = -(-room // SECTOR) + sum(-(-(x[2] + HED_SLACK) // SECTOR) for x in files if x[3] in meta)
        if total + r > DVD5_SECTORS:
            raise ValueError(f"not enough room on a DVD for these levels without shrinking: "
                             f"{(total + r - DVD5_SECTORS) * SECTOR / 2**20:.0f} MB over; choose fewer levels or "
                             f"shrink the image")
        wad = next(x for x in files if x[3] == "/DATAP.WAD;1")
        wad_end = wad[1] + -(-wad[2] // SECTOR)
        after = sorted((x for x in files if x[1] >= wad_end and x[2]), key=lambda x: -x[1])
        f.truncate((total + r) * SECTOR)
        for off, lba, size, _path in after:  # highest first: moves never overwrite unmoved data
            _copy_up(f, lba, lba + r, size)
            _set_both(f, off + 2, lba + r)
        files = _all_files(f)
        limit = min(x[1] for x in files if x[1] >= wad_end and x[2] and x[3] not in meta)
        top, hed_lba = limit, None
        for name in ("/DATAPF.HDP;1", "/DATAPD.HDP;1", "/DATAP.HED;1"):
            x = next(y for y in files if y[3] == name)
            n = -(-(x[2] + HED_SLACK) // SECTOR)
            top -= n
            f.seek(x[1] * SECTOR)
            data = f.read(x[2])
            f.seek(top * SECTOR)
            f.write(data + bytes(n * SECTOR - len(data)))
            _set_both(f, x[0] + 2, top)
            _set_both(f, x[0] + 10, n * SECTOR if name == "/DATAP.HED;1" else x[2])
            if name == "/DATAP.HED;1":
                hed_lba = top
        new_wad = (hed_lba - wad[1]) * SECTOR
        f.seek(wad[1] * SECTOR + wad[2])
        left = new_wad - wad[2]
        while left:
            n = min(left, 16 * 2**20)
            f.write(bytes(n))
            left -= n
        _set_both(f, wad[0] + 10, new_wad)
        total += r
        f.seek(16 * SECTOR + 80)
        f.write(struct.pack("<I", total) + struct.pack(">I", total))
        sync_udf(f, total)
    return (new_wad - wad[2]) // 2**20


def build(base, out, drop=("MOVIES",)):
    """Grow DATAP.WAD in place over the files that follow it (the movies) and move DATAP.HED to the top of that
    space. Dropped files get size 0. The image keeps its size, so every sector stays inside a single-layer DVD
    (2295104 sectors): appending past the end of the 4 GB image made the new files unreadable."""
    if os.path.abspath(base) == os.path.abspath(out):
        raise ValueError("output must differ from the base ISO")
    if os.path.exists(out):
        os.remove(out)
    if subprocess.run(["cp", "--reflink=auto", base, out]).returncode != 0:
        raise RuntimeError("copy failed")
    with open(out, "r+b") as f:
        files = _all_files(f)
        dropped = [x for x in files if x[3].split("/")[1] in drop]
        wad = next(x for x in files if x[3] == "/DATAP.WAD;1")
        wad_end = wad[1] + -(-wad[2] // SECTOR)
        limit = min(x[1] for x in files if x[1] >= wad_end and x not in dropped)  # next kept file after the WAD
        # the HED and its two lookup indexes (DATAPD.HDP per directory, DATAPF.HDP by filename hash) move to the
        # top of the freed range with zero padding, so they can grow when files are added
        top = limit
        hed_lba = None
        for name in ("/DATAPF.HDP;1", "/DATAPD.HDP;1", "/DATAP.HED;1"):
            x = next(y for y in files if y[3] == name)
            room = -(-(x[2] + HED_SLACK) // SECTOR)
            top -= room
            f.seek(x[1] * SECTOR)
            data = f.read(x[2])
            f.seek(top * SECTOR)
            f.write(data + bytes(room * SECTOR - len(data)))
            _set_both(f, x[0] + 2, top)
            _set_both(f, x[0] + 10, room * SECTOR if name == "/DATAP.HED;1" else x[2])
            if name == "/DATAP.HED;1":
                hed_lba = top
        # WAD grows up to the HED; zero the freed space so slack reads as zeros
        new_wad = (hed_lba - wad[1]) * SECTOR
        f.seek(wad[1] * SECTOR + wad[2])
        left = new_wad - wad[2]
        while left:
            n = min(left, 16 * 2**20)
            f.write(bytes(n))
            left -= n
        _set_both(f, wad[0] + 10, new_wad)
        for off, _lba, _size, _path in dropped:
            _set_both(f, off + 10, 0)
    return len(dropped), (new_wad - wad[2]) // 2**20


if __name__ == "__main__":
    a = sys.argv[1:]
    n, slack = build(a[0], a[1])
    print(f"built {a[1]}: {n} movie files dropped, DATAP.WAD has {slack} MB of room")
