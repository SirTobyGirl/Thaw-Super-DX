"""Shrink a finished THAW image in place: drop optional media, trim DATAP.WAD's unused room, pack the files down
and cut the image.

THAW discs are UDF bridge images (ISO9660 + UDF 1.02). Everything below the first file (system area, both volume
descriptor sets, directories, UDF file entries; sectors 0..348 on the NTSC-U disc) stays where it is: only file
extents move, always downwards, in their original order. ISO9660 records, the PVD volume size, UDF file entries
(sync_udf), the UDF partition length and the closing anchor are updated to match.

    compact(img, drop=("TEASERS", "MOVIES"))   -> (old MB, new MB)

Rebuilding the image with genisoimage crashed the PS2 BIOS in loadelf; this keeps the original structures and only
changes extents.
"""
import os
import struct
import sys

from thaw_sandbox import wad
from thaw_sandbox.iso_build import SECTOR, _all_files, _dir_records, _set_both

UDF_MAX_EXTENT = 0x3FFFF800  # largest short_ad length that is a whole number of sectors (< 2^30)


def _sectors(n):
    return -(-n // SECTOR)


# ---------------------------------------------------------------- UDF

def _crc_ccitt(data):
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def _retag(buf, n_body):
    """Recompute a descriptor tag's CRC (over the n_body bytes after the 16-byte tag) and checksum."""
    struct.pack_into("<HH", buf, 8, _crc_ccitt(bytes(buf[16:16 + n_body])), n_body)
    buf[4] = sum(buf[i] for i in range(16) if i != 4) & 0xFF


def _read(f, lba, n=SECTOR):
    f.seek(lba * SECTOR)
    return bytearray(f.read(n))


def _udf_layout(f):
    """(partition start, partition descriptor sectors) from the main and reserve volume descriptor sequences."""
    avdp = _read(f, 256)
    assert struct.unpack_from("<H", avdp, 0)[0] == 2, "no UDF anchor at sector 256"
    pstart, pds = None, []
    for ext_off in (16, 24):  # main, reserve VDS extents
        ln, loc = struct.unpack_from("<II", avdp, ext_off)
        for s in range(loc, loc + _sectors(ln)):
            d = _read(f, s)
            tid = struct.unpack_from("<H", d, 0)[0]
            if tid == 5:
                pstart = struct.unpack_from("<I", d, 188)[0]
                pds.append(s)
            if tid == 8:
                break
    return pstart, pds


def _udf_files(f, pstart):
    """{iso-style path ('/DIR/NAME;1'): FE sector} for every file in the UDF tree."""
    fsd = _read(f, pstart)
    assert struct.unpack_from("<H", fsd, 0)[0] == 256
    root = pstart + struct.unpack_from("<I", fsd, 400 + 4)[0]
    out = {}

    def fe_extents(fe):
        lea, lad = struct.unpack_from("<II", fe, 168)
        ads = fe[176 + lea:176 + lea + lad]
        return [struct.unpack_from("<II", ads, i) for i in range(0, lad, 8)]

    def walk(fe_lba, path):
        fe = _read(f, fe_lba)
        assert fe[16 + 18] & 7 == 0, "only short allocation descriptors are handled"
        data = b"".join(bytes(_read(f, pstart + pos, ln & 0x3FFFFFFF)) for ln, pos in fe_extents(fe))
        p = 0
        while p + 38 <= len(data):
            if struct.unpack_from("<H", data, p)[0] != 257:
                break
            chars, lfi = data[p + 18], data[p + 19]
            icb = struct.unpack_from("<I", data, p + 24)[0]
            liu = struct.unpack_from("<H", data, p + 36)[0]
            raw = data[p + 38 + liu:p + 38 + liu + lfi]
            p += (38 + liu + lfi + 3) & ~3
            if chars & 8:  # parent
                continue
            name = raw[1:].decode("latin1") if raw[:1] == b"\x08" else raw[1:].decode("utf-16-be")
            if chars & 2:
                walk(pstart + icb, f"{path}/{name}")
            else:
                out[f"{path}/{name}".upper()] = pstart + icb
    walk(root, "")
    return out


def sync_udf(f, total_sectors=None):
    """Make every UDF file entry describe the same extent as its ISO9660 record (sizes, positions); optionally
    set the partition length and write the closing anchor for an image of total_sectors."""
    pstart, pds = _udf_layout(f)
    udf = _udf_files(f, pstart)
    n = 0
    for _off, lba, size, path in _all_files(f):
        key = path.rsplit(";", 1)[0].upper()
        if key not in udf:
            continue
        s = udf[key]
        fe = _read(f, s)
        lea, lad = struct.unpack_from("<II", fe, 168)
        ads, pos, left = bytearray(), lba - pstart, size
        while True:
            ln = min(left, UDF_MAX_EXTENT)
            ads += struct.pack("<II", ln, pos if ln else 0)
            left -= ln
            pos += _sectors(ln)
            if not left:
                break
        new = fe[:176 + lea] + ads
        assert len(new) <= SECTOR
        struct.pack_into("<I", new, 172, len(ads))
        struct.pack_into("<QQ", new, 56, size, _sectors(size))
        _retag(new, len(new) - 16)
        if new != fe[:len(new)]:
            f.seek(s * SECTOR)
            f.write(bytes(new) + bytes(SECTOR - len(new)))
            n += 1
    if total_sectors:
        for s in pds:
            d = _read(f, s)
            struct.pack_into("<I", d, 192, total_sectors - pstart)
            _retag(d, struct.unpack_from("<H", d, 10)[0])
            f.seek(s * SECTOR)
            f.write(bytes(d))
        anchor = _read(f, 256)
        struct.pack_into("<I", anchor, 12, total_sectors - 1)  # tag location
        _retag(anchor, struct.unpack_from("<H", anchor, 10)[0])
        f.seek((total_sectors - 1) * SECTOR)
        f.write(bytes(anchor))
    return n


# ---------------------------------------------------------------- DATAP.WAD pruning

# story-mode / extras content the sandbox can never reach (story mode, the extras menu and the GameCube build)
WAD_DROP = ("\\cutscenes\\", "\\images\\ngc_screens\\", "\\images\\concept_art\\")


def prune_wad(img, prefixes=WAD_DROP):
    """Give dropped WAD files size 0 and pack the rest down inside DATAP.WAD (HED and both lookup indexes are
    rewritten by Disc.save). Entries sharing data keep sharing it. -> bytes freed"""
    from thaw_sandbox.disc import Disc
    d = Disc(img)
    for e in d.ents:
        if e.name.lower().startswith(prefixes):
            e.size = 0
    spans = {}  # old sector -> bytes needed (max over aliases)
    for e in d.ents:
        if e.size:
            spans[e.offset] = max(spans.get(e.offset, 0), e.size)
    new, cur = {}, 0
    with open(img, "r+b") as f:
        base = d.wad_off // SECTOR
        for off in sorted(spans):
            assert off >= cur
            _move(f, base + off, base + cur, spans[off])
            new[off] = cur
            cur += _sectors(spans[off])
    freed = d.end - cur * SECTOR
    for e in d.ents:
        e.offset = new.get(e.offset, 0) if e.size else 0
    d.save()
    return freed


# ---------------------------------------------------------------- compaction

def _wad_used(f, files):
    """Bytes of DATAP.WAD actually referenced by DATAP.HED."""
    hed = next(x for x in files if x[3] == "/DATAP.HED;1")
    f.seek(hed[1] * SECTOR)
    ents, _ = wad.parse_hed(f.read(hed[2]))
    return max(e.offset * SECTOR + e.size for e in ents)


def _dir_extents(f):
    out = []

    def walk(lba, size):
        out.append((lba, size))
        for _off, rec in _dir_records(f, lba, size):
            if rec[33:33 + rec[32]] in (b"\x00", b"\x01"):
                continue
            if rec[25] & 2:
                walk(struct.unpack_from("<I", rec, 2)[0], struct.unpack_from("<I", rec, 10)[0])
    f.seek(16 * SECTOR + 156)
    root = f.read(34)
    walk(struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0])
    return out


