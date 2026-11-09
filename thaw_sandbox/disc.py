"""Edit DATAP.HED / DATAP.WAD inside a THAW ISO in place (an image prepared by iso_build, which moved both to
the end of the disc with spare room).

    d = Disc("out.iso")
    data = d.read("\\pak\\qb.pab.ps2")
    d.put("\\pak\\qb.pab.ps2", new_bytes)      # in place if it fits its slot, else appended to the WAD slack
    d.add("\\worlds\\worldzones\\z_tr\\z_tr.pak.ps2", zone_bytes)   # new file, appended
    d.save()                                   # writes the HED back (it must fit the HED's padded size)

The HED is mostly alphabetical, but the shipped disc already has zone packs appended out of order at the end, so
new entries are appended too; their data goes to the WAD slack.
"""
import collections
import struct

from thaw_sandbox import iso_manager as I
from thaw_sandbox import wad
from thaw_sandbox.qb_parser import qbcrc

SECTOR = 2048


class Disc:
    def __init__(self, iso: str):
        self.iso = iso
        self.wad_off, self.wad_len = I.file_extent(iso, "/DATAP.WAD;1")
        self.hed_off, self.hed_len = I.file_extent(iso, "/DATAP.HED;1")
        with open(iso, "rb") as f:
            f.seek(self.hed_off)
            self.ents, self.trailer = wad.parse_hed(f.read(self.hed_len))
        self.trailer = self.trailer.rstrip(b"\0")
        self.by_name = {e.name.lower(): e for e in self.ents}
        self.orig = {id(e): (e.offset, e.size) for e in self.ents}
        self.hdpf = I.read_file(iso, "/DATAPF.HDP;1")
        self.end = max(e.offset * SECTOR + e.size for e in self.ents)
        self.end += -self.end % SECTOR

    def _entry(self, name):
        return self.by_name[name.lower()]

    def read(self, name: str) -> bytes:
        e = self._entry(name)
        with open(self.iso, "rb") as f:
            f.seek(self.wad_off + e.offset * SECTOR)
            return f.read(e.size)

    def _write(self, pos: int, data: bytes):
        assert pos + len(data) <= self.wad_len, "out of WAD slack: rebuild the base with a larger --wad-slack-mb"
        with open(self.iso, "r+b") as f:
            f.seek(self.wad_off + pos)
            f.write(data)

    def _append(self, data: bytes) -> int:
        pos = self.end
        padded = data + bytes(-len(data) % SECTOR)
        self._write(pos, padded)
        self.end = pos + len(padded)
        return pos // SECTOR

    def put(self, name: str, data: bytes):
        e = self._entry(name)
        start = e.offset * SECTOR
        nxt = min((x.offset * SECTOR for x in self.ents if x.offset * SECTOR > start), default=self.end)
        if start + len(data) <= nxt:
            self._write(start, data + bytes(-len(data) % SECTOR))
        else:
            e.offset = self._append(data)
        e.size = len(data)

    def add(self, name: str, data: bytes):
        if name.lower() in self.by_name:
            return self.put(name, data)
        e = wad.Entry(self._append(data), len(data), name)  # new: not in self.orig
        # appended, like the shipped disc's late additions (zone packs such as z_ho, z_sr, z_sm sit out of
        # alphabetical order at the end of the HED and load fine, so the game does not binary-search it)
        key = name.lower()
        self.ents.append(e)
        self.by_name[key] = e

    def _hdpd(self) -> bytes:
        """DATAPD.HDP: [file count, file table, dir table (0x10), 0], one (count, qbcrc(dir path), file table
        pointer) record per directory in HED order + terminator, then (sector, size, qbcrc(filename)) per file
        grouped by directory. Regenerating the shipped file from the shipped HED is byte-identical."""
        def split(name):
            p = name.lstrip("\\")
            return p.rsplit("\\", 1) if "\\" in p else ("", p)
        order, groups = [], collections.defaultdict(list)
        for e in self.ents:
            d = split(e.name)[0].lower()
            if d not in groups:
                order.append(d)
            groups[d].append(e)
        ftab = 16 + 12 * (len(order) + 1)
        out = bytearray(struct.pack("<4I", len(self.ents), ftab, 16, 0))
        recs = bytearray()
        for d in order:
            out += struct.pack("<3I", len(groups[d]), 0xFFFFFFFF if d == "" else qbcrc(d), ftab + len(recs))
            for e in groups[d]:
                recs += struct.pack("<3I", e.offset, e.size, qbcrc(split(e.name)[1]))
        return bytes(out + struct.pack("<3I", 0xFFFFFFFF, 0, 0) + recs)

    def _hdpf(self) -> bytes:
        """DATAPF.HDP: [count, 0x10, 0, 0] + (sector, size, qbcrc(filename)) sorted by hash (binary search).
        Original records keep their order (ties are in no reproducible order); changed files are updated,
        new files inserted at their hash position."""
        n = struct.unpack_from("<I", self.hdpf, 0)[0]
        recs = [list(struct.unpack_from("<3I", self.hdpf, 16 + 12 * i)) for i in range(n)]
        moved = {self.orig[id(e)]: (e.offset, e.size) for e in self.ents if id(e) in self.orig}
        for r in recs:
            if (r[0], r[1]) in moved:
                r[0], r[1] = moved[(r[0], r[1])]
        for e in self.ents:
            if id(e) not in self.orig:
                h = qbcrc(e.name.rsplit("\\", 1)[-1])
                i = 0
                while i < len(recs) and recs[i][2] <= h:
                    i += 1
                recs.insert(i, [e.offset, e.size, h])
        return struct.pack("<4I", len(recs), 16, 0, 0) + b"".join(struct.pack("<3I", *r) for r in recs)

    def _write_root_file(self, name, data):
        """Rewrite a root file of the image inside its allocated room (up to the next file) and set its size."""
        from thaw_sandbox.iso_build import _all_files, _set_both, SECTOR as S
        with open(self.iso, "r+b") as f:
            files = _all_files(f)
            rec = next(x for x in files if x[3] == name)
            room = (min(x[1] for x in files if x[1] > rec[1]) - rec[1]) * S
            assert len(data) <= room, f"{name}: {len(data)} bytes > room {room}"
            f.seek(rec[1] * S)
            f.write(data)
            if name != "/DATAP.HED;1":
                _set_both(f, rec[0] + 10, len(data))

    def save(self):
        hed = wad.build_hed(self.ents, self.trailer)
        assert len(hed) <= self.hed_len, f"HED {len(hed)} > room {self.hed_len}"
        with open(self.iso, "r+b") as f:
            f.seek(self.hed_off)
            f.write(hed + bytes(self.hed_len - len(hed)))
        self._write_root_file("/DATAPD.HDP;1", self._hdpd())
        self._write_root_file("/DATAPF.HDP;1", self._hdpf())
