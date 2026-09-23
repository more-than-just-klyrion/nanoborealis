#!/bin/sh
# Seeds nanobot's config and skills into the persistent home on first start, reinstalls
# any apt packages the agent listed (the container itself is disposable), then starts nanobot.
set -eu
umask 002

state="$HOME/.nanobot"
mkdir -p "$state"
if [ ! -e "$state/.nanobot-os-seeded" ]; then
    cp -R /opt/nanobot-seed/. "$state/"
    touch "$state/.nanobot-os-seeded"
fi
# Skills added in later NanoAurora releases reach existing agents; ones the agent edited are left alone.
mkdir -p "$state/workspace/skills"
cp -Rn /opt/nanobot-seed/workspace/skills/. "$state/workspace/skills/" 2>/dev/null || true

pkgs="$HOME/.config/nanoaurora/apt-packages"
if [ -s "$pkgs" ]; then
    list="$(grep -v '^[[:space:]]*#' "$pkgs" | xargs)"
    if [ -n "$list" ]; then
        { sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $list; } \
            || echo "nanoaurora: could not reinstall every package listed in $pkgs" >&2
    fi
fi

exec nanobot "$@"
