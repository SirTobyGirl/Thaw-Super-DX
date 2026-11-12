"""Source games: read levels from the user's own discs.

Each adapter: GAME (name), detect(iso) -> bool, Source(iso, cache_dir).levels() -> [(code, display name)],
.level_files(code) -> {"geom", "col", "tex", "qb", "scripts"} bytes, .resolve_texture_refs(textures).
"""
import os

from thaw_sandbox.sources import desa, p8, pg, thps3, thps4, thug, thug2

ADAPTERS = [p8, thug2, thug, thps4, thps3, desa]
# recognised but not offered yet: their levels load but are not usable (sources/pg.py explains)
PARKED = [pg]


def open_source(iso, cache_dir):
    for a in ADAPTERS:
        if a.detect(iso):
            return a.Source(iso, cache_dir)
    raise ValueError(f"{iso}: not a supported source game (supported: {', '.join(a.GAME for a in ADAPTERS)})")


def open_any(path, work_dir):
    """A disc image (.iso/.chd, via build.disc_image) or a custom level download (.zip or folder with a
    .level.json: THUG Pro levels)."""
    import os
    from thaw_sandbox.sources import thugpro
    if thugpro.is_mod(path):
        return thugpro.Source(path)
    from thaw_sandbox.build import disc_image
    return open_source(disc_image(path, work_dir), os.path.join(work_dir, "cache"))


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


# .chd images cannot be identified without extracting them (minutes each): their file names are matched instead
# (first match wins; the window's disc check extracts and verifies them afterwards)
CHD_NAME_HINTS = (("american wasteland", "THAW"), ("thaw", "THAW"), ("underground 2", "THUG2"), ("thug2", "THUG2"),
                  ("underground", "THUG"), ("thug", "THUG"), ("pro skater 4", "THPS4"), ("thps4", "THPS4"),
                  ("pro skater 3", "THPS3"), ("thps3", "THPS3"), ("extreme skate", "Disney Extreme Skate Adventure"),
                  ("project 8", "Project 8"))
DISC_EXTS = (".iso", ".chd")


def scan_folder(folder, depth=2):
    """Find the supported discs in a folder (and its subfolders, depth levels). -> (found {"THAW" or adapter GAME:
    path}, notes [str]): .iso files by their disc serial, .chd files by name; the first disc of each game wins."""
    from thaw_sandbox import build as B
    found, notes, paths = {}, [], []
    for root, dirs, files in os.walk(folder):
        if root[len(folder):].count(os.sep) >= depth:
            dirs[:] = []
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        paths += [os.path.join(root, f) for f in sorted(files) if f.lower().endswith(DISC_EXTS)
                  and not f.startswith(".")]
    for p in paths:
        name = os.path.basename(p).lower()
        if name.endswith(".chd"):
            key = next((g for hint, g in CHD_NAME_HINTS if hint in name), None)
            how = "by name"
        else:
            try:
                key = "THAW" if B.is_thaw(p) else next((a.GAME for a in ADAPTERS if a.detect(p)), None)
                parked = None if key else next((a.GAME for a in PARKED if a.detect(p)), None)
            except Exception:
                key = parked = None
            if parked:
                notes.append(f"{parked}: {os.path.basename(p)} (recognised; its levels are not supported yet)")
                continue
            how = "by its serial"
        if key is None:
            notes.append(f"not a supported game: {os.path.basename(p)}")
        elif key in found:
            notes.append(f"another {key} disc, not used: {os.path.basename(p)}")
        else:
            found[key] = p
            notes.append(f"{key}: {os.path.basename(p)} ({how})")
    return found, notes
