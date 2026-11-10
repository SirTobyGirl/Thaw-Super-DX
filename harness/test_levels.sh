#!/bin/bash
# usage: harness/test_levels.sh ISO FIRST_DOWNS LAST_DOWNS
# Boots ISO once per list position (DOWNS = Down presses from the top of the level list), loads that level and
# reports RUNS / FROZEN (two screenshots 3 s apart are identical) / CRASH (no running game). Shots: harness/lvl_N_*.jpg
cd "$(dirname "$0")/.."
ISO=$1; A=$2; B=$3
for n in $(seq "$A" "$B"); do
  harness/run_level.sh "$ISO" "$n" "lvl_$n" >/dev/null 2>&1
  sleep 5; harness/shot.sh "lvl_${n}_a" >/dev/null 2>&1; sleep 3; harness/shot.sh "lvl_${n}_b" >/dev/null 2>&1
  pkill -f '^pcsx2-qt'; sleep 2
  .venv/bin/python - "$n" <<'P'
import sys
from PIL import Image, ImageChops
n=sys.argv[1]
try:
    a=Image.open(f'harness/lvl_{n}_a.jpg').convert('L'); b=Image.open(f'harness/lvl_{n}_b.jpg').convert('L')
    d=sum(ImageChops.difference(a,b).histogram()[24:])
    print(f'position {n}: {"RUNS" if d>500 else "FROZEN"} ({d} px changed)')
except Exception as e:
    print(f'position {n}: no screenshot ({e})')
P
done
