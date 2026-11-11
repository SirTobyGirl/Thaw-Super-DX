"""A small compiler for THAW script bytecode, and helpers to take token streams apart.

    code = compile_script('''
        if GameModeEquals is_classic
            AddGoal_HighScore { zone = 'z_dj' score = 1000 pos = vec(1.0, 2.0, 3.0) <...> }
        else
            foo bar = <baz>
        endif
    ''')

One statement per line (a line may end inside { } or [ ]: every line break becomes an EOL token, as in the
game's own scripts). Words are name tokens; 12 an integer; 1.5 a float; 'text' a string; vec(x, y, z) a vector;
pair(x, y) a pair of floats; <name> an argument reference; <...> all arguments; #1a2b3c4d a raw name checksum.
if / else / endif compile to the fast forms with their jump offsets (qb_tokens: fastif lands just past the
fastelse token or the endif token, fastelse just past endif). begin / repeat / break / return / not and the
operators ( ) + - * / . , : = < > are their plain tokens. No switch, no random.
"""
import re
import struct

from thaw_sandbox import qb_tokens as T
from thaw_sandbox.qb_parser import qbcrc

EOL, ENDSCRIPT = b"\x01", b"\x24"
SYM = {"{": 3, "}": 4, "[": 5, "]": 6, "=": 7, ".": 8, ",": 9, "-": 10, "+": 11, "/": 12, "*": 13, "(": 14,
       ")": 15, "<": 18, "<=": 19, ">": 20, ">=": 21, ":": 66, "|": 50, "&": 51, "<...>": 44}
WORD = {"begin": 32, "repeat": 33, "break": 34, "return": 41, "not": 57, "endif": 40}
JUMPS = {46, 47, 55, 64, 65, 60, 61, 62, 63, 71, 72, 73}  # tokens with offsets (or switch structure)

_LEX = re.compile(r"""
    (?P<ws>[ \t]+) | (?P<nl>\n) | (?P<str>'(?:[^'\\]|\\.)*') |
    (?P<vec>(?:vec|pair)\([^)]*\)) | (?P<all><\.\.\.>) | (?P<arg><[A-Za-z_][A-Za-z0-9_]*>) |
    (?P<raw>\#[0-9a-fA-F]{8}) | (?P<num>-?\d+\.\d*(?:[eE]-?\d+)?|-?\d+) | (?P<sym><=|>=|[{}\[\]=.,\-+/*():|&<>]) |
    (?P<word>[A-Za-z_][A-Za-z0-9_]*)
""", re.X)


def name(n) -> bytes:
    return b"\x16" + struct.pack("<I", n if isinstance(n, int) else qbcrc(n))


def integer(v) -> bytes:
    return b"\x17" + struct.pack("<i", v)


def real(v) -> bytes:
    return b"\x1a" + struct.pack("<f", v)


def string(s) -> bytes:
    b = (s.encode("latin1") if isinstance(s, str) else s) + b"\0"
    return b"\x1b" + struct.pack("<I", len(b)) + b


def vector(x, y, z) -> bytes:
    return b"\x1e" + struct.pack("<3f", x, y, z)


def pair(x, y) -> bytes:
    return b"\x1f" + struct.pack("<2f", x, y)


def _lex(text):
    pos = 0
    while pos < len(text):
        m = _LEX.match(text, pos)
        if not m:
            raise SyntaxError(f"cannot read script text at: {text[pos:pos + 30]!r}")
        pos = m.end()
        k = m.lastgroup
        if k != "ws":
            yield k, m.group()


def _if(cond, then, other=None):
    """EOL fastif cond then [EOL fastelse other] EOL endif; offsets are relative to their own field."""
    if other is None:
        return EOL + b"\x47" + struct.pack("<h", 2 + len(cond) + len(then) + 2) + cond + then + EOL + b"\x28"
    out = EOL + b"\x47" + struct.pack("<h", 2 + len(cond) + len(then) + 4) + cond + then
    return out + EOL + b"\x48" + struct.pack("<h", 2 + len(other) + 2) + other + EOL + b"\x28"


