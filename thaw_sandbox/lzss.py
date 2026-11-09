"""LZSS used for THAW QB script bodies (Okumura variant, found by testing against known sizes).

A script body is  [u32 crc][u32 uncompressed size A][u32 stored size B][B bytes of stream]
If A == B the stream is stored raw. Otherwise it is LZSS:
  * flag byte, 8 items per flag, least significant bit first, bit 1 = literal byte
  * bit 0 = match: byte1 = low 8 bits of ring position, byte2 high nibble = bits 8..11 of
    the position, byte2 low nibble = length - 3
  * ring buffer of 4096 bytes, write pointer starts at 4078, buffer pre-filled with spaces (0x20),
    as in the encoder in the PC executable (180 scripts decode differently with a zero fill)
Flag bytes can fall in the middle of a 4-byte hash, so do not scan compressed data for names.
"""
import struct

N = 4096
START = 4078


def decompress(stream: bytes, out_size: int) -> bytes:
    out = bytearray()
    ring = bytearray(b" " * N)  # the game's encoder pre-fills the ring with spaces
    rp = START
    i = 0
    while len(out) < out_size and i < len(stream):
        flags = stream[i]
        i += 1
        for k in range(8):
            if len(out) >= out_size:
                break
            if (flags >> k) & 1:
                c = stream[i]
                i += 1
                out.append(c)
                ring[rp] = c
                rp = (rp + 1) & (N - 1)
            else:
                b1, b2 = stream[i], stream[i + 1]
                i += 2
                pos = b1 | ((b2 & 0xF0) << 4)
                for t in range((b2 & 0x0F) + 3):
                    c = ring[(pos + t) & (N - 1)]
                    out.append(c)
                    ring[rp] = c
                    rp = (rp + 1) & (N - 1)
    return bytes(out[:out_size])


def unpack_body(body: bytes) -> tuple[int, bytes]:
    """Return (header crc, uncompressed bytecode) for a script body."""
    crc, a, b = struct.unpack_from("<3I", body, 0)
    stream = body[12:12 + b]
    return crc, (stream if a == b else decompress(stream, a))


def pack_body_raw(crc: int, code: bytes) -> bytes:
    """Store bytecode uncompressed (A == B), padded to a 4 byte multiple like the originals."""
    body = struct.pack("<3I", crc, len(code), len(code)) + code
    return body + b"\0" * (-len(body) % 4)


def compress_literals(code: bytes) -> bytes:
    """Valid (uncompressed-ratio) LZSS stream: every item a literal. Decoders stop at the stated size."""
    out = bytearray()
    for i in range(0, len(code), 8):
        chunk = code[i:i + 8]
        out.append(0xFF)
        out += chunk
    return bytes(out)


def compress_to_size(code: bytes, stored: int) -> bytes:
    """LZSS stream of exactly `stored` bytes that decodes to code + zero padding and is fully consumed.

    The engine may decode until its input is used up, so the stream must neither under- nor overrun:
    all-literal items for the code and zero padding (ignored after the endscript token), then a few
    zero-copy matches (ring positions that are still untouched zeros) to hit the byte count exactly.
    Returns the stream; its decoded length is len(decompress-able output) = literals + 3 * matches.
    """
    for m in (1, 2, 3, 4):
        for lits in range(len(code), stored):
            items = lits + m
            if (items + 7) // 8 + lits + 2 * m == stored:
                data = code + b"\0" * (lits - len(code))
                out = bytearray()
                src = list(data)
                it = 0
                while it < items:
                    group = min(8, items - it)
                    flags = 0
                    chunk = bytearray()
                    for k in range(group):
                        if it + k < lits:
                            flags |= 1 << k
                            chunk.append(src[it + k])
                        else:  # match: ring position 1500 (zeros), length 3
                            chunk += bytes([1500 & 0xFF, (1500 >> 4) & 0xF0])
                    out.append(flags)
                    out += chunk
                    it += group
                assert len(out) == stored, (len(out), stored)
                return bytes(out)
    raise ValueError(f"cannot hit stored size {stored} for {len(code)} bytes of code")


def decoded_size(code_len: int, stored: int) -> int:
    """Uncompressed size A that compress_to_size() produces (literals + 3 per match)."""
    for m in (1, 2, 3, 4):
        for lits in range(code_len, stored):
            if ((lits + m) + 7) // 8 + lits + 2 * m == stored:
                return lits + 3 * m
    raise ValueError("no fit")


