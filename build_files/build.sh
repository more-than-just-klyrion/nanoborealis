#!/bin/bash

set -ouex pipefail

cp -avf "/ctx/system_files"/. /

chmod 0755 /usr/libexec/nanobot-os-firstrun \
           /usr/share/nanobot-os/install.sh \
           /usr/share/nanobot-os/nanobot-os \
           /usr/share/nanobot-os/image/entrypoint.sh
ln -sf /usr/share/nanobot-os/nanobot-os /usr/bin/nanobot-os