def if_block(cond: bytes, then: bytes, other: bytes | None = None) -> bytes:
    """An if statement from compiled pieces (cond: the condition's tokens; then/other: whole statements, each
    starting with its EOL)."""
    return _if(cond, then, other)


def compile_block(text: str) -> bytes:
    """Statements (each led by an EOL token), without the script terminator."""
    lines, cur = [], []
    for k, v in _lex(text.strip() + "\n"):
        if k == "nl":
            if cur:
                lines.append(cur)
            cur = []
        else:
            cur.append((k, v))

    def tokens(line):
        out = bytearray()
        for k, v in line:
            if k == "word":
                out += bytes([WORD[v]]) if v in WORD else name(v)
            elif k == "num":
                out += real(float(v)) if ("." in v or "e" in v.lower()) else integer(int(v))
            elif k == "str":
                out += string(re.sub(r"\\(.)", r"\1", v[1:-1]))
            elif k == "vec":
                kind, body = v.split("(", 1)
                nums = [float(x) for x in body[:-1].split(",")]
                out += vector(*nums) if kind == "vec" else pair(*nums)
            elif k == "arg":
                out += b"\x2d" + name(v[1:-1])
            elif k == "all":
                out.append(44)
            elif k == "raw":
                out += name(int(v[1:], 16))
            else:
                out.append(SYM[v])
        return bytes(out)

    def block(i, stop):
        out = bytearray()
        while i < len(lines):
            head = lines[i][0][1] if lines[i][0][0] == "word" else None
            if head in stop:
                return bytes(out), i
            if head == "if":
                then, j = block(i + 1, ("else", "endif"))
                other = None
                if lines[j][0][1] == "else":
                    other, j = block(j + 1, ("endif",))
                out += _if(tokens(lines[i][1:]), then, other)
                i = j + 1
            else:
                out += EOL + tokens(lines[i])
                i += 1
        if stop:
            raise SyntaxError("if without endif")
        return bytes(out), i
    return block(0, ())[0]


def compile_script(text: str) -> bytes:
    return compile_block(text) + EOL + ENDSCRIPT


# ---- taking token streams apart ----------------------------------------------------------------------------------

def name_of(code, tok):
    return struct.unpack_from("<I", code, tok.off + 1)[0] if tok.id == 22 else None


def matching(toks, i):
    """Index of the token closing the bracket opened at toks[i] ({ [ or ( )."""
    pairs = {3: 4, 5: 6, 14: 15}
    o, c, depth = toks[i].id, pairs[toks[i].id], 0
    for j in range(i, len(toks)):
        if toks[j].id == o:
            depth += 1
        elif toks[j].id == c:
            depth -= 1
            if depth == 0:
                return j
    raise ValueError("unbalanced brackets")


def fields(code, toks):
    """Top-level entries of a struct body (the tokens between its braces): [(key crc or None, value bytes)].
    A value is one token or a bracketed group; flags (bare names) come as (None, name token bytes)."""
    out, i = [], 0
    toks = [t for t in toks if t.id not in (1, 2)]

    def value(i):
        if toks[i].id in (3, 5, 14):
            j = matching(toks, i)
            return code[toks[i].off:toks[j].end], j + 1
        if toks[i].id == 45:  # arg + name
            return code[toks[i].off:toks[i + 1].end], i + 2
        return code[toks[i].off:toks[i].end], i + 1
    while i < len(toks):
        if toks[i].id == 22 and i + 1 < len(toks) and toks[i + 1].id == 7:
            v, j = value(i + 2)
            out.append((name_of(code, toks[i]), v))
            i = j
        else:
            v, i = value(i)
            out.append((None, v))
    return out


def struct_fields(value: bytes):
    """fields() of a compiled struct value '{ ... }'."""
    toks = T.tokenize(value)
    assert toks[0].id == 3 and toks[-1].id == 4
    return fields(value, toks[1:-1])


def build_struct(entries, eol=True) -> bytes:
    """{ key = value ... } from [(key crc/name or None, value bytes)]; one entry per line when eol."""
    sep = EOL if eol else b""
    out = bytearray(b"\x03")
    for k, v in entries:
        out += sep + (name(k) + b"\x07" if k is not None else b"") + v
    return bytes(out + sep + b"\x04")
