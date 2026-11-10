"""Source games: read levels from the user's own discs.

Each adapter: GAME (name), detect(iso) -> bool, Source(iso, cache_dir).levels() -> [(code, display name)],
.level_files(code) -> {"geom", "col", "tex", "qb", "scripts"} bytes, .resolve_texture_refs(textures).
"""
from thaw_sandbox.sources import thps4, thug, thug2

ADAPTERS = [thug2, thug, thps4]


def open_source(iso, cache_dir):
    for a in ADAPTERS:
        if a.detect(iso):
            return a.Source(iso, cache_dir)
    raise ValueError(f"{iso}: not a supported source game (supported: {', '.join(a.GAME for a in ADAPTERS)})")


def identity(source, code):
    """Cross-game identity of a level: the original game's id for remakes, else '<game>:<code>'."""
    return getattr(source, "ORIGIN", {}).get(code) or f"{source.GAME.lower()}:{code}"


def dedupe(chosen):
    """chosen: [(source, [(code, name)])] -> (kept in the same shape, [(skipped source, code, name, kept source)]).
    A level present in several games (e.g. THPS3's Airport, remade in THUG2) is imported once, from the newest
    engine (source.GENERATION)."""
    best = {}
    for s, levels in chosen:
        for code, _name in levels:
            k = identity(s, code)
            if k not in best or s.GENERATION > best[k][0].GENERATION:
                best[k] = (s, code)
    kept, skipped = [], []
    for s, levels in chosen:
        mine = []
        for code, name in levels:
            b = best[identity(s, code)]
            if b == (s, code):
                mine.append((code, name))
            else:
                skipped.append((s, code, name, b[0]))
        kept.append((s, mine))
    return kept, skipped
