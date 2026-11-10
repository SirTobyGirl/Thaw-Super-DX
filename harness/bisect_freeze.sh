#!/bin/bash
# usage: harness/bisect_freeze.sh SOURCE_DISC CODE N  - find the level script (index < N) whose presence freezes the
# loaded level (live_check.sh), assuming one culprit
cd "$(dirname "$0")/.."
D=$1; C=$2; lo=0; hi=$3
while [ $((hi-lo)) -gt 1 ]; do
  mid=$(((lo+hi)/2))
  r=$(SCRIPT_RANGE=$lo:$mid harness/freeze_variant.sh "$D" "$C" "" | tail -1)
  case $r in *FROZEN*) hi=$mid;; *) lo=$mid;; esac
  echo "$C: [$r] freeze within $lo..$hi"
done
echo "$C culprit index $lo"
