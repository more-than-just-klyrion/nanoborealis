#!/bin/sh
# Seed config and skills into the persistent volume on first start only, so
# WebUI changes and skills the agent writes itself survive rebuilds.
set -eu

state="$HOME/.nanobot"
mkdir -p "$state"
if [ ! -e "$state/.nanobot-os-seeded" ]; then
    cp -R /opt/nanobot-seed/. "$state/"
    touch "$state/.nanobot-os-seeded"
fi

exec nanobot "$@"
