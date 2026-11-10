"""THAW executable (SLUS_212.95) patches, applied in place to the output image.

rails_in_place: the rail table loader (FUN_0025a818) unpacks a zone's .rnb records (22 words each) into a
temporary main-heap buffer of count * 0x60 bytes, copies it back over the file and frees it. With many levels
registered the main heap has no free block that big for large levels (Kyoto, 0x43fe0; THUG San Diego, 0x3e160):
the allocation returns NULL and the memset at 0x4731d8 writes to address 0 (no rails). Every .rnb file is
already sized 8 + count * 0x60, so the patch unpacks in place instead:
  1. (cave 0x250a50) move the packed records to the end of the file (backwards word copy) and point the read
     cursor at them; the unpack buffer is the file itself (s4 = s3). Unpacking forwards then always writes
     below any word not yet read (record i goes to 0x60*i, its source starts at 8 + 8*count + 0x58*i).
  2. (cave 0x4525c8) instead of copy back + free, zero what the memset used to: words 0x58 and 0x5c of every
     record and the terrain word 0x48 of climbing nodes (flag 0x10), which the loop does not write.
The result is the same unpacked table, without the allocation.
"""
import struct

from thaw_sandbox import iso_manager as I

ELF = "/SLUS_212.95;1"
R = dict(zero=0, v0=2, a0=4, t0=8, t1=9, t2=10, t3=11, t4=12, t5=13, s2=18, s3=19, s4=20, s5=21, sp=29, fp=30, ra=31)


def _r(rs, rt, rd, sa, fn):
    return (R[rs] << 21) | (R[rt] << 16) | (R[rd] << 11) | (sa << 6) | fn


def _i(op, rs, rt, imm):
    return (op << 26) | (R[rs] << 21) | (R[rt] << 16) | (imm & 0xFFFF)


def asm(base, prog):
    """prog: list of (mnemonic, args...) or label strings -> list of words at base."""
    labels, pc = {}, base
    for x in prog:
        if isinstance(x, str):
            labels[x] = pc
        else:
            pc += 4
    out, pc = [], base
    for x in prog:
        if isinstance(x, str):
            continue
        m, a = x[0], x[1:]
        br = lambda t: ((labels[t] - (pc + 4)) >> 2) & 0xFFFF
        w = {
            "sll": lambda: _r("zero", a[1], a[0], a[2], 0x00),
            "addu": lambda: _r(a[1], a[2], a[0], 0, 0x21),
            "subu": lambda: _r(a[1], a[2], a[0], 0, 0x23),
            "move": lambda: _r(a[1], "zero", a[0], 0, 0x2D),  # daddu
            "jr": lambda: _r(a[0], "zero", "zero", 0, 0x08),
            "nop": lambda: 0,
            "addiu": lambda: _i(0x09, a[1], a[0], a[2]),
            "andi": lambda: _i(0x0C, a[1], a[0], a[2]),
            "lw": lambda: _i(0x23, a[2], a[0], a[1]),
            "sw": lambda: _i(0x2B, a[2], a[0], a[1]),
            "beq": lambda: _i(0x04, a[0], a[1], br(a[2])),
            "b": lambda: _i(0x04, "zero", "zero", br(a[0])),
            "jal": lambda: (3 << 26) | ((a[0] >> 2) & 0x3FFFFFF),
        }[m]()
        out.append(w)
        pc += 4
    return out


CAVE1, CAVE2 = 0x250A50, 0x4525C8
MOVE_PACKED = asm(CAVE1, [  # a0 = &cursor; s3 = file, s5 = count, fp = count * 0x60
    ("sll", "t0", "s5", 3),
    ("addu", "t1", "s3", "t0"),
    ("addiu", "t1", "t1", 8),      # destination: file + 8 + 8 * count
    ("sw", "t1", 0, "a0"),         # read cursor
    ("subu", "t2", "fp", "t0"),    # bytes: 0x58 * count
    ("addiu", "t3", "s3", 8),      # source: file + 8
    "loop",
    ("beq", "t2", "zero", "done"),
    ("addiu", "t2", "t2", -4),
    ("addu", "t4", "t3", "t2"),
    ("lw", "t5", 0, "t4"),
    ("addu", "t4", "t1", "t2"),
    ("b", "loop"),
    ("sw", "t5", 0, "t4"),
    "done",
    ("jr", "ra"),
    ("move", "s4", "s3"),          # unpack buffer = the file
])
ZERO_PAD = asm(CAVE2, [  # s3 = file, s5 = count
    ("move", "t0", "s3"),
    ("move", "t1", "s5"),
    "loop",
    ("beq", "t1", "zero", "done"),
    ("lw", "t2", 0x40, "t0"),
    ("andi", "t2", "t2", 0x10),
    ("beq", "t2", "zero", "skip"),
    ("sw", "zero", 0x58, "t0"),
    ("sw", "zero", 0x48, "t0"),
    "skip",
    ("sw", "zero", 0x5C, "t0"),
    ("addiu", "t1", "t1", -1),
    ("b", "loop"),
    ("addiu", "t0", "t0", 0x60),
    "done",
    ("jr", "ra"),
    ("nop",),
])
# (address, original words, new words)
RAILS_IN_PLACE = [
    # jal alloc; move a0,fp; move s4,v0; move a1,zero; move a0,s4; jal memset; move a2,fp
    (0x25A8B4, [0x0C04774A, 0x03C0202D, 0x0040A02D, 0x0000282D, 0x0280202D, 0x0C11CC67, 0x03C0302D],
     asm(0x25A8B4, [("jal", CAVE1), ("move", "a0", "sp")] + [("nop",)] * 5)),
    # move a2,fp; move a1,s4; jal memcpy; move s2,zero; jal free; move a0,s4
    (0x25AA6C, [0x03C0302D, 0x0280282D, 0x0C11CBFD, 0x0000902D, 0x0C047786, 0x0280202D],
     asm(0x25AA6C, [("jal", CAVE2), ("nop",), ("nop",), ("move", "s2", "zero"), ("nop",), ("nop",)])),
    (CAVE1, [0] * len(MOVE_PACKED), MOVE_PACKED),
    (CAVE2, [0] * len(ZERO_PAD), ZERO_PAD),
]
PATCHES = {"rails_in_place": RAILS_IN_PLACE}


def _segments(elf):
    ph, n = struct.unpack_from("<I", elf, 0x1C)[0], struct.unpack_from("<H", elf, 0x2C)[0]
    return [struct.unpack_from("<6I", elf, ph + i * 32)[1:6] for i in range(n)]


def file_offset(elf, va):
    for off, v, _, fs, _ in _segments(elf):
        if v <= va < v + fs:
            return off + va - v
    raise ValueError(f"{va:#x} not in the executable")


def patch_bytes(elf: bytes, names=tuple(PATCHES)) -> bytes:
    out = bytearray(elf)
    for name in names:
        for va, old, new in PATCHES[name]:
            o = file_offset(elf, va)
            have = list(struct.unpack_from(f"<{len(old)}I", out, o))
            if have == new:
                continue
            if have != old:
                raise ValueError(f"{name}: unexpected code at {va:#x} (not the NTSC-U THAW executable?)")
            struct.pack_into(f"<{len(new)}I", out, o, *new)
    return bytes(out)


def apply(iso, names=tuple(PATCHES)):
    off, size = I.file_extent(iso, ELF)
    elf = I.read_file(iso, ELF)
    new = patch_bytes(elf, names)
    if new != elf:
        I.patch_in_place(iso, off, new)
