#!/bin/bash

set -ouex pipefail

cp -avf "/ctx/system_files"/. /

# nft CLI for the agent's network guard (normally already present alongside firewalld).
dnf5 install -y nftables

chmod 0755 /usr/libexec/nanobot-os-firstrun \
           /usr/libexec/nanoaurora-firewall \
           /usr/libexec/nanoborealis-setup-from-stick \
           /usr/share/nanobot-os/install.sh \
           /usr/share/nanobot-os/nanobot-os \
           /usr/share/nanobot-os/image/entrypoint.sh
ln -sf /usr/share/nanobot-os/nanobot-os /usr/bin/nanobot-os
ln -sf /usr/share/nanobot-os/nanobot-os /usr/bin/nanoaurora

systemctl enable nanoaurora-firewall.service

# Updates are opt-in: machines only move to a newer build when their owner runs
# `nanoaurora update`. Masking (not just disabling) keeps presets from re-enabling these.
systemctl mask uupd.timer bootc-fetch-apply-updates.timer rpm-ostreed-automatic.timer

# Rebrand: the boot menu, System Info, and fastfetch read these. ID and VARIANT_ID stay
# as Aurora's so Universal Blue's update tooling keeps recognising the system.
. /usr/lib/os-release
sed -i \
    -e 's|^NAME=.*|NAME="NanoAurora"|' \
    -e "s|^PRETTY_NAME=.*|PRETTY_NAME=\"NanoAurora ${VERSION_ID:-}\"|" \
    /usr/lib/os-release
