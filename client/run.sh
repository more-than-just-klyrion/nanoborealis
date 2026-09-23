#!/bin/sh
# Opens the NanoAurora client on Linux or macOS. The first run sets up its own Python environment.
set -e
venv="${XDG_DATA_HOME:-$HOME/.local/share}/nanoaurora/client-venv"
if [ ! -x "$venv/bin/python" ]; then
    echo "Setting up the NanoAurora client. This happens once and takes a minute..."
    python3 -m venv "$venv"
    "$venv/bin/python" -m pip install --quiet --disable-pip-version-check "flet[desktop]==1.0.1" "websockets>=13"
fi
exec "$venv/bin/python" "$(dirname "$0")/src/main.py"
