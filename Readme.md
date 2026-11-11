THAW Super DX - using the tool
==============================
You need: your own Tony Hawk's American Wasteland (NTSC-U, .iso or .chd) and the discs you want levels from
(supported: THUG2 SLUS-20965, THUG SLUS-20731, THPS4 SLUS-20504). Python 3 with the packages in .venv; chdman for .chd input.

The window (pick each disc and its levels, options, Build):

  ./thaw-super-dx.sh            (or: python -m thaw_sandbox)

One row per game: American Wasteland (required), then Underground 2, Underground and Pro Skater 4 - fill in the
games you want levels from and leave the rest empty. Each disc is checked when chosen (a disc in the wrong row is
named; a .chd is extracted once). Levels... ticks single levels (all by default); a level that a newer chosen game
remade is marked and added once, from the newest game.

Levels from real places (needs internet): type a plus code (9C6WQCGF+QP, or QCGF+QP Durham) or "lat, lon",
pick a size (200-400 m square) and Add place. At build time the tool downloads OpenStreetMap features and elevation
for that square and generates a level: hills, roads with grindable kerbs, cobbled footways, buildings from their
footprints, steps with handrails, benches and walls as ledges, quarter pipes along the edges; textures come from
your American Wasteland disc. Map data (c) OpenStreetMap contributors (ODbL); elevation EU-DEM / SRTM via OpenTopoData.

Options:
  Shrink the image   off (default): the full game - boots as normal with story mode, classic mode, movies and
                     everything else; the new levels are in High Score / Free Skate. The image grows by the levels
                     (it must stay within a single-layer DVD: about 40 levels).
                     on: free skate only - boots straight to the level list; story, classic, movies, cutscenes
                     and extras are removed, music stays. About 1.9 GB.
  Unlock all levels  on (default): every level is open in free skate from the start. Off: THAW's levels open as
                     story mode visits them; the added levels are always open. Always on when shrinking.
  Emulator-ready folder: the image next to a PCSX2 launcher and notes.

