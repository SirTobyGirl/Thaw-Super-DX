#!/bin/bash
# usage: harness/run_level_normal.sh ISO DOWNS SHOTNAME - normal-boot image: intro, main menu, High Score / Free Skate,
# default skater, Play Level, DOWNS entries down the list, accept, wait, screenshot. Leaves PCSX2 running.
H="$(cd "$(dirname "$0")" && pwd)"; ISO="$1"; N="$2"; S="$3"
L=~/.var/app/net.pcsx2.PCSX2/config/PCSX2/logs/emulog.txt
$H/boot_shots.sh "$ISO" "${S}_boot" 20
timeout 10 $H/vk.sh Start; sleep 8
timeout 30 $H/vk.sh Down sleep:1 Down sleep:1 Down sleep:1 Down sleep:1 A; sleep 6
timeout 10 $H/vk.sh A; sleep 8
timeout 10 $H/vk.sh A; sleep 8
for i in $(seq 1 "$N"); do timeout 10 $H/vk.sh Down; done; sleep 1
timeout 30 $H/shot.sh "${S}_list" >/dev/null
timeout 10 $H/vk.sh A; sleep 35
timeout 30 $H/shot.sh "$S" >/dev/null
echo "crash markers: $(grep -cE 'Unknown R5900|TLB Miss' "$L")"
