"""Finds NanoBorealis machines on the local network, the way computers find printers (mDNS).

A NanoBorealis machine announces `_nanoborealis._tcp` while remote access is on
(`nanoborealis remote on`). Nothing here imports Flet.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

SERVICE = "_nanoborealis._tcp.local."


@dataclass(frozen=True)
class Found:
    name: str  # "NanoBorealis on laptop"
    host: str  # laptop.local
    address: str
    port: int

    @property
    def url(self) -> str:
        return f"http://{self.address}:{self.port}"


def browse(seconds: float = 3.0) -> list[Found]:
    """NanoBorealis machines that answer within `seconds`. Empty if mDNS isn't available."""
    try:
        from zeroconf import IPVersion, ServiceBrowser, ServiceListener, Zeroconf
    except ImportError:
        return []
    found: dict[str, Found] = {}

    class Listener(ServiceListener):
        def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            self.resolve(zc, type_, name)

        def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            self.resolve(zc, type_, name)

        def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            found.pop(name, None)

        def resolve(self, zc: Zeroconf, type_: str, name: str) -> None:
            info = zc.get_service_info(type_, name, timeout=1500)
            addresses = info.parsed_addresses() if info else []
            if not info or not addresses:
                return
            label = name[: -len(type_) - 1] if name.endswith("." + type_) else name
            found[name] = Found(label, (info.server or "").rstrip("."), addresses[0], info.port or 8765)

    try:
        zc = Zeroconf(ip_version=IPVersion.V4Only)
    except OSError:
        return []  # no multicast on this network or platform
    browser = ServiceBrowser(zc, SERVICE, Listener())
    try:
        time.sleep(seconds)
    finally:
        browser.cancel()
        zc.close()
    return sorted(found.values(), key=lambda f: f.name)
