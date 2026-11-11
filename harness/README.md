# Test harness

Scripts that play built images in PCSX2 without a person: a virtual gamepad presses the buttons, PCSX2 saves
screenshots, and frame differences plus the emulator log tell whether a level loaded, runs, froze or crashed.
Also here: bisect tools for finding the leaf / script / node that breaks a level, QB dumpers and save-state readers.

Linux only. Run everything from the repository root.

## Setup

1. **PCSX2 Flatpak** (`flatpak install flathub net.pcsx2.PCSX2`) with your own PS2 BIOS, run once by hand.
2. **Virtual pad**: `harness/vpad_daemon.py` creates an Xbox 360 pad through `/dev/uinput`; your user needs write
   access to it (e.g. a udev rule giving the `input` group `rw`, and your user in that group).
3. **PCSX2 settings** (start the pad first: `. harness/env.sh; vpad_start`):
   - Controller port 1: the "Microsoft X-Box 360 pad" (SDL), default Xbox mapping
   - Hotkeys: *Save Screenshot* = Guide button, *Save State to Selected Slot* = Select + R1
   - Graphics: native resolution (1x); turning off "pause when focus is lost" helps
   - Logging: enable the emulator log (system console / file log)
4. **Python**: the project's `.venv` with Pillow (`.venv/bin/pip install pillow`; `zstandard` and `capstone` for
   the save-state tools).
5. **Paths**: `harness/env.sh` has defaults for the Flatpak. If your screenshots or BIOS live elsewhere, create
   `harness/env.local.sh` (not in git), for example:
   ```
   PCSX2_SNAPS=$HOME/Emulation/storage/pcsx2/snaps
   PCSX2_FS="$HOME/Emulation"
   ```

## Main scripts

| Script | What it does |
|---|---|
| `run_level.sh ISO N NAME` | boot a shrunk image (level list), go N entries down, load, screenshot |
| `run_level_normal.sh ISO N NAME` | the same through the full game's main menu |
| `play_check.sh ISO N NAME` | load, play ~60 s of mixed input; prints OK / FROZEN / CRASH with crash PCs |
| `live_check.sh`, `session_check.sh` | quick liveness check; one-session tour with Pause > Change Area |
| `test_levels.sh` | sweep a range of list positions |
| `vk.sh KEY ...`, `shot.sh NAME` | press pad buttons (`sleep:N` waits); take a 960x540 screenshot |
| `boot_shots.sh ISO NAME T1 T2 ...` | screenshots at given seconds after boot |
| `bisect_leaves.sh`, `bisect_scripts.sh`, `bisect_level.sh`, `variant_level.py` | find what breaks a level |
| `state_regs.py STATE.p2s` | EE pc, registers and stack from a save state |
| `null_trap.py` | patch a test image so a null read spins (find the caller from a save state) |
| `qbdump.py`, `zonedump.py`, `t2dump.py` | print THAW / zone / THUG2 QB files as text |
| `run_dev.sh` | like run_level.sh with a self-built PCSX2 that has trace logging (`PCSX2_DEV_BIN`) |
| `ghidra/CallersAndDecompile.java` | headless Ghidra: callers and decompiles of addresses in the THAW ELF |

Some older scripts expect files under `_workspace/` from earlier experiments (noted at their top).
Never `pkill -f` a pattern that also appears in your own command line (it kills your shell); the scripts anchor
theirs (`'^pcsx2-qt'`).
