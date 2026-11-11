"""PS2 SPU ADPCM ('VAG' body) helpers: decode, interleave analysis and re-interleaving of music streams."""
import struct

F = [(0, 0), (60, 0), (115, -52), (98, -55), (122, -60)]


def decode(b: bytes, state=(0, 0)):
    """Decode 16-byte ADPCM frames -> (samples list, end state)."""
    s1, s2 = state
    out = []
    for o in range(0, len(b) - 15, 16):
        sf, flags = b[o], b[o + 1]
        shift, filt = sf & 0xF, min((sf >> 4) & 0xF, 4)
        f0, f1 = F[filt]
        for i in range(28):
            byte = b[o + 2 + i // 2]
            nib = (byte >> 4) if i & 1 else (byte & 0xF)
            if nib & 8:
                nib -= 16
            v = (nib << 12) >> shift
            v += (s1 * f0 + s2 * f1 + 32) >> 6
            v = max(-32768, min(32767, v))
            out.append(v)
            s2, s1 = s1, v
    return out, (s1, s2)


def boundary_jump(stream: bytes, block: int, nblocks=24):
    """Mean |jump| at block boundaries of channel 0 relative to the mean in-block step, assuming stereo blocks
    of `block` bytes (L, R, L, R ...). The true interleave gives a ratio near 1."""
    st = (0, 0)
    prev = None
    jumps, steps = [], []
    for k in range(0, 2 * nblocks, 2):
        chunk = stream[k * block:(k + 1) * block]
        if len(chunk) < block:
            break
        smp, st = decode(chunk, st)
        if prev is not None:
            jumps.append(abs(smp[0] - prev))
        steps += [abs(a - b) for a, b in zip(smp[1:200], smp[:199])]
        prev = smp[-1]
    if not jumps or not steps:
        return None
    return (sum(jumps) / len(jumps)) / (sum(steps) / len(steps) + 1e-9)


def lr_correlation(stream: bytes, block: int, pairs=6):
    """Correlation of channel 0 vs channel 1 assuming stereo blocks of `block` bytes; the true interleave of a
    stereo music stream gives a high value (left and right are similar)."""
    sl, sr, L, R = (0, 0), (0, 0), [], []
    for k in range(pairs):
        a = stream[2 * k * block:(2 * k + 1) * block]
        b = stream[(2 * k + 1) * block:(2 * k + 2) * block]
        if len(b) < block:
            break
        x, sl = decode(a, sl)
        y, sr = decode(b, sr)
        L += x
        R += y
    n = min(len(L), len(R))
    if n < 100:
        return None
    L, R = L[:n], R[:n]
    ml, mr = sum(L) / n, sum(R) / n
    cov = sum((a - ml) * (b - mr) for a, b in zip(L, R))
    vl = sum((a - ml) ** 2 for a in L) ** 0.5
    vr = sum((b - mr) ** 2 for b in R) ** 0.5
    return cov / (vl * vr + 1e-9)
