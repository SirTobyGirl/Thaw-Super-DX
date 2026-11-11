#!/bin/bash
# Build the single-file Linux executable dist/thaw-super-dx (needs PyInstaller in .venv:
# .venv/bin/pip install pyinstaller). No game data is bundled; chdman stays an optional system tool for .chd discs.
set -e
cd "$(dirname "$(readlink -f "$0")")/.."
# Python builds that keep Tcl/Tk in their own lib/ (python-build-standalone): let PyInstaller find them to bundle
export LD_LIBRARY_PATH="$(.venv/bin/python -c 'import sys; print(sys.base_prefix)')/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
.venv/bin/pyinstaller --noconfirm --clean --onefile --name thaw-super-dx \
  --workpath build/pyinstaller --distpath dist --specpath build/pyinstaller \
  --paths . --collect-submodules thaw_sandbox --hidden-import pycdlib \
  packaging/thaw_super_dx.py
echo "built dist/thaw-super-dx ($(du -h dist/thaw-super-dx | cut -f1))"
