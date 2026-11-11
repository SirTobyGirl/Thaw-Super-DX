#!/bin/bash
# usage: harness/session_check.sh ISO START COUNT NAME  - one boot: load list position START, then play ~20 s and
# use Pause > Change Area to load the next level, COUNT times. Like a person going through the levels in one
# session (heap state carries over). Prints one line per level: OK / FROZEN / new crash markers.
cd "$(dirname "$0")/.."
ISO=$1; N=$2; COUNT=$3; S=$4
L=~/.var/app/net.pcsx2.PCSX2/config/PCSX2/logs/emulog.txt
harness/run_level.sh "$ISO" "$N" "$S" >/dev/null 2>&1
seen=0
for i in $(seq 0 $((COUNT - 1))); do
  pos=$((N + i))
  timeout 40 harness/vk.sh Up Up Up sleep:1 A sleep:1 Y Left Left Up X sleep:1 Right Up B sleep:2 >/dev/null 2>&1
  harness/shot.sh "${S}_${pos}_a" >/dev/null 2>&1
  timeout 20 harness/vk.sh Up Up A sleep:2 >/dev/null 2>&1
  harness/shot.sh "${S}_${pos}_b" >/dev/null 2>&1
  d=$(.venv/bin/python -c "
from PIL import Image, ImageChops
a=Image.open('harness/${S}_${pos}_a.jpg').convert('L'); b=Image.open('harness/${S}_${pos}_b.jpg').convert('L')
print(sum(ImageChops.difference(a,b).histogram()[24:]))" 2>/dev/null)
  m=$(grep -cE 'TLB Miss|Unknown R5900' "$L")
  new=$((m - seen)); seen=$m
  st=OK; [ "${d:-0}" -lt 2000 ] && st=FROZEN
  echo "$pos: $st (${d:-?} px) new markers: $new $(grep -E 'TLB Miss|Unknown R5900' "$L" | tail -n $new | grep -o 'pc=0x[0-9a-f]*' | sort | uniq -c | tr '\n' ' ')"
  [ "$st" = FROZEN ] && break
  timeout 30 harness/vk.sh Start sleep:2 Down sleep:1 A sleep:4 Down sleep:1 A >/dev/null 2>&1
  sleep 30
done
pkill -f '^pcsx2-qt'
