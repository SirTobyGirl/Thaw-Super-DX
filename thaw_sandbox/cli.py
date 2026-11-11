"""thaw-super-dx: build a THAW free-skate sandbox with levels from your other Tony Hawk discs.

  python -m thaw_sandbox list  DISC                      levels a source disc offers
  python -m thaw_sandbox build --thaw THAW.iso|.chd --add DISC[:code,code...] [--add ...] --out NEW.iso [--shrink] [--package DIR]

Discs are read only; the output is a new image. Supported sources: see thaw_sandbox/sources.
"""
import argparse
import os
import sys

from thaw_sandbox import build as B, sources

WORK = os.path.expanduser("~/.cache/thaw-super-dx")


def run_build(thaw, wanted, out, work=WORK, shrink=False, package_dir=None, keep_duplicates=False,
              level_scripts=True, unlock_all=True, generated=(), music=False):
    """The whole job (shared by the command line and the GUI) -> [(display name, zone)] added.
    shrink: free skate only (boots to the level list; story, movies, cutscenes and extras removed; music kept).
    Without it THAW is complete and boots normally; the added levels are in free skate."""
    added = B.build(thaw, wanted, out, work, level_scripts=level_scripts, keep_duplicates=keep_duplicates,
                    sandbox=shrink, unlock_all=unlock_all, generated=generated)
    if music:  # mega merge: the chosen games' soundtracks join THAW's playlist
        from thaw_sandbox import iso_build, music as M
        discs = []
        for path, _ in wanted:
            p = B.disc_image(path, work)
            discs.append((p, sources.open_source(p, os.path.join(work, "cache"))))
        if shrink:
            M.merge(out, discs, log=B.log)
        else:  # the full game keeps its old music WAD too: only what still fits a single-layer DVD
            from thaw_sandbox import iso_manager as I
            _, wlen = I.file_extent(out, "/MUSIC/MUSICP.WAD;1")
            room = iso_build.DVD5_SECTORS * 2048 - os.path.getsize(out) - wlen - 8 * 2**20
            if room > 64 * 2**20:
                M.merge(out, discs, log=B.log, max_bytes=room)
            else:
                B.log("music: no room left on a DVD for more songs without shrinking; skipped")
    if shrink:
        from thaw_sandbox import iso_compact
        B.log("shrinking the image ...")
        iso_compact.compact(out)
    if package_dir:
        from thaw_sandbox import package
        package.package(out, package_dir, [n for n, _ in added])
        B.log(f"emulator-ready folder: {package_dir}")
    B.log(f"built {out}: {len(added)} levels added ({', '.join(n for n, _ in added)})")
    return added


def main(argv=None):
    ap = argparse.ArgumentParser(prog="thaw-super-dx", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("gui", help="open the window (also the default with no command)")
    ls = sub.add_parser("list", help="list the levels a source disc offers")
    ls.add_argument("disc")
    ls.add_argument("--work", default=WORK)
    b = sub.add_parser("build", help="build a new THAW image")
    b.add_argument("--thaw", required=True, help="your Tony Hawk's American Wasteland disc (.iso or .chd)")
    b.add_argument("--add", action="append", default=[], metavar="DISC[:codes]",
                   help="source disc, optionally with a comma list of level codes (default: all levels)")
    b.add_argument("--out", required=True, help="the new image to write")
    b.add_argument("--work", default=WORK,
                   help="working folder (extracted .chd images, caches)")
    b.add_argument("--shrink", action="store_true",
                   help="free skate only: boots to the level list; story, movies, cutscenes and extras removed, music "
                        "kept (about 1.9 GB). Without it THAW boots normally and the levels are in free skate")
    b.add_argument("--music", action="store_true",
                   help="also add the chosen games' soundtracks to THAW's playlist (with --shrink: about +1.7 GB)")
    b.add_argument("--no-unlock", action="store_true",
                   help="keep levels locked until visited in story mode (default: all unlocked; ignored with --shrink)")
    b.add_argument("--package", metavar="DIR",
                   help="also make an emulator-ready folder (image, Linux PCSX2 launcher, Android notes)")
    b.add_argument("--generate", action="append", default=[], metavar="LOCATION[;RADIUS[;NAME[;LAYOUT.json]]]",
                   help="generate a level from a real place (OpenStreetMap + elevation, downloaded): a plus code "
                        "(9C6WQCGF+QP, or QCGF+QP Durham) or 'lat, lon'; radius in metres (default 150)")
    b.add_argument("--keep-duplicates", action="store_true",
                   help="import a level from every chosen game even when a newer game remade it (default: newest only)")
    b.add_argument("--no-level-scripts", action="store_true", help="leave the levels' own scripts out")
    a = ap.parse_args(argv)
    if a.cmd in (None, "gui"):
        from thaw_sandbox import gui
        return gui.main()
    if a.cmd == "list":
        s = sources.open_source(B.disc_image(a.disc, a.work), os.path.join(a.work, "cache"))
        print(f"{s.GAME}:")
        for code, name in s.levels():
            print(f"  {code:5} {name}")
        return 0
    wanted = []
    for spec in a.add:
        path, _, codes = spec.rpartition(":") if os.path.exists(spec.rpartition(":")[0] or "\0") else (spec, "", "")
        wanted.append((path, [c for c in codes.split(",") if c] or None))
    gen = []
    if a.generate:
        from thaw_sandbox.mapgen import real_place
        for spec in a.generate:
            parts = spec.split(";")
            gen.append(real_place(parts[0], float(parts[1]) if len(parts) > 1 and parts[1] else 150.0,
                                  parts[2] if len(parts) > 2 and parts[2] else None, a.work,
                                  parts[3] if len(parts) > 3 and parts[3] else None))
    run_build(a.thaw, wanted, a.out, a.work, a.shrink, a.package, a.keep_duplicates, not a.no_level_scripts,
              not a.no_unlock, gen, a.music)
    return 0


if __name__ == "__main__":
    sys.exit(main())
