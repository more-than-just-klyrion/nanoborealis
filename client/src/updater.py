"""Updates for the packaged app, from its GitHub releases, on one of three channels:

    stable   client-vX.Y.Z          releases everyone gets
    testing  client-vX.Y.Z-rc.N     candidates for the next stable version (pre-releases)
    dev      client-vX.Y.Z-dev.N    built from every change to the app (pre-releases)

A channel offers its own builds and every more stable one, so testing also gets stable
releases, and dev gets everything. Versions order as semver does: 0.3.0-dev.9 < 0.3.0-rc.2 <
0.3.0.

Only the packaged app updates itself; running from source updates with git. An update is found,
downloaded, checked against the release's SHA256SUMS, and only then installed:

- Windows: the installer runs silently, replaces the app, and reopens it.
- Linux: the archive's install.sh runs, then the app reopens.
- macOS: the disk image opens, to drag the new app over the old one.

Nothing here imports Flet.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from typing import Callable

from version import VERSION

REPO = "more-than-just-kyrion/nanoborealis"
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-(rc|dev)\.(\d+))?$")
CHANNELS = {"stable": (None,), "testing": (None, "rc"), "dev": (None, "rc", "dev")}
RANK = {"dev": 0, "rc": 1, None: 2}  # a release outranks its own candidates and dev builds


class UpdateError(Exception):
    pass


@dataclass
class Update:
    version: str
    notes_url: str
    asset_name: str
    asset_url: str
    size: int
    sums_url: str


def parse(version: str) -> tuple[int, int, int, int, int] | None:
    """A sort key: major, minor, patch, then stable above rc above dev, then the build number."""
    match = VERSION_RE.match(version)
    if not match:
        return None
    major, minor, patch, kind, number = match.groups()
    return int(major), int(minor), int(patch), RANK[kind], int(number or 0)


def channel_of(version: str) -> str:
    """The channel a build came from: the one it keeps following unless the owner changes it."""
    match = VERSION_RE.match(version)
    kind = match.group(4) if match else None
    return {"rc": "testing", "dev": "dev"}.get(kind, "stable")


def can_update() -> bool:
    """Only a packaged build knows its version and can replace itself."""
    return bool(getattr(sys, "frozen", False)) and parse(VERSION) is not None


def asset_for_platform(version: str) -> str:
    if sys.platform == "win32":
        return f"NanoBorealis-Setup-{version}.exe"
    if sys.platform == "darwin":
        return f"NanoBorealis-{version}-macos.dmg"
    return f"NanoBorealis-{version}-linux-x86_64.tar.gz"


def newest(releases: list[dict], channel: str) -> tuple[str, dict] | None:
    """The newest release a channel accepts, as (version, release)."""
    kinds = CHANNELS.get(channel, CHANNELS["stable"])
    best: tuple[tuple, str, dict] | None = None
    for release in releases:
        tag = release.get("tag_name", "")
        if release.get("draft") or not tag.startswith("client-v"):
            continue
        version = tag[len("client-v"):]
        match = VERSION_RE.match(version)
        if not match or match.group(4) not in kinds:
            continue
        key = parse(version)
        if best is None or key > best[0]:
            best = (key, version, release)
    return (best[1], best[2]) if best else None


def check(channel: str = "stable") -> Update | None:
    """The newest release on `channel`, if it's newer than this app and has a file for this platform."""
    current = parse(VERSION)
    if current is None:
        return None
    request = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases?per_page=100",
                                     headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        releases = json.loads(response.read())
    found = newest(releases, channel)
    if found is None or parse(found[0]) <= current:
        return None
    version, release = found
    assets = {a["name"]: a for a in release.get("assets", [])}
    name = asset_for_platform(version)
    if name not in assets or "SHA256SUMS" not in assets:
        return None
    return Update(version, release.get("html_url", ""), name, assets[name]["browser_download_url"],
                  int(assets[name].get("size") or 0), assets["SHA256SUMS"]["browser_download_url"])


def download(update: Update, progress: Callable[[int, int], None] | None = None) -> str:
    """Download the update and check it against the release checksums. Returns the file path."""
    with urllib.request.urlopen(update.sums_url, timeout=30) as response:
        sums = response.read().decode()
    expected = next((line.split()[0].lower() for line in sums.splitlines()
                     if line.strip().endswith(update.asset_name)), None)
    if not expected:
        raise UpdateError(f"the release lists no checksum for {update.asset_name}")
    folder = tempfile.mkdtemp(prefix="nanoborealis-update-")
    path = os.path.join(folder, update.asset_name)
    digest = hashlib.sha256()
    done = 0
    with urllib.request.urlopen(update.asset_url, timeout=60) as response, open(path, "wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, update.size)
    if digest.hexdigest() != expected:
        os.remove(path)
        raise UpdateError("the download doesn't match the release checksum; nothing was installed")
    return path


def install(path: str) -> None:
    """Start installing a verified download. The caller quits the app right after."""
    if sys.platform == "win32":
        # Silent install over this one; the installer closes this app, replaces it, reopens it.
        subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                         close_fds=True, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        folder = os.path.dirname(path)
        with tarfile.open(path) as archive:
            archive.extractall(folder, filter="data")
        top = next(os.path.join(folder, d) for d in os.listdir(folder)
                   if os.path.isdir(os.path.join(folder, d)))
        launcher = os.path.join(os.path.expanduser("~"), ".local/share/nanoborealis/NanoBorealis")
        subprocess.Popen(["sh", "-c", f'sleep 2 && "{top}/install.sh" && exec "{launcher}"'],
                         start_new_session=True)