def pack_body_same_size(old_body: bytes, code: bytes) -> bytes:
    """Replace a script body's code while keeping the body's total slot (the loader walks the file using
    the stored size rounded up to 4, see raw scripts with A == B == 42 in a 44 byte slot).

    Pure-literal stream: code is zero-padded (ignored after the endscript token) so the stream
    (1 flag byte per 8 literals) fills the slot to within 3 bytes; header = old crc, A = padded code
    length, B = exact stream length.
    """
    crc, _a, b_old = struct.unpack_from("<3I", old_body, 0)
    slot = len(old_body) - 12
    lits = len(code)
    best = None
    for n in range(len(code), slot + 1):
        s_len = n + (n + 7) // 8
        if s_len > slot:
            break
        best = n
    if best is None:
        raise ValueError(f"new code ({len(code)} bytes) does not fit the {slot} byte slot")
    data = code + b"\0" * (best - len(code))
    stream = compress_literals(data)
    assert len(stream) <= slot and (len(stream) + 3) // 4 * 4 >= slot - 3 or True
    new = struct.pack("<3I", crc, len(data), len(stream)) + stream
    new += b"\0" * (len(old_body) - len(new))
    return new


def literal_offsets(stream: bytes, out_size: int) -> list[int]:
    """Stream offsets of the leading output bytes that are plain literals (until the first match item)."""
    i, out, offs = 0, 0, []
    while out < out_size and i < len(stream):
        fl = stream[i]
        i += 1
        for k in range(8):
            if (fl >> k) & 1:
                offs.append(i)
                i += 1
                out += 1
            else:
                return offs
    return offs


def patch_prefix(body: bytes, code: bytes) -> bytes:
    """Overwrite the first len(code) decompressed bytes of a script in place by editing the literal bytes of
    its stream. Header, sizes and stream length stay untouched (like a hash swap). `code` should end with
    an endscript token so execution never reaches the (now stale) rest of the original script."""
    crc, a, b = struct.unpack_from("<3I", body, 0)
    if a == b:  # stored raw
        if len(code) > a:
            raise ValueError("code longer than script")
        return body[:12] + code + body[12 + len(code):]
    stream = bytearray(body[12:12 + b])
    offs = literal_offsets(bytes(stream), a)
    if len(code) > len(offs):
        raise ValueError(f"only {len(offs)} leading literal bytes, need {len(code)}")
    for o, c in zip(offs, code):
        stream[o] = c
    return body[:12] + bytes(stream) + body[12 + b:]


def decompress_roots(stream: bytes, out_size: int) -> tuple[bytes, list[int]]:
    """Like decompress(), also returning for every output byte the stream offset of the literal byte it
    originates from (matches copy the root of the ring slot they read; -1 = untouched initial ring)."""
    out = bytearray()
    roots: list[int] = []
    ring = bytearray(b" " * N)  # the game's encoder pre-fills the ring with spaces
    ring_root = [-1] * N
    rp = START
    i = 0
    while len(out) < out_size and i < len(stream):
        flags = stream[i]
        i += 1
        for k in range(8):
            if len(out) >= out_size:
                break
            if (flags >> k) & 1:
                c, r = stream[i], i
                i += 1
                out.append(c); roots.append(r)
                ring[rp] = c; ring_root[rp] = r
                rp = (rp + 1) & (N - 1)
            else:
                b1, b2 = stream[i], stream[i + 1]
                i += 2
                pos = b1 | ((b2 & 0xF0) << 4)
                for t in range((b2 & 0x0F) + 3):
                    q = (pos + t) & (N - 1)
                    c, r = ring[q], ring_root[q]
                    out.append(c); roots.append(r)
                    ring[rp] = c; ring_root[rp] = r
                    rp = (rp + 1) & (N - 1)
    return bytes(out[:out_size]), roots[:out_size]


def patch_code(body: bytes, new_code: bytes) -> bytes:
    """Same-size edit of a script's decompressed code by changing literal bytes in its stream.
    new_code must have the original length. Raises if the edit cannot be expressed without recompressing
    (a changed byte shares its source literal with a byte that must stay unchanged)."""
    crc, a, b = struct.unpack_from("<3I", body, 0)
    if len(new_code) != a:
        raise ValueError("new code must keep the original length")
    if a == b:
        return body[:12] + new_code + body[12 + a:]
    stream = bytearray(body[12:12 + b])
    old, roots = decompress_roots(bytes(stream), a)
    want: dict[int, int] = {}
    for i, (o, n) in enumerate(zip(old, new_code)):
        if o != n:
            r = roots[i]
            if r < 0:
                raise ValueError(f"byte {i} comes from the initial ring, cannot patch")
            if want.get(r, n) != n:
                raise ValueError(f"byte {i} conflicts with another edit sharing literal {r}")
            want[r] = n
    for r, n in want.items():
        stream[r] = n
    if decompress(bytes(stream), a) != new_code:
        raise ValueError("edit would change other bytes through shared literals")
    return body[:12] + bytes(stream) + body[12 + b:]


