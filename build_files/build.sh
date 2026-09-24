#!/bin/bash

set -ouex pipefail

cp -avf "/ctx/system_files"/. /

# nft CLI for the agent's network guard (normally already present alongside firewalld).
dnf5 install -y nftables

chmod 0755 /usr/libexec/nanoborealis-firstrun \
           /usr/libexec/nanoborealis-firewall \
           /usr/libexec/nanoborealis-migrate \
           /usr/libexec/nanoborealis-setup-from-stick \
           /usr/libexec/nanoborealis-relay \
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
REPO_URL=https://github.com/more-than-just-kyrion/nanoborealis
sed -i \
    -e 's|^NAME=.*|NAME="NanoBorealis"|' \
    -e "s|^PRETTY_NAME=.*|PRETTY_NAME=\"NanoBorealis ${VERSION_ID:-}\"|" \
    -e 's|^LOGO=.*|LOGO=distributor-logo|' \
    -e "s|^HOME_URL=.*|HOME_URL=\"$REPO_URL\"|" \
    -e "s|^DOCUMENTATION_URL=.*|DOCUMENTATION_URL=\"$REPO_URL#readme\"|" \
    -e "s|^SUPPORT_URL=.*|SUPPORT_URL=\"$REPO_URL/issues\"|" \
    -e "s|^BUG_REPORT_URL=.*|BUG_REPORT_URL=\"$REPO_URL/issues\"|" \
    /usr/lib/os-release
grep -q '^LOGO=' /usr/lib/os-release || echo 'LOGO=distributor-logo' >> /usr/lib/os-release

# --- The NanoBorealis look ------------------------------------------------------------------
# Every override here has a check in tests/image-checks.sh, so an upstream update that replaces
# one of these files fails the build instead of quietly bringing Aurora's look back.
B=/ctx/branding

# The star, wherever KDE and other apps look for the distribution's logo.
install -Dm0644 "$B/nanoborealis.svg" /usr/share/icons/hicolor/scalable/apps/nanoborealis.svg
install -Dm0644 "$B/nanoborealis-mark.svg" /usr/share/icons/hicolor/scalable/places/distributor-logo.svg
install -Dm0644 "$B/nanoborealis-mark.svg" /usr/share/icons/hicolor/scalable/distributor-logo.svg
install -Dm0644 "$B/nanoborealis-symbolic.svg" /usr/share/icons/hicolor/scalable/places/distributor-logo-symbolic.svg
install -Dm0644 "$B/os/nanoborealis-mark-white.svg" /usr/share/icons/hicolor/scalable/places/distributor-logo-white.svg
install -Dm0644 "$B/os/system-logo.png" /usr/share/pixmaps/system-logo.png
install -Dm0644 "$B/os/system-logo-white.png" /usr/share/pixmaps/system-logo-white.png
gtk-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true

# The desktop: Aurora's look-and-feel, as NanoBorealis, with the aurora wallpaper and star splash.
aurora_lnf=/usr/share/plasma/look-and-feel/dev.getaurora.aurora.desktop
lnf=/usr/share/plasma/look-and-feel/org.nanoborealis.desktop
rm -rf "$lnf"
cp -a "$aurora_lnf" "$lnf"
python3 - "$lnf" <<'PY'
import json, re, sys
from pathlib import Path
lnf = Path(sys.argv[1])
meta_file = lnf / "metadata.json"
meta = json.loads(meta_file.read_text())
plugin = meta.setdefault("KPlugin", {})
for key in [k for k in plugin if k.startswith(("Name[", "Description["))]:
    del plugin[key]  # translations would still say Aurora
plugin.update(Id="org.nanoborealis.desktop", Name="NanoBorealis",
              Description="Breeze Dark under an aurora: the NanoBorealis desktop")
meta_file.write_text(json.dumps(meta, indent=4) + "\n")
defaults = lnf / "contents" / "defaults"
text = re.sub(r"(?ms)^\[Wallpaper\].*?(?=^\[|\Z)", "", defaults.read_text())
text = text.replace("Theme=dev.getaurora.aurora", "Theme=org.nanoborealis.desktop")
defaults.write_text(text.rstrip() + "\n\n[Wallpaper]\nImage=NanoBorealis\n")
for script in (lnf / "contents").rglob("*.js"):  # a layout may name Aurora's wallpaper directly
    old = script.read_text()
    new = old.replace("/usr/share/wallpapers/Aurora", "/usr/share/wallpapers/NanoBorealis")
    if new != old:
        script.write_text(new)
PY
find "$lnf/contents/splash" -type f \( -iname '*logo*' -o -iname '*aurora*' \) 2>/dev/null | while read -r art; do
    case "$art" in
        *.svgz) gzip -c "$B/os/nanoborealis-mark-white.svg" > "$art" ;;
        *.svg) cp "$B/os/nanoborealis-mark-white.svg" "$art" ;;
        *.png) cp "$B/os/system-logo-white.png" "$art" ;;
    esac
done
kwriteconfig6 --file /etc/xdg/kdeglobals --group KDE --key LookAndFeelPackage org.nanoborealis.desktop
kwriteconfig6 --file /etc/xdg/kscreenlockerrc --group Greeter --group Wallpaper --group org.kde.image \
    --group General --key Image "file:///usr/share/wallpapers/NanoBorealis/"

# fastfetch shows the star.
sed -i 's|/usr/share/ublue-os/aurora-ascii-logo.txt|/usr/share/nanoborealis/fastfetch-logo.txt|' \
    /usr/share/ublue-os/fastfetch.jsonc
sed -i 's|"1": "white"|"1": "#5eead4"|' /usr/share/ublue-os/fastfetch.jsonc

# Boot splash: the star on a night sky, with Fedora's spinner. The initramfs carries the theme,
# so it's rebuilt the way Aurora builds it.
theme=/usr/share/plymouth/themes/nanoborealis
mkdir -p "$theme"
cp /usr/share/plymouth/themes/spinner/*.png "$theme/"
install -m0644 "$B/os/plymouth-watermark.png" "$theme/watermark.png"
cat > "$theme/nanoborealis.plymouth" <<EOF
[Plymouth Theme]
Name=NanoBorealis
Description=The NanoBorealis star while the computer starts
ModuleName=two-step

[two-step]
ImageDir=$theme
DialogHorizontalAlignment=.5
DialogVerticalAlignment=.382
TitleHorizontalAlignment=.5
TitleVerticalAlignment=.382
HorizontalAlignment=.5
VerticalAlignment=.72
WatermarkHorizontalAlignment=.5
WatermarkVerticalAlignment=.42
Transition=none
TransitionDuration=0.0
BackgroundStartColor=0x060a1d
BackgroundEndColor=0x060a1d
EOF
plymouth-set-default-theme nanoborealis
KERNEL_VERSION="$(rpm -q --queryformat='%{evr}.%{arch}' kernel-core)"
export DRACUT_NO_XATTR=1
/usr/bin/dracut --kver "$KERNEL_VERSION" --reproducible -v -f "/usr/lib/modules/$KERNEL_VERSION/initramfs.img"
chmod 0600 "/usr/lib/modules/$KERNEL_VERSION/initramfs.img"
