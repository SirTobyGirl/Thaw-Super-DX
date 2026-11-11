#!/bin/bash
# usage: shot.sh name  -> takes a screenshot via the virtual pad Guide button in PCSX2 and writes <harness dir>/name.jpg (960x540)
S="$(cd "$(dirname "$0")" && pwd)"
. "$S/env.sh"
$S/vk.sh Guide; sleep 5
HARNESS_DIR="$S" "$SDX_PY" - "$1" <<'P'
import glob,os,sys
from PIL import Image
S=os.environ["HARNESS_DIR"]
f=sorted(glob.glob(os.environ['PCSX2_SNAPS'] + '/*.png'))[-1]
import time
for _ in range(10):
    try:
        im=Image.open(f); im.load(); break
    except Exception: time.sleep(1)
im.convert('RGB').resize((960,540)).save(f'{S}/{sys.argv[1]}.jpg',quality=85)
P
