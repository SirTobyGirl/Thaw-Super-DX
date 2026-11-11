"""Borrowed textures: decode source-game textures to RGBA (contact sheets, colour stats) and pick them as
materials for generated levels. Textures come from the user's own discs, like the converted levels."""
import struct

from thaw_sandbox import thaw_tex as TT


def _c32(v):
    return (v & 255, (v >> 8) & 255, (v >> 16) & 255, min(255, ((v >> 24) & 255) * 2))


def _c16(v):
    return ((v & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31, ((v >> 10) & 31) * 255 // 31, 255 if v >> 15 else 0)


def rgba(src):
    """Top level of a linear palettised texture (thug2_tex.Texture / thaw_tex.NewTexture) -> bytes RGBA."""
    w, h, m = src.width, src.height, src.mips[0]
    cl = src.clut
    if src.cpsm == 2:
        pal = [_c16(struct.unpack_from("<H", cl, k * 2)[0]) for k in range(len(cl) // 2)]
    else:
        pal = [_c32(struct.unpack_from("<I", cl, k * 4)[0]) for k in range(len(cl) // 4)]
    if src.psm == 0x14:
        idx = [(m[k >> 1] >> (4 * (k & 1))) & 15 for k in range(w * h)]
    elif src.psm == 0x13:
        idx = m[:w * h]
        if len(pal) == 256:
            pal = [pal[(k & 0xE7) | ((k & 8) << 1) | ((k & 16) >> 1)] for k in range(256)]
    else:
        raise NotImplementedError(f"psm {src.psm:#x}")
    return b"".join(bytes(pal[i]) for i in idx)


def new_texture(src, crc=None, group=None, levels=4):
    return TT.NewTexture(crc if crc is not None else src.crc, src.width, src.height, src.psm, src.cpsm, src.clut,
                         src.mips[:levels], group=group if group is not None else (crc or src.crc))
