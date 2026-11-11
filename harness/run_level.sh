#!/bin/bash
# usage: harness/run_level.sh ISO DOWNS SHOTNAME   - boot ISO in PCSX2, go DOWNS entries down the level list,
# accept, wait, screenshot to harness/SHOTNAME.jpg, print load/crash lines from the emulator log. Leaves PCSX2 running.
H="$(cd "$(dirname "$0")" && pwd)"; ISO="$(realpath "$1")"; N="$2"; S="$3"
. "$(dirname "$0")/env.sh"
L=$PCSX2_LOG
kill $(pgrep -f '^[p]csx2-qt') 2>/dev/null; sleep 2
rm -f "$PCSX2_SNAPS"/*.png
vpad_start
pcsx2_start "$ISO"
sleep 42
for i in $(seq 1 "$N"); do timeout 10 $H/vk.sh Down; done; sleep 1
timeout 30 $H/shot.sh "${S}_list" >/dev/null
timeout 10 $H/vk.sh A; sleep ${LOADWAIT:-28}
timeout 30 $H/shot.sh "$S" >/dev/null
grep -E 'loadscrn_|worldZones/z_|Unknown R5900|Trap|TLB Miss' "$L" | grep -v GSScreenshot | tail -5 | cut -c1-110
echo "crash markers: $(grep -cE 'Unknown R5900|TLB Miss' "$L")"
