"""Reader for THUG2 PS2 texture dictionaries (.tex.ps2, version 5; THPS4 version 4: same without the leading zero word).

file    = u32 version (5) | u32 group count | u32 texture count | groups...
group   = u32 crc | u32 0 | u32 0 | u32 texture count | textures...
texture = u32 (0) | u32 crc | u32 log2 width | u32 log2 height | u32 psm | u32 clut psm | u32 flags
          | zero padding up to a 16-byte file offset | clut (if palettised) | mip levels
          flags & 0xFF = mip count - 1. psm: 0x00 CT32, 0x02 CT16, 0x13 T8, 0x14 T4 (GS codes).
          flags bit 31: header only (28 bytes), no padding, no clut, no pixels.
Pixel data is linear (host order), not swizzled.
"""
import struct
from dataclasses import dataclass, field

BPP = {0x00: 32, 0x01: 24, 0x02: 16, 0x13: 8, 0x14: 4}
CLUT_ENTRIES = {0x13: 256, 0x14: 16}


@dataclass
class Texture:
    """flags bit 31 (0x80000000): header-only entry with no clut or pixel data (mips == [])."""
    crc: int
    width: int
    height: int
    psm: int
    cpsm: int
    flags: int
    clut: bytes
    mips: list = field(default_factory=list)  # bytes per level, largest first
    group: int = 0


def parse(b: bytes) -> tuple[list[int], list[Texture]]:
    ver, ngroups, ntex = struct.unpack_from("<3I", b, 0)
    assert ver in (4, 5), f"version {ver}"
    hdr = 28 if ver == 5 else 24  # version 4 (THPS4) has no leading zero word
    o = 12
    groups, texs = [], []
    # the texture count is authoritative: Disney Extreme Skate Adventure's Olliewood says 10 groups and holds more
    while len(texs) < ntex and o + 16 <= len(b):
        gcrc, _a, _b, n = struct.unpack_from("<4I", b, o)
        o += 16
        groups.append(gcrc)
        for k in range(n):
            crc, lw, lh, psm, cpsm, flags = struct.unpack_from("<7I" if ver == 5 else "<6I", b, o)[-6:]
            if flags & 0x80000000:  # header only: no clut/pixels, no padding (data lives elsewhere)
                texs.append(Texture(crc, 1 << lw, 1 << lh, psm, cpsm, flags, b"", [], gcrc))
                o += hdr
                continue
            o += hdr
            o += -o % 16
            w, h = 1 << lw, 1 << lh
            clut = b""
            if psm in CLUT_ENTRIES:
                cb = CLUT_ENTRIES[psm] * (4 if cpsm == 0 else 2)
                clut = b[o:o + cb]
                o += cb
            mips = []
            for m in range((flags & 0xFF) + 1):
                n_bytes = max(1, w >> m) * max(1, h >> m) * BPP[psm] // 8
                mips.append(b[o:o + n_bytes])
                o += n_bytes
            texs.append(Texture(crc, w, h, psm, cpsm, flags, clut, mips, gcrc))
    assert o == len(b), f"parsed to {o:#x}, file is {len(b):#x}"
    assert len(texs) == ntex
    return groups, texs
