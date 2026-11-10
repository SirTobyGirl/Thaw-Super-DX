"""Source games: read levels from the user's own discs.

Each adapter: GAME (name), detect(iso) -> bool, Source(iso, cache_dir).levels() -> [(code, display name)],
.level_files(code) -> {"geom", "col", "tex", "qb", "scripts"} bytes, .resolve_texture_refs(textures).
"""
from thaw_sandbox.sources import thps4, thug2

ADAPTERS = [thug2, thps4]


def open_source(iso, cache_dir):
    for a in ADAPTERS:
        if a.detect(iso):
            return a.Source(iso, cache_dir)
    raise ValueError(f"{iso}: not a supported source game (supported: {', '.join(a.GAME for a in ADAPTERS)})")
