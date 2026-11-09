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


# ---------------------------------------------------------------- encoder
WINDOWS = [(0x2BC0, 0x35A0), (0x35A0, 0x3F80)]  # VRAM block ranges THAW alternates between per group
PAGE_DIMS = {0x14: (128, 128), 0x13: (128, 64), 0x02: (64, 64), 0x00: (64, 32)}
BPP = {0x14: 4, 0x13: 8, 0x02: 16, 0x00: 32}


@dataclass
class NewTexture:
    crc: int
    width: int
    height: int
    psm: int           # 0x14 T4, 0x13 T8 (palettised); 0x00/0x02 untested
    cpsm: int          # 0x00 CT32, 0x02 CT16
    clut: bytes        # palette as stored by the GS (CT32 RGBA with alpha 0x80 = opaque, or CT16)
    mips: list         # linear pixel data per level, largest first
    flags: int = 0x40005  # record field 3; meaning unknown, most common value in THAW
    group: int = 0        # texture group crc; geometry refers to groups, so keep the source's groups


def _tbw(psm, w):
    tbw = max(1, -(-w // 64))
    if psm in (0x13, 0x14):
        tbw = max(2, tbw + (tbw & 1))
    return tbw


def _pages(psm, w, h, tbw):
    pw, ph = PAGE_DIMS[psm]
    return (tbw * 64 // pw) * -(-h // ph)


BLOCK_DIMS = {0x14: (32, 16), 0x13: (16, 16), 0x02: (16, 8), 0x00: (8, 8)}


def _level_blocks(psm, w, h, tbw):
    """VRAM blocks reserved for one level: a single block if it fits inside one, else whole pages."""
    bw, bh = BLOCK_DIMS[psm]
    if w <= bw and h <= bh:
        return 1
    return _pages(psm, w, h, tbw) * 32


def _qwords(n):
    return -(-n // 16)


def _upload_packet(dbp, dbw, dpsm, rrw, rrh, data_off, nbytes):
    nqw = _qwords(nbytes)
    q = []
    q.append(struct.pack("<QQ", 0x10000006, 0x50000006 << 32))                 # DMA CNT 6, VIF DIRECT 6
    q.append(struct.pack("<QQ", 0x1000000000000004, 0x0E))                     # GIFtag A+D x4
    q.append(struct.pack("<QQ", (dbp << 32) | (dbw << 48) | (dpsm << 56), 0x50))  # BITBLTBUF
    q.append(struct.pack("<QQ", 0, 0x51))                                      # TRXPOS
    q.append(struct.pack("<QQ", (rrh << 32) | rrw, 0x52))                      # TRXREG
    q.append(struct.pack("<QQ", 0, 0x53))                                      # TRXDIR host->local
    q.append(struct.pack("<QQ", 0x0800000000000000 | nqw, 0))                  # GIFtag IMAGE nqw
    q.append(struct.pack("<QQ", ((0xEB00000A + data_off) << 32) | 0x30000000 | nqw,
                         (0x50000000 | nqw) << 32))                            # DMA REF data, VIF DIRECT
    return b"".join(q)


GROUP_END = struct.pack("<QQ", 0x60000002, 0x50000002 << 32) + \
    struct.pack("<QQ", 0x1000000000008001, 0x0E) + struct.pack("<QQ", 0, 0x3F)  # RET, TEXFLUSH


def write(textures: list) -> bytes:
    """Build a version 6 texture dictionary. Pixels are uploaded in their own format (no swizzling).
    Groups (and their order) come from NewTexture.group."""
    # 1. keep the source's groups (order of first appearance); each group gets the next VRAM window
    order, members = [], {}
    for t in textures:
        if t.group not in members:
            order.append(t.group)
            members[t.group] = []
        members[t.group].append(t)
    groups = []
    for gi, gcrc in enumerate(order):
        win = gi % 2
        for drop in (False, True):  # if a group overflows its window, keep only top mip levels
            lo, hi, items = WINDOWS[win][0], WINDOWS[win][1], []
            ok = True
            for t in members[gcrc]:
                mips = t.mips[:1] if drop else t.mips
                levels = []
                for m in range(len(mips)):
                    w, h = max(1, t.width >> m), max(1, t.height >> m)
                    tbw = _tbw(t.psm, w)
                    levels.append((w, h, tbw, _level_blocks(t.psm, w, h, tbw)))
                cblocks = (4 if t.cpsm == 0 else 2) if t.psm == 0x13 else 1
                cbp = hi - cblocks
                cbp -= cbp % cblocks
                tbps = []
                for lv in levels:
                    if lv[3] >= 32 and lo % 32:  # page-sized levels start on a page
                        lo += 32 - lo % 32
                    tbps.append(lo)
                    lo += lv[3]
                if lo > cbp:
                    ok = False
                    break
                hi = cbp
                items.append((t, levels, tbps, cbp, mips))
            if ok:
                break
        else:
            raise ValueError(f"texture group {gcrc:#x} does not fit a VRAM window even without mips")
        groups.append({"win": win, "crc": gcrc, "items": items})

    # 2. lay out data area, packets and records
    data = bytearray()
    seen = {}  # identical clut / pixel blobs are stored once (THAW does the same)

    def put(blob):
        if blob in seen:
            return seen[blob]
        off = len(data)
        data.extend(blob + b"\0" * (-len(blob) % 16))
        seen[blob] = off
        return off

    packets = bytearray()
    records = []
    group_recs = []
    first = 0
    for gi, g in enumerate(groups):
        gstart = len(packets)
        for t, levels, tbps, cbp, mips in g["items"]:
            clut_off = put(t.clut) if t.clut else 0
            if t.clut:
                n = len(t.clut) // (4 if t.cpsm == 0 else 2)
                rw, rh = (8, 2) if n == 16 else (16, 16)
                packets += _upload_packet(cbp, 1, t.cpsm, rw, rh, clut_off, len(t.clut))
            mip0_packet = None
            img_off = None
            for (w, h, tbw, _), tbp, px in zip(levels, tbps, mips):
                off = put(px)
                if img_off is None:
                    img_off = off
                if mip0_packet is None:
                    mip0_packet = len(packets) + 0x60
                packets += _upload_packet(tbp, tbw, t.psm, w, h, off, len(px))
            img_size = sum(len(px) + (-len(px) % 16) for px in mips)
            tw, th = t.width.bit_length() - 1, t.height.bit_length() - 1
            tex0 = (tbps[0] | (levels[0][2] << 14) | (t.psm << 20) | (tw << 26) | (th << 30) | (1 << 34)
                    | (cbp << 37) | (t.cpsm << 51) | (1 << 61))
            mip1 = 0
            for k, sh in ((1, 0), (2, 20), (3, 40)):
                if k < len(levels):
                    mip1 |= (tbps[k] | (levels[k][2] << 14)) << sh
            words = [t.crc, g["crc"], len(levels) - 1, t.flags, tex0 & 0xFFFFFFFF, tex0 >> 32,
                     mip1 & 0xFFFFFFFF, mip1 >> 32, 0, 0, img_off, img_size, clut_off if t.clut else 0,
                     len(t.clut), mip0_packet, len(mips[0]) << 12]
            records.append(struct.pack("<16I", *words))
        packets += GROUP_END
        win = WINDOWS[g["win"]]
        group_recs.append(struct.pack("<20I", 0, 0, g["crc"], 0, gstart, gstart, 0, 0, 0, 0, 0, 0,
                                      (win[1] << 16) | win[0], 0, 0, len(g["items"]), first, 0, 0xC000, 0))
        first += len(g["items"])
    ntex = len(records)
    poff = 0x10 + 80 * len(groups) + 64 * ntex
    doff = poff + len(packets)
    doff += -doff % 16
    head = struct.pack("<HHIII", 6, len(groups), ntex, poff, doff)
    out = head + b"".join(group_recs) + b"".join(records) + bytes(packets)
    out += b"\0" * (doff - len(out))
    return bytes(out + data)


def extract_native(b: bytes, offs, t: Texture) -> NewTexture:
    """Top mip level as linear pixels in the texture's own format, plus its raw clut bytes."""
    poff, doff = offs
    dbp, dbw, dpsm, rrw, rrh = upload_params(b, poff, t)
    vram = G.VRAM()
    fmt = G.PSM[dpsm]
    n = rrw * rrh * G.FORMATS[fmt][6] // 8
    io = doff + t.image[0]
    vram.write(fmt, dbp, dbw, rrw, rrh, b[io:io + n])
    pix = vram.read(G.PSM[t.psm], t.tbp, t.tbw, t.width, t.height)
    co, cs = doff + t.clut[0], t.clut[1]
    return NewTexture(t.crc, t.width, t.height, t.psm, t.cpsm, b[co:co + cs], [pix], t.words[3], t.group)
