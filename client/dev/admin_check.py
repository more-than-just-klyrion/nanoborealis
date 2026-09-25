"""Checks the control center's endpoints on the remote-access service, end to end.

The service runs in test mode with NANOBOREALIS_REMOTE_TEST_AGENT_HOME, a folder standing in for
the agent's home (see .github/workflows/test-client.yml):

    python dev/admin_check.py 127.0.0.1:18868 /tmp/pin3 /tmp/agenthome

Exits non-zero on the first failed check.
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import admin  # noqa: E402
from pairing import Machine, NotPaired, split_address  # noqa: E402
from checks import check, pair  # noqa: E402


def refused(fn, *args) -> str:
    try:
        fn(*args)
    except admin.AdminError as e:
        return str(e)
    return ""


def main(address: str, pin_file: str, home: str) -> None:
    host, port = split_address(address)
    machine = pair(host, port, pin_file, "Control center check")
    check(admin.supported(machine), "the computer offers the control center")
    config_path = os.path.join(home, ".nanobot", "config.json")
    for _ in range(50):
        config = json.load(open(config_path))
        if config["agents"]["defaults"].get("model"):
            break
        time.sleep(0.2)
    limit = config["providers"]["openrouter"].get("extraBody", {}).get("provider", {}).get("max_price", {})
    check(config["agents"]["defaults"].get("model", "").endswith(":free") and limit.get("prompt") == 0,
          "an agent set up before free-only is kept to free models")
    check(config["providers"]["openrouter"]["apiKey"] == "${OPENROUTER_API_KEY}" and
          config["agents"]["defaults"]["modelPreset"] == "ultra", "...and nothing else in its config changes")
    info = admin.overview(machine)
    check(info["agent"]["running"] and info["machine"], f"overview: the agent's state ({info['agent']['state']})")

    admin.write_file(machine, f"{admin.WORKSPACE}/memory/MEMORY.md", "# Memory\n- likes tea\n")
    check(admin.read_file(machine, f"{admin.WORKSPACE}/memory/MEMORY.md") == "# Memory\n- likes tea\n",
          "a workspace file round-trips")
    check(any(f["path"].endswith("memory/MEMORY.md") for f in admin.list_files(machine)), "workspace files are listed")
    for bad in ("../../../etc/passwd", "/etc/passwd", f"{admin.WORKSPACE}/../../.ssh/id_rsa", ".nanobot/config.json",
                ".nanobot/sessions/x.jsonl"):
        check(refused(admin.read_file, machine, bad) != "" and refused(admin.write_file, machine, bad, "x") != "",
              f"stays out of {bad}")
    os.symlink("/etc/hostname", os.path.join(home, ".nanobot", "workspace", "escape.md"))
    check(refused(admin.read_file, machine, f"{admin.WORKSPACE}/escape.md") != "",
          "a link out of the agent's home is not followed")
    admin.delete_file(machine, f"{admin.WORKSPACE}/memory/MEMORY.md")
    check(refused(admin.read_file, machine, f"{admin.WORKSPACE}/memory/MEMORY.md") != "", "a file can be deleted")

    check("no OpenRouter key" in admin.usage(machine).get("error", ""), "usage says when there's no key")
    check("sk-or-" in refused(admin.set_key, machine, "hunter2"), "a key that isn't one is turned down")
    admin.set_key(machine, "sk-or-v1-" + "0" * 64)
    check(open(os.path.join(home, ".openrouter-key")).read() == "sk-or-v1-" + "0" * 64, "a new key is saved")

    listed = admin.devices(machine)
    check(any(d["this"] and d["id"] == machine.device_id for d in listed), "devices: this one is marked")
    other = pair(host, port, pin_file, "Second device")
    admin.remove_device(machine, other.device_id)
    try:
        admin.overview(other)
        check(False, "a removed device is locked out")
    except NotPaired:
        check(True, "a removed device is locked out")
    stranger = Machine(host, port, machine.name, machine.certificate, "unknown-" * 6, "0000")
    try:
        admin.overview(stranger)
        check(False, "an unknown device gets nothing")
    except NotPaired:
        check(True, "an unknown device gets nothing")
    print("all control center checks passed")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
