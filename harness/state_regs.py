"""usage: state_regs.py STATE.p2s  - unpack a PCSX2 savestate here (cwd) and print EE pc, GPRs and the stack top."""
import sys, zipfile, zstandard, struct
f = open(sys.argv[1], 'rb'); z = zipfile.ZipFile(f)
for zi in z.infolist():
    f.seek(zi.header_offset); h = f.read(30); nl, el = struct.unpack_from('<HH', h, 26)
    f.seek(zi.header_offset + 30 + nl + el); raw = f.read(zi.compress_size)
    if zi.compress_type != 0:
        raw = zstandard.ZstdDecompressor().decompressobj().decompress(raw)
    open(zi.filename, 'wb').write(raw)
d = open('PCSX2 Internal Structures.dat', 'rb').read()
g = d.find(b'cpuRegs') + 0x20
regs = [struct.unpack_from('<I', d, g + 16 * r)[0] for r in range(32)]
names = "zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra".split()
print('pc', hex(struct.unpack_from('<I', d, g + 0x2a8)[0]))
print(' '.join(f'{a}={r:#x}' for a, r in zip(names, regs)))
m = open('eeMemory.bin', 'rb').read(); sp = regs[29]
print('stack', [hex(struct.unpack_from('<I', m, sp + 4 * i)[0]) for i in range(64)])
