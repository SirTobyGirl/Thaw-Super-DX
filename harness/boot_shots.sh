#!/bin/bash
# usage: harness/boot_shots.sh ISO NAME T1 T2 ...  - boot ISO in PCSX2 (no input) and screenshot at the given
# seconds after launch: harness/NAME_<t>.jpg. Leaves PCSX2 running.
H="$(cd "$(dirname "$0")" && pwd)"; ISO="$(realpath "$1")"; S="$2"; shift 2
kill $(pgrep -f '^[p]csx2-qt') 2>/dev/null; sleep 2
[ "$(ps -eo args | grep -c 'python3 .*vpad_daemon.py$')" = 0 ] && (setsid nohup python3 $H/vpad_daemon.py > /tmp/vpd.log 2>&1 &)
sleep 1
(setsid nohup flatpak run --filesystem=/home/bazzite/Thaw-Super-DX --filesystem=/home/bazzite/Emulation net.pcsx2.PCSX2 -batch -nogui -fastboot -- "$ISO" > /tmp/pcsx2_run.log 2>&1 &)
t0=$(date +%s)
for t in "$@"; do
  while [ $(( $(date +%s) - t0 )) -lt "$t" ]; do sleep 1; done
  timeout 30 $H/shot.sh "${S}_$t" >/dev/null
done
