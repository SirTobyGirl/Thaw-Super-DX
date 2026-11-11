"""usage: harness/null_trap.py IN.iso OUT.iso  - copy an image and make FUN_002ae610 (StructureContains-like) spin
forever when called with a NULL struct (a0 == 0), so a savestate shows the caller in ra. Debug only."""
import struct
import sys

sys.path.insert(0, ".")
from thaw_sandbox import elf_patch as E, iso_manager as I

src, dst = sys.argv[1:3]
I.stage_copy(src, dst)
CAVE, AT = 0x137F88, 0x2AE628
code = E.asm(CAVE, [("sw", "zero", 0, "zero")] * 0)  # placeholder (asm has no 'sd'; raw words below)
J = lambda a: (2 << 26) | ((a >> 2) & 0x3FFFFFF)
cave = [0xFFB00000,                                   # sd s0, 0(sp)
        0x1080FFFF, 0,                                # loop: beqz a0, loop ; nop
        0x8C900004,                                   # lw s0, 4(a0)
        J(AT + 8), 0]                                 # j 0x2ae630 ; nop
off, _ = I.file_extent(dst, E.ELF)
elf = bytearray(I.read_file(dst, E.ELF))
assert struct.unpack_from("<2I", elf, E.file_offset(elf, AT)) == (0xFFB00000, 0x8C900004)
assert not any(struct.unpack_from("<6I", elf, E.file_offset(elf, CAVE)))
struct.pack_into("<6I", elf, E.file_offset(elf, CAVE), *cave)
struct.pack_into("<2I", elf, E.file_offset(elf, AT), J(CAVE), 0)
I.patch_in_place(dst, off, bytes(elf))
print("trap installed")
