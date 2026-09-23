#!/usr/bin/bash
# Prints the branding-relevant parts of an image (upstream Aurora or a NanoBorealis build):
# look-and-feel packages, wallpapers, boot splash, login theme, logos, fastfetch, and the
# config that selects them. Upstream's output is the baseline the reskin is checked against.
set -u
section() { printf '\n== %s\n' "$1"; }

section "os-release"
grep -E '^(NAME|PRETTY_NAME|ID|VARIANT_ID|LOGO|VERSION_ID)=' /usr/lib/os-release

section "look-and-feel packages"
ls /usr/share/plasma/look-and-feel/ 2>/dev/null
section "default look-and-feel and theme settings (/etc/xdg)"
grep -rH -E 'LookAndFeelPackage|ColorScheme|Theme=|Image=|widgetStyle|iconTheme|cursorTheme' \
    /etc/xdg/kdeglobals /etc/xdg/plasmarc /etc/xdg/kscreenlockerrc /etc/xdg/ksplashrc 2>/dev/null
section "look-and-feel defaults"
for d in /usr/share/plasma/look-and-feel/*/contents/defaults; do echo "-- $d"; cat "$d"; done 2>/dev/null | head -80
section "wallpapers"
ls /usr/share/wallpapers/ 2>/dev/null
section "plymouth"
plymouth-set-default-theme 2>/dev/null || grep -h Theme /etc/plymouth/plymouthd.conf /usr/share/plymouth/plymouthd.defaults 2>/dev/null
ls /usr/share/plymouth/themes/ 2>/dev/null
section "sddm"
ls /usr/share/sddm/themes/ 2>/dev/null
cat /etc/sddm.conf.d/*.conf /usr/lib/sddm/sddm.conf.d/*.conf 2>/dev/null | grep -v '^#' | grep -v '^$' | head -40
for f in /usr/share/sddm/themes/*/theme.conf.user; do echo "-- $f"; cat "$f"; done 2>/dev/null
section "logos and icons"
ls /usr/share/pixmaps/ 2>/dev/null | grep -i -E 'logo|aurora|fedora|system' | head -20
find /usr/share/icons/hicolor -iname '*aurora*' -o -iname '*distributor*' 2>/dev/null | head -20
section "fastfetch"
ls /usr/share/ublue-os/ 2>/dev/null | head -30
find /usr/share/ublue-os /etc/fastfetch /usr/share/fastfetch -maxdepth 2 -name '*.jsonc' 2>/dev/null | head
for f in $(find /usr/share/ublue-os -maxdepth 2 -name '*fastfetch*.jsonc' 2>/dev/null | head -2); do echo "-- $f"; head -40 "$f"; done
section "welcome and first boot"
ls /usr/share/applications/ 2>/dev/null | grep -i -E 'welcome|setup|aurora|ublue' | head -20
ls /etc/xdg/autostart/ 2>/dev/null | head -30
section "kickoff (app launcher) icon"
grep -rl -i 'kickoff' /usr/share/plasma/look-and-feel/*/contents/layouts 2>/dev/null | head -5
grep -rh -o -E 'icon[^,;]{0,80}' /usr/share/plasma/look-and-feel/*/contents/layouts/*.js 2>/dev/null | head -10
