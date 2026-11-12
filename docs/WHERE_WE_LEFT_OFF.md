# Where we left off (2026-11-12)

A pick-up note for the next session. The README says what the tool does; docs/FORMATS.md has the format notes.

## State

Released: v0.1.0 (Linux executable). Everything below is committed on `main` but not in a release yet.

| Source | Levels | State |
|---|---|---|
| THUG2 | 15 | play |
| THUG | 12 (+3 remade in THUG2) | play |
| THPS4 | 9 | play; render fix (XYZ2 vertex tags) |
| THPS3 | 12 (Airport/Canada/LA come from THUG2 when both are given) | play; gaps, triggers, blends, objects (static) |
| Disney's Extreme Skate Adventure | 10 | play |
| Project 8 | 10 areas | play; **rails don't work**; some areas get a generated start point |
| Proving Ground | 10 areas | **parked** (recognised, not offered): see below |
| THUG Pro custom levels (.zip) | any | experimental (Skate Heaven 2x tested) |

Builder: window with **Scan a folder…** (CLI `--scan FOLDER`), per-build log at
`~/.cache/thaw-super-dx/last_build.log`, images may grow past DVD size (warning only; PCSX2 reads them).

## Open issues and next steps

1. **Project 8 rails don't work** (user report). Rails come from `rails.build(node_items)` in
   `level_convert.assemble_level`; compare a P8 zone's own `.rnb` with the rebuilt one first.
2. **THPS3 geometry is off in places, plus minor adjustments** (user report; which levels and where still to
   collect). Skies are not carried over yet (`levels\<code>_sky\<code>_sky.bsp` in `pre\<code>.pre`; THAW skies
   are `skies\<name>\<name>.pak.ps2` chosen by the level's `Sky`). Level objects are static and render only.
3. **Proving Ground** (`thaw_sandbox/sources/pg.py` has the plan): the city areas use a unit ~12x THAW's, about half
   the leaves use V4_32 absolute fixed-point positions (draw as shards), Baltimore crashed once. Rebuild like THPS3:
   decode leaves to triangles, scale x12, rewrite geometry/collision, scale nodes.
4. **Project 8 start points**: areas without a restart use a pedestrian / rail spot; pick a better one. Joining the
   areas into one streamed city fits the "level mash" idea.
5. **Release 0.2.0** with a new executable (`packaging/build_linux.sh`), once the above is tested.
6. Parked from earlier: classic mode rework / Super DX / Free Roam (`thaw_sandbox/classic.py`, off), Windows .exe
   (needs a Windows build machine and a fallback for `cp --reflink`), online, decks, THPS4 detail surfaces
   (Shipyard wall, London tree base), custom levels look darker than in THUG Pro, music untested by ear.

## Working setup

- Python: `.venv/bin/python` with `PYTHONPATH=.` from the repo root (Pillow for the harness).
- Discs live in `iso/` (not in git). Quick builds:
  `python -m thaw_sandbox build --scan iso --out _workspace/build/x.iso --work _workspace/e2e --shrink`
  or `--thaw <THAW> --add <disc>[:codes]`; `python -m thaw_sandbox list <disc>`.
- Testing: `harness/play_check.sh IMAGE POSITION NAME` (shrunk images: added levels start at list position 14;
  `KEEP_GOING=1` to play through crash markers). Setup in harness/README.md, local paths in
  `harness/env.local.sh`.
- Disk: test images, extracted discs and screenshots are regenerable; they were cleared on 2026-11-12. The first
  build after that re-extracts THAW's .chd (needs `chdman`, a few minutes).
