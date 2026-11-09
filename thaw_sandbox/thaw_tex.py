"""Reader for THAW PS2 texture dictionaries (.tex inside zone PAKs, version 6).

header  = u16 version (6) | u16 group count | u32 texture count | u32 packet offset | u32 data offset
groups  = group count x 80 bytes from 0x10 (contents not decoded yet)
records = texture count x 64 bytes, right after the groups; the packet area starts where they end
record  = [0] crc | [1] group crc | [2] flags | [3] ? | [4,5] GS TEX0 (64 bit) | [6,7] ? (mip pointers?)
          | [10] image offset | [11] image size | [12] clut offset | [13] clut size   (relative to data offset)
          | [14] offset of the image upload packet (relative to packet offset) | [15] ?
Pixel data is stored pre-swizzled for the GS: each image is uploaded with BITBLTBUF/TRXREG in a possibly
different format (e.g. a 128x128 T4 texture as a 64x32 CT32 image), so decoding writes it into a simulated
GS memory with the upload format and reads it back with the TEX0 format (see gsmem.py).
"""
import struct
from dataclasses import dataclass

from thaw_sandbox import gsmem as G


@dataclass
class Texture:
    crc: int
    group: int
    tbp: int
    tbw: int
    psm: int
    width: int
    height: int
    cpsm: int
    image: tuple   # (offset, size) relative to data offset
    clut: tuple
    packet: int    # offset of the upload packet relative to packet offset
    words: tuple   # all 16 record dwords


def parse(b: bytes):
    ver, ngroups, ntex, poff, doff = struct.unpack_from("<HHIII", b, 0)
    assert ver == 6, f"version {ver}"
    rec0 = 0x10 + ngroups * 80
    assert rec0 + ntex * 64 == poff, "record table does not end at the packet area"
    texs = []
    for i in range(ntex):
        w = struct.unpack_from("<16I", b, rec0 + i * 64)
        t0 = w[4] | (w[5] << 32)
        texs.append(Texture(w[0], w[1], t0 & 0x3FFF, (t0 >> 14) & 63, (t0 >> 20) & 63, 1 << ((t0 >> 26) & 15),
                            1 << ((t0 >> 30) & 15), (t0 >> 51) & 15, (w[10], w[11]), (w[12], w[13]), w[14], w))
    return (poff, doff), texs


def upload_params(b: bytes, poff: int, t: Texture):
    """(dbp, dbw, dpsm, rrw, rrh) of the image upload packet."""
    p = poff + t.packet
    lo, reg = struct.unpack_from("<QQ", b, p - 0x40)
    assert reg & 0xFF == 0x50, "BITBLTBUF not where expected"
    tr = struct.unpack_from("<Q", b, p - 0x20)[0]
    return (lo >> 32) & 0x3FFF, (lo >> 48) & 63, (lo >> 56) & 63, tr & 0xFFF, (tr >> 32) & 0xFFF


def _c16(v):
    return ((v & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31, ((v >> 10) & 31) * 255 // 31, 255 if v >> 15 else 0)


def _c32(v):
    return (v & 255, (v >> 8) & 255, (v >> 16) & 255, min(255, ((v >> 24) & 255) * 2))


def decode_rgba(b: bytes, offs, t: Texture) -> list:
    """Top mip level as a list of (r, g, b, a). Palettised T4/T8 only."""
    poff, doff = offs
    dbp, dbw, dpsm, rrw, rrh = upload_params(b, poff, t)
    vram = G.VRAM()
    fmt = G.PSM[dpsm]
    n = rrw * rrh * G.FORMATS[fmt][6] // 8
    io = doff + t.image[0]
    vram.write(fmt, dbp, dbw, rrw, rrh, b[io:io + n])
    pix = vram.read(G.PSM[t.psm], t.tbp, t.tbw, t.width, t.height)
    co, cs = doff + t.clut[0], t.clut[1]
    cl = b[co:co + cs]
    if t.cpsm == 2:
        pal = [_c16(struct.unpack_from("<H", cl, k * 2)[0]) for k in range(cs // 2)]
    else:
        pal = [_c32(struct.unpack_from("<I", cl, k * 4)[0]) for k in range(cs // 4)]
    if t.psm == 0x14:
        idx = [(pix[k // 2] >> (4 * (k & 1))) & 15 for k in range(t.width * t.height)]
    elif t.psm == 0x13:
        idx = list(pix)
        if len(pal) == 256:  # CSM1 palette order
            pal = [pal[(k & 0xE7) | ((k & 8) << 1) | ((k & 16) >> 1)] for k in range(256)]
    else:
        raise NotImplementedError(f"psm {t.psm:#x}")
    return [pal[k] for k in idx]
