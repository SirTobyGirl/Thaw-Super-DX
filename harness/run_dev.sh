#!/bin/bash
# usage: harness/run_dev.sh ISO DOWNS NAME [EXTRA_SECONDS]
# Like run_level.sh, but runs the self-built PCSX2 *Devel* binary (~/.local/src/pcsx2, trace logging compiled in)
# with its own config in _workspace/pcsx2dev (VIF/GIF/DMAC tracing on). The flatpak config is not touched.
# SAVE=1 also saves a state before quitting. Kills PCSX2 if the log grows past 8 GB. Log: _workspace/pcsx2dev/PCSX2/logs/emulog.txt
H="$(cd "$(dirname "$0")" && pwd)"; R="$(dirname "$H")"; ISO="$(realpath "$1")"; N="$2"; S="$3"; X="${4:-10}"
. "$H/env.sh"
BIN=$PCSX2_DEV_BIN
L="$R/_workspace/pcsx2dev/PCSX2/logs/emulog.txt"
pkill -f "^$BIN" 2>/dev/null; sleep 2
rm -f "$L" "$PCSX2_SNAPS"/*.png
vpad_start
(XDG_CONFIG_HOME="$R/_workspace/pcsx2dev" setsid nohup "$BIN" -batch -nogui -fastboot -- "$ISO" > "$SDX_TMP/pcsx2_dev.log" 2>&1 &)
( for i in $(seq 1 400); do s=$(stat -c %s "$L" 2>/dev/null || echo 0)
    [ "$s" -gt 8000000000 ] && { pkill -f "^$BIN"; echo "log guard: killed at $s bytes" >> "$SDX_TMP/pcsx2_dev.log"; break; }
    pgrep -f "^$BIN" >/dev/null || break; sleep 1; done ) &
sleep 42
for i in $(seq 1 "$N"); do timeout 10 "$H/vk.sh" Down; done; sleep 1
timeout 10 "$H/vk.sh" A; sleep 28
timeout 30 "$H/shot.sh" "$S" >/dev/null
sleep "$X"
if [ -n "$SAVE" ]; then timeout 20 "$H/vk.sh" SaveState; sleep 10; fi
pkill -f "^$BIN"; sleep 2
ls -la "$L"; grep -E 'TLB Miss' "$L" | head -2
