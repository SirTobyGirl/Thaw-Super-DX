#!/bin/bash
# usage: harness/boot_shots.sh ISO NAME T1 T2 ...  - boot ISO in PCSX2 (no input) and screenshot at the given
# seconds after launch: harness/NAME_<t>.jpg. Leaves PCSX2 running.
H="$(cd "$(dirname "$0")" && pwd)"; ISO="$(realpath "$1")"; S="$2"; shift 2
. "$(dirname "$0")/env.sh"
kill $(pgrep -f '^[p]csx2-qt') 2>/dev/null; sleep 2
vpad_start
pcsx2_start "$ISO"
t0=$(date +%s)
for t in "$@"; do
  while [ $(( $(date +%s) - t0 )) -lt "$t" ]; do sleep 1; done
  timeout 30 $H/shot.sh "${S}_$t" >/dev/null
done
