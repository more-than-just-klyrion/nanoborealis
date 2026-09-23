#!/bin/bash

set -ouex pipefail

cp -avf "/ctx/system_files"/. /

# nft CLI for the agent's network guard (normally already present alongside firewalld).
dnf5 install -y nftables

chmod 0755 /usr/libexec/nanoborealis-firstrun \
           /usr/libexec/nanoborealis-firewall \
           /usr/libexec/nanoborealis-migrate \
           /usr/libexec/nanoborealis-setup-from-stick \
           /usr/share/nanoborealis/install.sh \
           /usr/share/nanoborealis/nanoborealis \
           /usr/share/nanoborealis/image/entrypoint.sh
ln -sf /usr/share/nanoborealis/nanoborealis /usr/bin/nanoborealis
# Earlier names, so existing habits, scripts and desktop icons keep working.
ln -sf /usr/share/nanoborealis/nanoborealis /usr/bin/nanoaurora
ln -sf /usr/share/nanoborealis/nanoborealis /usr/bin/nanobot-os

systemctl enable nanoborealis-firewall.service nanoborealis-migrate.service

# Updates are opt-in: machines only move to a newer build when their owner runs
# `nanoborealis update`. Masking (not just disabling) keeps presets from re-enabling these.
systemctl mask uupd.timer bootc-fetch-apply-updates.timer rpm-ostreed-automatic.timer

# Rebrand: the boot menu, System Info, and fastfetch read these. ID and VARIANT_ID stay
# as Aurora's so Universal Blue's update tooling keeps recognising the system.
. /usr/lib/os-release
sed -i \
    -e 's|^NAME=.*|NAME="NanoBorealis"|' \
    -e "s|^PRETTY_NAME=.*|PRETTY_NAME=\"NanoBorealis ${VERSION_ID:-}\"|" \
    /usr/lib/os-release
