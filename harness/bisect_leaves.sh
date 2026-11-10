#!/bin/bash
# usage: harness/bisect_leaves.sh SOURCE_DISC CODE LO HI  - narrow a freezing leaf range [LO,HI) (keeps halves that freeze)
cd "$(dirname "$0")/.."
D=$1; C=$2; lo=$3; hi=$4
while [ $((hi-lo)) -gt 1 ]; do
  mid=$(((lo+hi)/2))
  r=$(LEAVES=$lo:$mid harness/freeze_variant.sh "$D" "$C" "" | tail -1)
  if [[ $r == *FROZEN* ]]; then hi=$mid; else
    r2=$(LEAVES=$mid:$hi harness/freeze_variant.sh "$D" "$C" "" | tail -1)
    if [[ $r2 == *FROZEN* ]]; then lo=$mid; else echo "$C: neither half of $lo..$hi freezes alone (needs both)"; break; fi
  fi
  echo "$C: freeze within leaves $lo..$hi"
done
echo "$C leaves $lo..$hi"
