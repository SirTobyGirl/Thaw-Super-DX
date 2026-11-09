#!/bin/bash
# usage: harness/run_level.sh ISO DOWNS SHOTNAME   - boot ISO in PCSX2, go DOWNS entries down the level list,
# accept, wait, screenshot to harness/SHOTNAME.jpg, print load/crash lines from the emulator log. Leaves PCSX2 running.
H="$(cd "$(dirname "$0")" && pwd)"; ISO="$(realpath "$1")"; N="$2"; S="$3"
L=~/.var/app/net.pcsx2.PCSX2/config/PCSX2/logs/emulog.txt
kill $(pgrep -f '^[p]csx2-qt') 2>/dev/null; sleep 2
rm -f /home/bazzite/Emulation/storage/pcsx2/snaps/*.png
[ "$(ps -eo args | grep -c 'python3 .*vpad_daemon.py$')" = 0 ] && (setsid nohup python3 $H/vpad_daemon.py > /tmp/vpd.log 2>&1 &)
sleep 1
(setsid nohup flatpak run --filesystem=/home/bazzite/Thaw-Super-DX --filesystem=/home/bazzite/Emulation net.pcsx2.PCSX2 -batch -nogui -fastboot -- "$ISO" > /tmp/pcsx2_run.log 2>&1 &)
sleep 42
for i in $(seq 1 "$N"); do timeout 10 $H/vk.sh Down; done; sleep 1
timeout 30 $H/shot.sh "${S}_list" >/dev/null
timeout 10 $H/vk.sh A; sleep 28
timeout 30 $H/shot.sh "$S" >/dev/null
grep -E 'loadscrn_|worldZones/z_|Unknown R5900|Trap|TLB Miss' "$L" | grep -v GSScreenshot | tail -5 | cut -c1-110
echo "crash markers: $(grep -cE 'Unknown R5900|TLB Miss' "$L")"
