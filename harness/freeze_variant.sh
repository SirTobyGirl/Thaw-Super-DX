#!/bin/bash
# usage: harness/freeze_variant.sh SOURCE_DISC CODE PARTS_FROM_KYOTO  - build a one-level image with the given parts
# taken from Kyoto (variant_level.py), load it and report LIVE / FROZEN: the level is driven with input between two
# screenshots, so a standing skater still counts as live (test_levels.sh's FROZEN can be an idle skater).
cd "$(dirname "$0")/.."
PYTHONPATH=. timeout 900 .venv/bin/python harness/variant_level.py \
  "_workspace/e2e/tony hawk's american wasteland (usa) (collector's edition).iso" _workspace/build/v_f.iso "$1" "$2" "$3" 2>&1 | grep -E "kyoto|Error"
harness/live_check.sh _workspace/build/v_f.iso 14 fv
