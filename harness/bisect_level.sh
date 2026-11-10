#!/bin/bash
# usage: harness/bisect_level.sh SOURCE_DISC CODE N  - find the level script (index < N) whose presence hangs the load
cd "$(dirname "$0")/.."
D=$1; C=$2; lo=0; hi=$3
while [ $((hi-lo)) -gt 1 ]; do
  mid=$(((lo+hi)/2))
  harness/bisect_scripts.sh "$D" "$C" $lo $mid >/dev/null
  if .venv/bin/python harness/is_loading.py harness/lvl_14_b.jpg >/dev/null; then hi=$mid; else lo=$mid; fi
  echo "$C: hang within $lo..$hi"
done
echo "$C culprit index $lo"
