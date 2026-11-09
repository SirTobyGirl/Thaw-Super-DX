#!/bin/bash
# usage: harness/run_dev.sh ISO DOWNS NAME [EXTRA_SECONDS]
# Like run_level.sh, but runs the self-built PCSX2 *Devel* binary (~/.local/src/pcsx2, trace logging compiled in)
# with its own config in _workspace/pcsx2dev (VIF/GIF/DMAC tracing on). The flatpak config is not touched.
# SAVE=1 also saves a state before quitting. Kills PCSX2 if the log grows past 8 GB. Log: _workspace/pcsx2dev/PCSX2/logs/emulog.txt
H="$(cd "$(dirname "$0")" && pwd)"; R="$(dirname "$H")"; ISO="$(realpath "$1")"; N="$2"; S="$3"; X="${4:-10}"
BIN=~/.local/src/pcsx2/build/bin/pcsx2-qt
L="$R/_workspace/pcsx2dev/PCSX2/logs/emulog.txt"
pkill -f '^/home/bazzite/.local/src/pcsx2/build/bin/pcsx2-qt' 2>/dev/null; sleep 2
rm -f "$L" /home/bazzite/Emulation/storage/pcsx2/snaps/*.png
[ "$(ps -eo args | grep -c 'python3 .*vpad_daemon.py$')" = 0 ] && (setsid nohup python3 "$H/vpad_daemon.py" > /tmp/vpd.log 2>&1 &)
sleep 1
(XDG_CONFIG_HOME="$R/_workspace/pcsx2dev" setsid nohup "$BIN" -batch -nogui -fastboot -- "$ISO" > /tmp/pcsx2_dev.log 2>&1 &)
( for i in $(seq 1 400); do s=$(stat -c %s "$L" 2>/dev/null || echo 0)
    [ "$s" -gt 8000000000 ] && { pkill -f '^/home/bazzite/.local/src/pcsx2/build/bin/pcsx2-qt'; echo "log guard: killed at $s bytes" >> /tmp/pcsx2_dev.log; break; }
    pgrep -f '^/home/bazzite/.local/src/pcsx2/build/bin/pcsx2-qt' >/dev/null || break; sleep 1; done ) &
sleep 42
for i in $(seq 1 "$N"); do timeout 10 "$H/vk.sh" Down; done; sleep 1
timeout 10 "$H/vk.sh" A; sleep 28
timeout 30 "$H/shot.sh" "$S" >/dev/null
sleep "$X"
if [ -n "$SAVE" ]; then timeout 20 "$H/vk.sh" SaveState; sleep 10; fi
pkill -f '^/home/bazzite/.local/src/pcsx2/build/bin/pcsx2-qt'; sleep 2
ls -la "$L"; grep -E 'TLB Miss' "$L" | head -2
