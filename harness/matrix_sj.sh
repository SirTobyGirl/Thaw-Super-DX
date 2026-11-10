#!/bin/bash
# 2x2: index re-sort on/off x 0x400 clear on/off for one THUG level; two live checks each
cd "$(dirname "$0")/.."
T="iso/Tony Hawk's Underground (USA).iso"; C=${1:-sj}
for resort in 1 0; do for clr in 1 0; do
  RESORT=$resort CLR=$clr PYTHONPATH=. .venv/bin/python - "$T" "$C" <<'P' >/dev/null 2>&1
import os, sys, runpy
from thaw_sandbox import zone_rename as ZR, thps4_geom as G4
if os.environ["RESORT"] == "0":
    ZR._resort_name_indexes = lambda items: 0
if os.environ["CLR"] == "0":
    src = open(G4.__file__).read().replace("n[7] & 0x00FFFBFF", "n[7] & 0x00FFFFFF")
    exec(compile(src, G4.__file__, "exec"), G4.__dict__)
sys.argv = ["variant_level.py", "_workspace/e2e/tony hawk's american wasteland (usa) (collector's edition).iso",
            "_workspace/build/v_m.iso", sys.argv[1], sys.argv[2], ""]
runpy.run_path("harness/variant_level.py", run_name="__main__")
P
  for i in 1 2; do
    r=$(harness/live_check.sh _workspace/build/v_m.iso 14 mx)
    t=$(grep 'TLB Miss' ~/.var/app/net.pcsx2.PCSX2/config/PCSX2/logs/emulog.txt | awk '{print $5}' | sort | uniq -c | tr '\n' ' ')
    echo "resort=$resort clear400=$clr run$i: $r  TLB: $t"
    cp harness/mx_a.jpg harness/mx_${resort}${clr}_$i.jpg 2>/dev/null
  done
done; done
