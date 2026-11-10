#!/bin/bash
# usage: harness/live_check.sh ISO DOWNS NAME  - load the level at list position DOWNS, screenshot, push Up x3 + A,
# screenshot again; prints "DOWNS: LIVE|FROZEN (px changed)". Shots: harness/NAME_a.jpg, NAME_b.jpg
cd "$(dirname "$0")/.."
ISO=$1; N=$2; S=$3
harness/run_level.sh "$ISO" "$N" "$S" >/dev/null 2>&1
sleep 4; harness/shot.sh "${S}_a" >/dev/null 2>&1
for k in 1 2 3; do timeout 10 harness/vk.sh Up; done; timeout 10 harness/vk.sh A; sleep 1
harness/shot.sh "${S}_b" >/dev/null 2>&1
pkill -f '^pcsx2-qt'; sleep 2
.venv/bin/python - "$N" "$S" <<'P'
import sys
from PIL import Image, ImageChops
n, s = sys.argv[1:3]
try:
    a = Image.open(f'harness/{s}_a.jpg').convert('L'); b = Image.open(f'harness/{s}_b.jpg').convert('L')
    d = sum(ImageChops.difference(a, b).histogram()[24:])
    print(f'{n}: {"LIVE" if d > 2000 else "FROZEN"} ({d} px changed)')
except Exception as e:
    print(f'{n}: no screenshot ({e})')
P
