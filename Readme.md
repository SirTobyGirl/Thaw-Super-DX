# THAW Super DX

Adds levels from older Tony Hawk games into **Tony Hawk's American Wasteland** (PS2) and gives you a new disc image
to play in an emulator such as PCSX2.

You bring your own discs. The tool reads them and writes a new image; your discs are never changed, and no game
data is included in this project.

## Features

- **Levels from five games**: Underground 2, Underground, Pro Skater 4, Pro Skater 3 and Disney's Extreme Skate
  Adventure, added to THAW's
  High Score / Free Skate level list with their textures, collision, rails and start points
- **Pick what you want**: whole games or single levels; a level remade by a newer game (e.g. THPS3's Airport in
  THUG2) is added once, from the newest version
- **Shrink**: free skate only. Boots straight to the level list, with story, movies and cutscenes removed
  (about 1.9 GB). Without it the full game stays and boots as normal; with many levels and soundtracks the
  image can grow past DVD size (up to ~7 GB), which emulators handle fine
- **Unlock all levels** (on by default)
- **Soundtracks**: the chosen games' songs join THAW's playlist
- **Custom levels** (experimental): THUG Pro level downloads (.zip), added like a disc with `--add level.zip`
- **Real places** (experimental): generate a level from a location using OpenStreetMap and elevation data

## Getting started

You need your THAW disc (NTSC-U, `.iso` or `.chd`) plus the discs you want levels from:
THUG2 (SLUS-20965), THUG (SLUS-20731), THPS4 (SLUS-20504), THPS3 (SLUS-20013), Disney's Extreme Skate
Adventure (SLUS-20607).
`.chd` files need MAME's `chdman` installed; `.iso` files work as they are.

**Linux**: download `thaw-super-dx-linux-x86_64` from [Releases](../../releases), make it executable and run it:

```
chmod +x thaw-super-dx-linux-x86_64 && ./thaw-super-dx-linux-x86_64
```

Pick your discs (or **Scan a folder…** to find them all at once), tick the levels and options, press Build. A command line is also available
(`./thaw-super-dx-linux-x86_64 build --help`; `build --scan FOLDER --out NEW.iso` uses every disc in a folder). Windows is not available yet.

**From source** (Python 3.12 with Tkinter, nothing else to install): `./thaw-super-dx.sh` or `python -m thaw_sandbox`.

## Levels

| Game | Levels | State |
|---|---|---|
| Underground 2 | Training, Boston, Barcelona, Berlin, Australia, New Orleans, Skatopia, Pro Skater, The Triangle, Los Angeles, School, Philly, Downhill Jam, Canada, Airport | All load and play |
| Underground | New Jersey, Manhattan, Tampa, San Diego, Hawaii, Vancouver, Slam City Jam, Moscow, Hotter Than Hell, Old Hangar, School II, Venice | All load and play |
| Pro Skater 4 | College, San Francisco, Alcatraz, Kona, Shipyard, London, Zoo, Carnival, Chicago | All load and play |
| Pro Skater 3 | Foundry, Rio, Suburbia, Skater Island, Tokyo, Cruise Ship, Warehouse, Burnside, Roswell (+ Canada, Airport, Los Angeles if THUG2 isn't given) | All load and play, with gaps and level objects (static) |
| Disney's Extreme Skate Adventure | Andy's Room, Pizza Planet, Zurg's World, Jungle Treehouse, Human Camp, Clayton's Ship, Pride Rock, Elephant Graveyard, The Canyon, Olliewood | New |

Underground's Old School, Old Downhill Jam and Old Philly come from Underground 2's newer versions when both discs
are given.

## Current state

Levels are skateable: geometry, textures, collision, rails, grinding and start points work. Not carried over yet:
goals, level objects (cars, peds, moving parts) and most level scripts.

Known issues:

- Some texture glitches (Training, Boston, Australia, Downhill Jam, The Triangle, Airport, and a few THPS4 surfaces)
- Geometry errors in New Orleans, Tampa, Barcelona (bridge at the start) and Old Hangar (also missing helicopter)
- Hawaii tree leaves missing, Hotter Than Hell ramps at the start, School II gym doors closed
- Pro Skater 3: original skies not yet carried over; level objects (crates, glass, cars) don't move or break
- Music import is untested by ear

## For modders

The code that does the work is reusable on its own:

- **[docs/FORMATS.md](docs/FORMATS.md)**: what we decoded about THAW's PS2 files (archives, compressed scripts,
  textures, geometry, collision, rails, gaps, node tables) and the level formats of THUG2, THUG, THPS4 and THPS3
- **`thaw_sandbox/`**: Python readers and writers for those formats (e.g. `lzss`, `qb_file`, `qb_tokens`,
  `qb_code` (a small script compiler), `thaw_tex`, `geom`, `col`, `rails`, `rw`), plus the converters
- **[harness/](harness/README.md)**: automated PCSX2 testing (virtual pad, screenshots, freeze and crash
  detection, bisect tools, save-state readers, a Ghidra script)

Built with help from [neversoft-multitool](https://github.com/slfx77/neversoft-multitool),
[io_thps_scene](https://github.com/denetii/io_thps_scene), [LegacyTHPS](https://github.com/DCxDemo/LegacyTHPS),
[QScript](https://github.com/cuckydev/QScript), [NeverScript](https://github.com/byxor/NeverScript) and
[WAD-Tool](https://github.com/DCxDemo/WAD-Tool) as references.

## Legal

Not affiliated with Activision or Neversoft. Use only discs you own. OpenStreetMap data © OpenStreetMap contributors
(ODbL); elevation EU-DEM / SRTM via OpenTopoData.
