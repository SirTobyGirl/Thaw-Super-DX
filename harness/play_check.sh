#!/bin/bash
# usage: harness/play_check.sh ISO DOWNS NAME [normal]  - load the level at list position DOWNS (shrunk image, or a
# full-game image with 'normal'), then play ~60 s of mixed input (push, turn, ollie, grind, flip) with a screenshot
# every round; prints "DOWNS: OK|FROZEN at round k|CRASH (markers)" and the crash markers from the emulator log.
cd "$(dirname "$0")/.."
ISO=$1; N=$2; S=$3; MODE=$4
L=~/.var/app/net.pcsx2.PCSX2/config/PCSX2/logs/emulog.txt
if [ "$MODE" = normal ]; then harness/run_level_normal.sh "$ISO" "$N" "$S" >/dev/null 2>&1
else harness/run_level.sh "$ISO" "$N" "$S" >/dev/null 2>&1; fi
prev=""; frozen=0; res=OK
for r in 1 2 3 4 5 6 7 8; do
  timeout 30 harness/vk.sh Up Up Up Up sleep:1 A sleep:1 Y sleep:1 Left Left Up Up X sleep:1 Right Up Up B >/dev/null 2>&1
  harness/shot.sh "${S}_r$r" >/dev/null 2>&1
  if [ -n "$prev" ]; then
    d=$(.venv/bin/python -c "
from PIL import Image, ImageChops
a=Image.open('harness/${prev}.jpg').convert('L'); b=Image.open('harness/${S}_r$r.jpg').convert('L')
print(sum(ImageChops.difference(a,b).histogram()[24:]))" 2>/dev/null)
    [ "${d:-0}" -lt 2000 ] && frozen=$((frozen+1)) || frozen=0
    [ $frozen -ge 2 ] && { res="FROZEN at round $r"; break; }
  fi
  prev="${S}_r$r"
  grep -qE 'Unknown R5900|TLB Miss' "$L" && { res="CRASH"; break; }
done
pkill -f '^pcsx2-qt'; sleep 2
echo "$N: $res  markers: $(grep -E 'TLB Miss|Unknown R5900' "$L" | grep -o 'pc=0x[0-9a-f]*' | sort | uniq -c | tr '\n' ' ')"
