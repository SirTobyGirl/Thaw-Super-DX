#!/bin/bash
# Opens the THAW Super DX window (uses the project's .venv when present).
cd "$(dirname "$(readlink -f "$0")")"
PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python
exec "$PY" -m thaw_sandbox gui "$@"