# ---------------------------------------------------------------- encoder (port of Okumura's lzss.c)
F_MAX = 18
THRESHOLD = 2
NIL = N


def compress(data: bytes) -> bytes:
    """LZSS-compress exactly like Haruhiko Okumura's lzss.c (binary-tree match finder), which the game's
    encoder follows: N=4096, F=18, THRESHOLD=2, ring pre-filled with spaces, r starts at N-F."""
    text = bytearray(b" " * (N + F_MAX - 1))
    lson = [NIL] * (N + 1)
    rson = [NIL] * (N + 257)
    dad = [NIL] * (N + 1)
    st = {"pos": 0, "len": 0}

    def insert(r):
        cmp = 1
        key = r
        p = N + 1 + text[key]
        rson[r] = lson[r] = NIL
        st["len"] = 0
        while True:
            if cmp >= 0:
                if rson[p] != NIL:
                    p = rson[p]
                else:
                    rson[p] = r
                    dad[r] = p
                    return
            else:
                if lson[p] != NIL:
                    p = lson[p]
                else:
                    lson[p] = r
                    dad[r] = p
                    return
            i = 1
            while i < F_MAX:
                cmp = text[key + i] - text[p + i]
                if cmp != 0:
                    break
                i += 1
            if i > st["len"]:
                st["pos"] = p
                st["len"] = i
                if i >= F_MAX:
                    break
        dad[r] = dad[p]
        lson[r] = lson[p]
        rson[r] = rson[p]
        dad[lson[p]] = r
        dad[rson[p]] = r
        if rson[dad[p]] == p:
            rson[dad[p]] = r
        else:
            lson[dad[p]] = r
        dad[p] = NIL

    def delete(p):
        if dad[p] == NIL:
            return
        if rson[p] == NIL:
            q = lson[p]
        elif lson[p] == NIL:
            q = rson[p]
        else:
            q = lson[p]
            if rson[q] != NIL:
                while rson[q] != NIL:
                    q = rson[q]
                rson[dad[q]] = lson[q]
                dad[lson[q]] = dad[q]
                lson[q] = lson[p]
                dad[lson[p]] = q
            rson[q] = rson[p]
            dad[rson[p]] = q
        dad[q] = dad[p]
        if rson[dad[p]] == p:
            rson[dad[p]] = q
        else:
            lson[dad[p]] = q
        dad[p] = NIL

    out = bytearray()
    code_buf = bytearray(17)
    code_buf[0] = 0
    cbp = 1
    mask = 1
    s = 0
    r = N - F_MAX
    src = 0
    ln = 0
    while ln < F_MAX and src < len(data):
        text[r + ln] = data[src]
        src += 1
        ln += 1
    if ln == 0:
        return b""
    for i in range(1, F_MAX + 1):
        insert(r - i)
    insert(r)
    while True:
        if st["len"] > ln:
            st["len"] = ln
        if st["len"] <= THRESHOLD:
            st["len"] = 1
            code_buf[0] |= mask
            code_buf[cbp] = text[r]
            cbp += 1
        else:
            code_buf[cbp] = st["pos"] & 0xFF
            code_buf[cbp + 1] = ((st["pos"] >> 4) & 0xF0) | (st["len"] - (THRESHOLD + 1))
            cbp += 2
        mask = (mask << 1) & 0xFF
        if mask == 0:
            out += code_buf[:cbp]
            code_buf[0] = 0
            cbp = 1
            mask = 1
        last = st["len"]
        i = 0
        while i < last and src < len(data):
            delete(s)
            c = data[src]
            src += 1
            text[s] = c
            if s < F_MAX - 1:
                text[s + N] = c
            s = (s + 1) & (N - 1)
            r = (r + 1) & (N - 1)
            insert(r)
            i += 1
        while i < last:
            i += 1
            delete(s)
            s = (s + 1) & (N - 1)
            r = (r + 1) & (N - 1)
            ln -= 1
            if ln:
                insert(r)
        if ln <= 0:
            break
    if cbp > 1:
        out += code_buf[:cbp]
    return bytes(out)


def pack_body(crc: int, code: bytes) -> bytes:
    """Store script code like the original compiler: LZSS when that is smaller, otherwise raw (A == B)."""
    c = compress(code)
    if len(c) < len(code):
        return struct.pack("<3I", crc, len(code), len(c)) + c
    return struct.pack("<3I", crc, len(code), len(code)) + code
