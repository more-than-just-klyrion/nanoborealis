"""The control center's calls to a NanoBorealis computer's pairing service (nanoborealis-remote),
for what nanobot can't do itself: the agent container's state, logs and restarts, its OpenRouter
key and what that key has spent, its memory files, and the paired devices. (Models, channels,
skills and schedules go through nanobot's own settings: AgentLink.request.)

The computer allows them to devices paired by one of its administrators. Every call blocks: run
them in a thread.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from pairing import DEVICE_HEADER, Machine, NotPaired, PairingError, call

WORKSPACE = ".nanobot/workspace"


class AdminError(PairingError):
    """The computer turned the request down, or couldn't carry it out."""


def _call(machine: Machine, method: str, path: str, body: dict | None = None, timeout: float = 45) -> dict[str, Any]:
    status, data, _ = call(machine.host, machine.port, method, path, context=machine.context(), body=body,
                           headers={DEVICE_HEADER: machine.password}, timeout=timeout)
    if status == 401:
        raise NotPaired("This computer doesn't know this device anymore. Pair it again.")
    if status == 404 and not data.get("error"):
        raise AdminError("This computer's NanoBorealis is too old for the control center. Update it.")
    if status != 200:
        raise AdminError(str(data.get("error") or f"The computer answered HTTP {status}."))
    return data


def supported(machine: Machine) -> bool:
    status, data, _ = call(machine.host, machine.port, "GET", "/nanoborealis/hello", context=machine.context())
    return status == 200 and bool(data.get("admin"))


def overview(machine: Machine) -> dict[str, Any]:
    return _call(machine, "GET", "/nanoborealis/agent")


def read_file(machine: Machine, path: str) -> str:
    return str(_call(machine, "GET", "/nanoborealis/agent/file?" + urllib.parse.urlencode({"path": path}))["content"])


def list_files(machine: Machine, path: str = WORKSPACE) -> list[dict[str, Any]]:
    return list(_call(machine, "GET", "/nanoborealis/agent/files?" + urllib.parse.urlencode({"path": path}))["files"])


def write_file(machine: Machine, path: str, content: str) -> None:
    _call(machine, "POST", "/nanoborealis/agent/file", {"path": path, "content": content})


def delete_file(machine: Machine, path: str) -> None:
    _call(machine, "POST", "/nanoborealis/agent/file", {"path": path, "content": "", "delete": True})


def logs(machine: Machine, lines: int = 300) -> list[str]:
    return list(_call(machine, "GET", f"/nanoborealis/agent/logs?lines={int(lines)}")["lines"])


def restart(machine: Machine) -> dict[str, Any]:
    return _call(machine, "POST", "/nanoborealis/agent/restart", {}, timeout=320)["agent"]


def usage(machine: Machine, fresh: bool = False) -> dict[str, Any]:
    return _call(machine, "GET", "/nanoborealis/agent/usage" + ("?fresh=1" if fresh else ""))


def set_key(machine: Machine, key: str) -> None:
    _call(machine, "POST", "/nanoborealis/agent/key", {"key": key}, timeout=320)


def devices(machine: Machine) -> list[dict[str, Any]]:
    return list(_call(machine, "GET", "/nanoborealis/devices")["devices"])


def remove_device(machine: Machine, device_id: str) -> None:
    _call(machine, "POST", "/nanoborealis/devices/remove", {"id": device_id})
