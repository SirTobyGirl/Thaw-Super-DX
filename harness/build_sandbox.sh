#!/bin/bash
# Build the current Free Skate sandbox test ISO from the vanilla disc (in-place, same-size script edits).
# usage: harness/build_sandbox.sh [OUT.iso]   (run from anywhere; default _workspace/build/sandbox.iso)
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-_workspace/build/sandbox.iso}"
PYTHONPATH=. .venv/bin/python harness/patch_iso.py "$OUT" \
  "create_main_menu:attract_mode_timer:NullScript" \
  "startup_loading_screen:0xba297025:IsNGC" \
  "create_xbox_online_menu@=cheat_reallygivelevels;load_pro_skater name = hawk;change_gamemode_singlesession;launch_level_select_menu" \
  "create_base_main_menu@=create_xbox_online_menu" \
  "menu_confirm_quit@=launch_level_select_menu"
# What each edit does:
#  1 the main menu's idle timer spawns NullScript instead of the attract-mode demo
#  2 the startup movie condition is false on PS2, so the ATVI logo and intro movie are skipped
#  3 an Xbox-only script hosts our boot code: unlock all levels, load Tony Hawk, Free Skate, level list
#  4 the main menu builder just runs that host
#  5 pause/end-run QUIT goes back to the level list instead of the old main menu