def _move(f, src, dst, n):
    """Copy n bytes from sector src to sector dst (dst <= src; forward chunks are safe)."""
    if src == dst or not n:
        return
    assert dst < src
    done = 0
    while done < n:
        k = min(n - done, 32 * 2**20)
        f.seek(src * SECTOR + done)
        b = f.read(k)
        f.seek(dst * SECTOR + done)
        f.write(b)
        done += k


def compact(img, drop=("TEASERS", "MOVIES"), trim_wad=True, wad_drop=WAD_DROP, log=print):
    old = os.path.getsize(img)
    if wad_drop:
        log(f"story/extras files dropped from DATAP.WAD: {prune_wad(img, wad_drop) / 2**20:.0f} MB")
    with open(img, "r+b") as f:
        files = _all_files(f)
        live = [x for x in files if x[2] and x[3].split("/")[1] not in drop]
        start = min(x[1] for x in live)
        top_dir = max(l + _sectors(s) for l, s in _dir_extents(f))
        assert top_dir <= start, "directories above the first file"
        sizes = {x[3]: x[2] for x in live}
        if trim_wad:
            sizes["/DATAP.WAD;1"] = _wad_used(f, files)
        cur = start
        for off, lba, size, path in sorted(live, key=lambda x: x[1]):
            assert lba >= cur
            n = sizes[path]
            _move(f, lba, cur, n)
            _set_both(f, off + 2, cur)
            _set_both(f, off + 10, n)
            cur += _sectors(n)
        for off, lba, size, path in files:
            if (off, lba, size, path) not in live:
                _set_both(f, off + 2, start)
                _set_both(f, off + 10, 0)
        total = cur + 1  # + the closing UDF anchor
        f.seek(16 * SECTOR + 80)
        f.write(struct.pack("<I", total) + struct.pack(">I", total))
        n_fe = sync_udf(f, total)
        f.truncate(total * SECTOR)
    log(f"compacted: {old / 2**20:.0f} MB -> {total * SECTOR / 2**20:.0f} MB ({n_fe} UDF entries updated)")
    return old / 2**20, total * SECTOR / 2**20


if __name__ == "__main__":
    compact(sys.argv[1])
