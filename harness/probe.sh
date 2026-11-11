#!/bin/bash
# usage: [ENV=..] harness/probe.sh CODE LABEL [extra build_level_test args]
# Builds the THUG2 level CODE into Kyoto's slot, boots it, and prints CRASH pc=.. / HANG / RUNS + a screenshot.
cd "$(dirname "$0")/.."
CODE=$1; LABEL=$2; shift 2
. harness/env.sh
pkill -f '^pcsx2-qt' 2>/dev/null; sleep 2
NO_LEVEL_SCRIPTS=${NO_LEVEL_SCRIPTS-1} PYTHONPATH=. .venv/bin/python harness/build_level_test.py \
  _workspace/build/sandbox.iso _workspace/build/$CODE.iso _workspace/thug2/$CODE $CODE z_ja --tex ${TEX:-convert} \
  --parts ${PARTS:-tex,geom,col,nqb,scripts,peds} \
  --no-create LevelObject,LevelLight,Pedestrian,Vehicle,ParticleObject,GameObject "$@" >"$SDX_TMP/probe_build.log" 2>&1 \
  || { echo "$LABEL: BUILD FAILED"; tail -3 "$SDX_TMP/probe_build.log"; exit 1; }
harness/run_level.sh _workspace/build/$CODE.iso 13 probe_$LABEL >/dev/null 2>&1
LOG=$PCSX2_LOG
pc=$(grep -m1 -o "TLB Miss, pc=0x[0-9a-f]*" $LOG | sed 's/.*pc=//')
if [ -n "$pc" ]; then echo "$LABEL: CRASH pc=$pc"; pkill -f '^pcsx2-qt'; exit 0; fi
harness/shot.sh probe_${LABEL}_a >/dev/null 2>&1; sleep 3; harness/shot.sh probe_${LABEL}_b >/dev/null 2>&1
d=$(.venv/bin/python -c "
from PIL import Image, ImageChops
a=Image.open('harness/probe_${LABEL}_a.jpg').convert('L'); b=Image.open('harness/probe_${LABEL}_b.jpg').convert('L')
print(sum(ImageChops.difference(a,b).histogram()[24:]))")
if [ "$d" -gt 500 ]; then echo "$LABEL: RUNS (frames differ: $d px)"; else echo "$LABEL: FROZEN (frames differ: $d px)"; fi