Command line:

  python -m thaw_sandbox list  "THPS4.iso"                      # levels a disc offers (codes + names)
  python -m thaw_sandbox build --thaw "THAW.chd" \
         --add "THUG2.iso" --add "THPS4.iso:sch,alc" \
         --out "THAW Super DX.iso" [--shrink] [--package DIR]

  --add DISC[:codes]  all levels of DISC, or only the listed codes
  --generate "LOCATION[;RADIUS[;NAME]]"  generate a level from a real place (plus code or "lat, lon"; radius m)
  --keep-duplicates   a level that a newer game remade (e.g. THPS3's Airport, in THUG2) is normally imported once,
                      from the newest engine; this keeps every version
  --shrink            free skate only (boots to the level list; story, movies, cutscenes, extras removed; music
                      kept; about 1.9 GB). Without it the full game boots as normal, levels in free skate
  --no-unlock         THAW's levels open as story mode visits them (default: all unlocked; ignored with --shrink)
  --package DIR       emulator-ready folder: the image, play-linux.sh (PCSX2) and Android notes
Your discs are never modified.

(Original project blueprint below.)

THAW Free Skate Sandbox: ROM Patcher & Injector
An Automation Blueprint for Claude Code

Project Vision
This project is a Python-based ROM hacking and automation CLI tool designed to transform a vanilla Tony Hawk's American Wasteland (THAW) PS2 ISO into a lightweight "Free Skate Sandbox."

The tool will programmatically strip away Story Mode, Classic Mode, and Create-A-Skater from the game's UI and scripting logic, leaving only a Free Skate menu. It will then inject level assets (.scn, .col, .tex) from previous 6th-generation Neversoft titles (THPS3, THPS4, THUG1, THUG2) and rebuild a fresh, playable "Super ISO" optimized for AetherSX2/NetherSX2 on Android handhelds (specifically the AYN Odin 2 and AYN Thor).

Execution Environment Context
Host OS: Bazzite Linux (Fedora Silverblue-based)

AI Toolchain: Orchestrated via Claude Code, routed alongside a local multi-agent Llama + LiteLLM pipeline.

Target Hardware: AYN Odin 2 and AYN Thor (Snapdragon-based ARM64 handhelds running PS2 emulation).

Launch Architecture: The resulting ISO will eventually be launched via a custom Android Jetpack Compose frontend using the AetherSX2 boot intent (ru.playsoftware.aethersx2.boot).

Dependency Toolchain (Active Repositories)
Do not attempt to reverse-engineer Neversoft file headers from scratch. The Python tool must act as a subprocess wrapper around the following active community tools:

Archive Handling (WAD-Tool by DCxDemo): Use github.com/DCxDemo/WAD-Tool to unpack and repack the proprietary PS2 .PAK and .WAD files (specifically scripts.pak and levels.pak).

Script Decompilation (ThpsQScriptEd by DCxDemo): Found within the github.com/DCxDemo/LegacyTHPS repository. Use this to decompile the binary .qb (QueenBee) script files into plaintext for editing, and to recompile them back to binary.

ISO Manipulation (pycdlib): Use the pure-Python pycdlib library to extract and rebuild the PS2 ISO, ensuring the PS2 Logical Block Addressing (LBA) tables and SYSTEM.CNF boot sectors are perfectly preserved.

The user must have a Tony Hawks American Wasteland .iso or .chd format, the other games in the series can be individually selected, so that levels can be pulled from 1 or more games. 

System Architecture & Phased Objectives
Phase 1: Unpacking & Decompilation
The tool must handle the raw I/O of the PS2 ISO and Neversoft's proprietary archives.

ISO Extraction: Mount/extract the vanilla THAW PS2 .iso to a local _workspace directory using pycdlib.

PAK Extraction: Execute WAD-Tool via Python subprocess to unpack scripts.pak and levels.pak.

Decompilation: Execute ThpsQScriptEd to decompile the .qb binary scripts into plaintext (.txt or .q) for modification.

Phase 2: Logic Stripping (The UI Lobotomy)
The tool must parse and modify the decompiled .qb scripts using regex or AST string manipulation to remove narrative bloat.

Menu Modification (mainmenu.qb / levelselect.qb):

Delete all UI nodes, array entries, and event listeners associated with Story Mode, Classic Mode, and CAS (Create-A-Skater).

Ensure the "Free Skate" button is the primary active element and routes directly to the level selection array.

State Logic: Remove logic triggers that attempt to load story-specific cutscenes, ped spawns, or mission variables upon level initialization.

Phase 3: Asset Injection
The tool must integrate external level files and register them within THAW's engine.

File Migration: Accept a target directory of extracted assets from older games (THPS3-THUG2). Copy the respective .scn (geometry), .col (collision), and .tex (textures) files into THAW's extracted levels/ directory structure.

Array Registration: Dynamically append the injected levels to THAW's level_details.qb (or the equivalent Free Skate level array).

Spawn Coordinates: Inject a default skater spawn coordinate (0, 50, 0) in skater_start_positions for the newly added levels to prevent engine crashes on load.

Phase 4: Repacking & ISO Rebuilding
The tool must clean up the workspace and generate the final playable ROM.

Recompilation: Execute ThpsQScriptEd to recompile the modified plaintext .qb scripts back into binary format.

PAK Rebuilding: Execute WAD-Tool to repack the modified scripts.pak and levels.pak archives, overwriting the vanilla files in the workspace.

ISO Generation: Use pycdlib (or a subprocess call to mkisofs with PS2 flags -iso-level 1 -no-emul-boot) to compile the workspace back into THAW_FreeSkate_Sandbox.iso.

Cleanup: Purge the temporary extraction folders to maintain idempotency.

Claude's Directives & Constraints
Strict File Operations: Do not attempt to write game physics, render logic, or C++ hooks. This is strictly a file I/O, binary extraction, and string-manipulation project.

Modular Codebase: Structure the Python tool with clear separation of concerns: iso_manager.py, pak_wrapper.py, qb_parser.py, and injector.py.

QueenBee Syntax: When generating regex or parsing logic for .qb files, account for Neversoft's specific array structuring and checksum hashing conventions.

Safety: Ensure the build script can be run multiple times safely without corrupting the base vanilla ISO. Always copy the vanilla ISO to a staging area before operations begin.
