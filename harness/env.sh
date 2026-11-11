# Settings shared by the harness scripts (sourced, not run). Defaults suit the PCSX2 Flatpak (net.pcsx2.PCSX2);
# put your own values in harness/env.local.sh (not in git), e.g.
#   PCSX2_SNAPS=$HOME/Emulation/storage/pcsx2/snaps   # where PCSX2 saves screenshots
#   PCSX2_FS="$HOME/Emulation"                         # extra folders the Flatpak needs (BIOS, snaps, ...)
H="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDX_ROOT="$(dirname "$H")"
[ -f "$H/env.local.sh" ] && . "$H/env.local.sh"
: "${SDX_PY:=$SDX_ROOT/.venv/bin/python}"                      # Python with Pillow (screenshots, frame compares)
: "${PCSX2_FLATPAK:=net.pcsx2.PCSX2}"
: "${PCSX2_CONFIG:=$HOME/.var/app/$PCSX2_FLATPAK/config/PCSX2}"
: "${PCSX2_LOG:=$PCSX2_CONFIG/logs/emulog.txt}"                 # emulator log (load lines, TLB misses)
: "${PCSX2_SNAPS:=$PCSX2_CONFIG/snaps}"                         # screenshot folder
: "${PCSX2_FS:=}"                                               # extra --filesystem folders for the Flatpak
: "${PCSX2_DEV_BIN:=$HOME/.local/src/pcsx2/build/bin/pcsx2-qt}" # self-built PCSX2 with tracing (run_dev.sh)
: "${SDX_TMP:=${TMPDIR:-/tmp}}"
export SDX_ROOT SDX_PY PCSX2_LOG PCSX2_SNAPS PCSX2_DEV_BIN SDX_TMP

# start the virtual pad (needs write access to /dev/uinput) unless it is already running
vpad_start() {
  [ "$(ps -eo args | grep -c 'python3 .*vpad_daemon.py$')" = 0 ] &&
    (setsid nohup python3 "$H/vpad_daemon.py" > "$SDX_TMP/vpd.log" 2>&1 &)
  sleep 1
}

# boot an image in the PCSX2 Flatpak, detached (fast boot, no GUI)
pcsx2_start() {
  local fs=(--filesystem="$SDX_ROOT" --filesystem="$(dirname "$PCSX2_SNAPS")") d
  for d in $PCSX2_FS; do fs+=(--filesystem="$d"); done
  (setsid nohup flatpak run "${fs[@]}" "$PCSX2_FLATPAK" -batch -nogui -fastboot -- "$1" > "$SDX_TMP/pcsx2_run.log" 2>&1 &)
}
