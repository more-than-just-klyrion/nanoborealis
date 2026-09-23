#!/usr/bin/bash
# Runs inside a built NanoBorealis image. The build runs it before publishing to the testing
# channel and the Promote workflow runs it again before stable, so an upstream Aurora change
# that breaks our layer stops here instead of on someone's computer.
set -u
fail=0
pass() { echo "ok   $1"; }
flunk() { echo "FAIL $1"; fail=1; }
expect() {  # description, command...
    local what="$1"; shift
    if "$@" >/dev/null 2>&1; then pass "$what"; else flunk "$what"; fi
}

# Identity: our name everywhere users see it, Aurora's ID where ublue tooling looks.
. /usr/lib/os-release
[ "${NAME:-}" = NanoBorealis ] && pass "os-release NAME is NanoBorealis" || flunk "os-release NAME is '${NAME:-}'"
[ "${ID:-}" = aurora ] && pass "os-release ID stays aurora" || flunk "os-release ID changed to '${ID:-}' upstream"

# Our commands and scripts.
expect "nanoborealis command" test -x /usr/bin/nanoborealis
expect "earlier command names still work" test -x /usr/bin/nanoaurora -a -x /usr/bin/nanobot-os
for f in /usr/libexec/nanoborealis-firewall /usr/libexec/nanoborealis-migrate /usr/libexec/nanoborealis-firstrun \
         /usr/libexec/nanoborealis-setup-from-stick /usr/share/nanoborealis/install.sh \
         /usr/share/nanoborealis/nanoborealis /usr/share/nanoborealis/image/entrypoint.sh; do
    expect "$f is executable" test -x "$f"
done
for f in /usr/share/nanoborealis/install.sh /usr/share/nanoborealis/nanoborealis \
         /usr/libexec/nanoborealis-firewall /usr/libexec/nanoborealis-migrate /usr/libexec/nanoborealis-firstrun; do
    expect "$f parses" bash -n "$f"
done
expect "setup-from-stick compiles" python3 -c 'import ast, sys; ast.parse(open(sys.argv[1]).read())' \
    /usr/libexec/nanoborealis-setup-from-stick
expect "compute-config compiles" python3 -c 'import ast, sys; ast.parse(open(sys.argv[1]).read())' \
    /usr/share/nanoborealis/compute-config.py

# Services and update policy.
expect "network guard enabled" systemctl is-enabled nanoborealis-firewall.service
expect "migration enabled" systemctl is-enabled nanoborealis-migrate.service
for timer in uupd.timer bootc-fetch-apply-updates.timer rpm-ostreed-automatic.timer; do
    state="$(systemctl is-enabled "$timer" 2>/dev/null || true)"
    [ "$state" = masked ] && pass "$timer masked (updates are opt-in)" || flunk "$timer is '$state', not masked"
done

# What first login and the menus need.
expect "first-login setup in autostart" test -f /etc/xdg/autostart/nanoborealis-firstrun.desktop
expect "app menu entries" test -f /usr/share/applications/nanoborealis.desktop -a -f /usr/share/applications/nanoborealis-update.desktop
if command -v desktop-file-validate >/dev/null; then
    expect "desktop entries validate" desktop-file-validate /usr/share/applications/nanoborealis.desktop \
        /usr/share/applications/nanoborealis-update.desktop /etc/xdg/autostart/nanoborealis-firstrun.desktop
fi
for tool in nft konsole podman python3 bootc flatpak; do
    expect "$tool is present" command -v "$tool"
done

# The migration from earlier names, run against a simulated NanoAurora-era layout. This runs in
# a throwaway container, so it may change things.
mkdir -p /srv/nanoaurora/projects /var/home/olduser/Desktop /etc/nanoaurora/compute.d
echo marker > /srv/nanoaurora/projects/kept.txt
ln -s /srv/nanoaurora/projects /var/home/olduser/nanoaurora-projects
cp /usr/share/applications/nanoborealis-update.desktop /var/home/olduser/Desktop/nanoaurora-update.desktop
printf 'ip=10.0.0.5\nport=11435\n' > /etc/nanoaurora/compute.d/laptop2
first="$(/usr/libexec/nanoborealis-migrate 2>&1)"
echo "$first" | sed 's/^/     /'
expect "migration moved the projects folder and its files" test -f /srv/nanoborealis/projects/kept.txt -a ! -e /srv/nanoaurora
[ "$(readlink /var/home/olduser/nanoborealis-projects)" = /srv/nanoborealis/projects ] \
    && [ ! -e /var/home/olduser/nanoaurora-projects ] && pass "migration relinked the user's projects shortcut" \
    || flunk "migration relinked the user's projects shortcut"
expect "migration replaced the desktop update icon" test -f /var/home/olduser/Desktop/nanoborealis-update.desktop \
    -a ! -e /var/home/olduser/Desktop/nanoaurora-update.desktop
expect "migration kept approved compute devices" test -f /etc/nanoborealis/compute.d/laptop2
second="$(/usr/libexec/nanoborealis-migrate 2>&1)"
[ "$second" = "nanoborealis-migrate: nothing to migrate" ] && pass "a second migration run changes nothing" \
    || flunk "a second migration run said: $second"

if [ "$fail" -eq 0 ]; then echo "all image checks passed"; else echo "image checks FAILED"; fi
exit "$fail"
