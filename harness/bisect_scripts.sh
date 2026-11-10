#!/bin/bash
# usage: harness/bisect_scripts.sh SOURCE_DISC CODE A B  - boot the level with only level scripts A..B-1
cd "$(dirname "$0")/.."
ALL_SCRIPTS=1 SCRIPT_RANGE=$3:$4 PYTHONPATH=. timeout 900 .venv/bin/python harness/variant_level.py \
  "_workspace/e2e/tony hawk's american wasteland (usa) (collector's edition).iso" _workspace/build/v_b.iso "$1" "$2" "" 2>&1 | grep -E "kept|Error"
harness/test_levels.sh _workspace/build/v_b.iso 14 14 2>&1 | grep position
