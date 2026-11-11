# THAW Super DX

Adds levels from older Tony Hawk games into **Tony Hawk's American Wasteland** (PS2) and gives you a new disc image
to play in an emulator such as PCSX2.

You bring your own discs. The tool reads them and writes a new image; your discs are never changed, and no game
data is included in this project.

## Features

- **Levels from four games**: Underground 2, Underground, Pro Skater 4 and Pro Skater 3, added to THAW's
  High Score / Free Skate level list with their textures, collision, rails and start points
- **Pick what you want**: whole games or single levels; a level remade by a newer game (e.g. THPS3's Airport in
  THUG2) is added once, from the newest version
- **Shrink**: free skate only. Boots straight to the level list, with story, movies and cutscenes removed
  (about 1.9 GB). Without it the full game stays and boots as normal
- **Unlock all levels** (on by default)
- **Soundtracks**: the chosen games' songs join THAW's playlist
- **Real places** (experimental): generate a level from a location using OpenStreetMap and elevation data

## Getting started

You need your THAW disc (NTSC-U, `.iso` or `.chd`) plus the discs you want levels from:
THUG2 (SLUS-20965), THUG (SLUS-20731), THPS4 (SLUS-20504), THPS3 (SLUS-20013).
`.chd` files need MAME's `chdman` installed; `.iso` files work as they are.

**Linux**: download `thaw-super-dx-linux-x86_64` from [Releases](../../releases), make it executable and run it:

```
chmod +x thaw-super-dx-linux-x86_64 && ./thaw-super-dx-linux-x86_64
```

Pick your discs, tick the levels and options, press Build. A command line is also available
(`./thaw-super-dx-linux-x86_64 build --help`). Windows is not available yet.

**From source** (Python 3.12, `pip install pycdlib`): `./thaw-super-dx.sh` or `python -m thaw_sandbox`.

## Levels

| Game | Levels | State |
|---|---|---|
| Underground 2 | Training, Boston, Barcelona, Berlin, Australia, New Orleans, Skatopia, Pro Skater, The Triangle, Los Angeles, School, Philly, Downhill Jam, Canada, Airport | All load and play |
| Underground | New Jersey, Manhattan, Tampa, San Diego, Hawaii, Vancouver, Slam City Jam, Moscow, Hotter Than Hell, Old Hangar, School II, Venice | All load and play |
| Pro Skater 4 | College, San Francisco, Alcatraz, Kona, Shipyard, London, Zoo, Carnival, Chicago | All load and play |
| Pro Skater 3 | Foundry, Rio, Suburbia, Skater Island, Tokyo, Cruise Ship, Warehouse, Burnside, Roswell (+ Canada, Airport, Los Angeles if THUG2 isn't given) | New: Foundry, Cruise Ship, Skater Island tested; the rest untested |

Underground's Old School, Old Downhill Jam and Old Philly come from Underground 2's newer versions when both discs
are given.

## Current state

Levels are skateable: geometry, textures, collision, rails, grinding and start points work. Not carried over yet:
goals, level objects (cars, peds, moving parts) and most level scripts.

Known issues:

- Some texture glitches (Training, Boston, Australia, Downhill Jam, The Triangle, Airport, and a few THPS4 surfaces)
- Geometry errors in New Orleans, Tampa, Barcelona (bridge at the start) and Old Hangar (also missing helicopter)
- Hawaii tree leaves missing, Hotter Than Hell ramps at the start, School II gym doors closed
- Pro Skater 3: glowing / see-through surfaces draw solid, Warehouse, Burnside and Roswell miss some textures
- Music import is untested by ear

## Legal

Not affiliated with Activision or Neversoft. Use only discs you own. OpenStreetMap data © OpenStreetMap contributors
(ODbL); elevation EU-DEM / SRTM via OpenTopoData.
