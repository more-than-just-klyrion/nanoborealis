"""Talks to this computer's pool node (exo) for `nanoborealis pool`.

    python3 pool.py wait            wait until the node answers
    python3 pool.py status          the pool's computers, their memory, and the models they serve
    python3 pool.py serve <model>   spread a model over the pool and wait until it answers
    python3 pool.py stop <model>    stop serving a model (its download stays on disk)
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = "http://127.0.0.1:52415"


def call(method: str, path: str, body: object = None, timeout: float = 30):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(API + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read() or b"null")


def unwrap(value):
    """exo tags variants as {"KindName": {...}}; returns (kind, fields)."""
    if isinstance(value, dict) and len(value) == 1:
        kind, inner = next(iter(value.items()))
        if kind[:1].isupper() and isinstance(inner, dict):
            return kind, inner
    return "", value if isinstance(value, dict) else {}


def size(memory) -> int:
    if isinstance(memory, dict):
        return int(memory.get("inBytes") or 0)
    return int(memory or 0)


def gb(n: int) -> str:
    return f"{n / 1024**3:.1f} GB"


def find(value, key: str):
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for inner in value.values():
            found = find(inner, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for inner in value:
            found = find(inner, key)
            if found is not None:
                return found
    return None


def instances(state) -> list[dict]:
    found = []
    for instance_id, wrapped in (state.get("instances") or {}).items():
        _, inner = unwrap(wrapped)
        shards = inner.get("shardAssignments") or {}
        found.append({"id": instance_id, "model": shards.get("modelId"),
                      "nodes": sorted(shards.get("nodeToRunner") or {}),
                      "runners": list((shards.get("nodeToRunner") or {}).values())})
    return found


def names(state) -> dict[str, str]:
    identities = state.get("nodeIdentities") or {}
    return {node: (identities.get(node) or {}).get("friendlyName") or node[:12]
            for node in set(identities) | set(state.get("lastSeen") or {})}


def runner_states(state, runners: list[str]) -> list[str]:
    return [unwrap((state.get("runners") or {}).get(r))[0].removeprefix("Runner") or "?" for r in runners]


def downloads(state, model: str | None = None) -> list[str]:
    lines = []
    for node, entries in (state.get("downloads") or {}).items():
        for entry in entries or []:
            kind, inner = unwrap(entry)
            model_id = find(inner.get("shardMetadata"), "modelId")
            if model and model_id != model:
                continue
            who = names(state).get(node, node[:12])
            if kind == "DownloadOngoing":
                progress = inner.get("downloadProgress") or {}
                done, total = size(progress.get("downloaded")), size(progress.get("total"))
                percent = f"{100 * done / total:.0f}%" if total else "starting"
                lines.append(f"{who}: downloading {model_id} ({percent} of {gb(total)})")
            elif kind == "DownloadFailed":
                lines.append(f"{who}: download of {model_id} failed: {inner.get('errorMessage')}")
            elif kind == "DownloadPending" and model:
                lines.append(f"{who}: waiting to download {model_id}")
    return lines


def wait_for_node(seconds: int = 300) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            call("GET", "/node_id", timeout=5)
            return
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(3)
    sys.exit("the pool node didn't start; see: nanoborealis pool logs")


def status() -> None:
    try:
        state = call("GET", "/state")
    except (urllib.error.URLError, OSError) as error:
        sys.exit(f"this computer's pool node isn't answering ({error}); start it with: nanoborealis pool join")
    who = names(state)
    memory = state.get("nodeMemory") or {}
    seen = state.get("lastSeen") or {}
    now = datetime.now(timezone.utc)
    total_ram = free_ram = 0
    print(f"Computers in the pool: {len(who)}")
    for node, name in sorted(who.items(), key=lambda item: item[1].lower()):
        ram = memory.get(node) or {}
        total, free = size(ram.get("ramTotal")), size(ram.get("ramAvailable"))
        total_ram, free_ram = total_ram + total, free_ram + free
        age = ""
        if node in seen:
            try:
                last = datetime.fromisoformat(str(seen[node]).replace("Z", "+00:00"))
                age = f", seen {int((now - last).total_seconds())} s ago"
            except ValueError:
                pass
        print(f"  {name:<28} {gb(free)} free of {gb(total)}{age}")
    print(f"  {'together':<28} {gb(free_ram)} free of {gb(total_ram)}")
    running = instances(state)
    print(f"Models served: {len(running)}")
    for instance in running:
        spread = ", ".join(who.get(n, n[:12]) for n in instance["nodes"])
        states = "/".join(sorted(set(runner_states(state, instance["runners"]))))
        print(f"  {instance['model']}  on {spread}  ({states})")
    for line in downloads(state):
        print(f"  {line}")


def serve(model: str) -> None:
    wait_for_node()
    if not any(i["model"] == model for i in instances(call("GET", "/state"))):
        try:
            call("POST", "/place_instance", {"model_id": model}, timeout=120)
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:300]
            sys.exit(f"the pool can't serve {model}: HTTP {error.code} {detail}")
    print(f"Spreading {model} over the pool. The first time, every computer that holds a part of it")
    print("downloads that part, which can take a long while for big models. Ctrl+C stops waiting;")
    print("the pool carries on, and 'nanoborealis pool status' shows how far it got.")
    last, started = "", time.time()
    while True:
        state = call("GET", "/state")
        mine = [i for i in instances(state) if i["model"] == model]
        progress = downloads(state, model)
        if mine:
            states = runner_states(state, mine[0]["runners"])
            line = f"on {len(mine[0]['nodes'])} computer(s): {'/'.join(sorted(set(states)))}"
            if states and all(s in ("Ready", "Running") for s in states) and answers(model):
                print(f"{model} is ready, served by {len(mine[0]['nodes'])} computer(s) "
                      f"after {int(time.time() - started)} s.")
                return
        else:
            line = "waiting for the pool to place it"
        line = "; ".join([line, *progress])
        if line != last:
            print(f"  {line}", flush=True)
            last = line
        if any("failed" in p for p in progress):
            sys.exit("a download failed; try again later, or pick another model")
        time.sleep(10)


def answers(model: str) -> bool:
    try:
        reply = call("POST", "/v1/chat/completions", {
            "model": model, "max_tokens": 8, "messages": [{"role": "user", "content": "Reply with OK."}]},
            timeout=900)
        return bool(reply.get("choices"))
    except (urllib.error.URLError, OSError, ValueError):
        return False


def stop(model: str) -> None:
    stopped = 0
    for instance in instances(call("GET", "/state")):
        if instance["model"] == model:
            call("DELETE", f"/instance/{instance['id']}")
            stopped += 1
    print(f"stopped serving {model}" if stopped else f"{model} wasn't being served")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    try:
        if action == "wait":
            wait_for_node()
        elif action == "status":
            status()
        elif action == "serve" and len(sys.argv) == 3:
            serve(sys.argv[2])
        elif action == "stop" and len(sys.argv) == 3:
            stop(sys.argv[2])
        else:
            sys.exit(__doc__)
    except KeyboardInterrupt:
        print("\nStopped waiting; the pool carries on. Check on it with: nanoborealis pool status")
