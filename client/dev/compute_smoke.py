"""Checks compute sharing: model fitting, choosing with a benchmark, and the relay.

Start the stand-in Ollama first. It must think qwen3:30b is already installed and make the
two largest models too slow:

    STUB_INSTALLED=qwen3:30b STUB_SPEEDS="qwen3:30b=5,qwen3:14b=6,*=40" python dev/stub_ollama.py 18434 &
    python dev/compute_smoke.py

With a gateway configured by dev/gateway-compute.json running, also pass its address and
password to send a chat turn from nanobot through the relay:

    python dev/compute_smoke.py http://127.0.0.1:18766 test-password
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request

os.environ.setdefault("NANOBOREALIS_OLLAMA_URL", "http://127.0.0.1:18434")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import compute  # noqa: E402
from agent_link import AgentLink  # noqa: E402

TOKEN = "test-device-token"
RELAY_PORT = 18435


def check(ok: bool, what: str) -> None:
    print(("ok   " if ok else "FAIL ") + what, flush=True)
    if not ok:
        raise SystemExit(1)


def hw(ram: float, ram_free: float, vram_free: float = 0.0, disk: float = 500.0, unified: bool = False):
    gpus = [{"name": "Test GPU", "vram_gb": vram_free, "vram_free_gb": vram_free}] if vram_free else []
    return compute.Hardware("Test", "Test CPU", 8, ram, ram_free, gpus, unified, disk)


def plan_names(hardware) -> list[str]:
    return [f"{p.model.tag}@{p.where}/{p.context // 1024}k" for p in compute.plans(hardware)]


def request(method: str, path: str, token: str | None = None, body: dict | None = None) -> tuple[int, bytes]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{RELAY_PORT}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


async def main() -> None:
    this = compute.probe()
    print("     this device:", this.describe())
    print("     would try:", plan_names(this)[:3] or "nothing fits")

    big_gpu = plan_names(hw(64, 48, vram_free=24))
    check(big_gpu[0] == "qwen3:30b@gpu/16k", f"24 GB GPU starts with the 30B MoE on the GPU ({big_gpu[0]})")
    laptop = plan_names(hw(32, 28, vram_free=8))
    check(laptop[0].startswith("qwen3:30b@cpu") and "qwen3:4b@gpu/32k" in laptop,
          f"8 GB GPU + 32 GB RAM: MoE from RAM, 4B on the GPU ({laptop[:2]})")
    cpu_only = plan_names(hw(16, 10))
    check(cpu_only and cpu_only[0] == "qwen3:4b@cpu/32k" and not any("8b" in p or "14b" in p for p in cpu_only),
          f"CPU only: no dense model past 4B ({cpu_only})")
    check(plan_names(hw(4, 1.5)) == [], "a device with too little memory gets nothing")
    check(all("30b" not in p and "14b" not in p for p in plan_names(hw(64, 48, vram_free=24, disk=8))),
          "models that don't fit on the disk are skipped")

    check(compute.ollama_version() is not None, "the stand-in Ollama answers")
    steps: list[str] = []
    choice = compute.choose(hw(64, 48, vram_free=24), lambda text, fraction: steps.append(text))
    print("     steps:", " | ".join(s for s in steps if not s.startswith("Downloading qwen3") or ":" not in s[12:]))
    check(choice.plan.model.tag == "qwen3:8b" and choice.gen_tps >= compute.MIN_GEN_TPS,
          f"chose the largest fast-enough model ({choice.plan.model.tag}, {choice.gen_tps:.0f} tokens/s)")
    with urllib.request.urlopen(f"{compute.OLLAMA_URL}/stub/log") as response:
        state = json.loads(response.read())
    log, models = state["log"], set(state["models"])
    check("pull qwen3:30b" not in log and "qwen3:30b" in models, "a model that was already installed is kept")
    check("pull qwen3:14b" in log and "qwen3:14b" not in models, "a model it downloaded and rejected is deleted")
    check(choice.served in models and "ctx=" in " ".join(log), f"serves {choice.served} with a fixed context")

    relay = compute.Relay(TOKEN, port=RELAY_PORT, host="127.0.0.1", upstream=compute.OLLAMA_URL)
    await relay.start()
    try:
        status, _ = await asyncio.to_thread(request, "GET", "/v1/models")
        check(status == 401, f"relay refuses requests without the token ({status})")
        status, _ = await asyncio.to_thread(request, "GET", "/v1/models", "wrong-token")
        check(status == 401, f"relay refuses a wrong token ({status})")
        status, _ = await asyncio.to_thread(request, "GET", "/api/tags", TOKEN)
        check(status == 403, f"relay refuses Ollama's own API, even with the token ({status})")
        status, _ = await asyncio.to_thread(request, "POST", "/api/delete", TOKEN, {"model": choice.served})
        check(status == 403, f"so the agent can't delete models ({status})")
        status, body = await asyncio.to_thread(request, "POST", "/v1/chat/completions", TOKEN, {
            "model": choice.served, "stream": True, "messages": [{"role": "user", "content": "hello relay"}]})
        streamed = "".join(
            json.loads(line[6:])["choices"][0]["delta"].get("content") or ""
            for line in body.decode().splitlines() if line.startswith("data: {")
        )
        check(status == 200 and "Stub reply to" in streamed and b"[DONE]" in body,
              f"streams a chat reply through the relay (HTTP {status}, {len(streamed)} characters)")

        if len(sys.argv) >= 3:
            events: asyncio.Queue[dict] = asyncio.Queue()

            async def on_event(event: dict) -> None:
                await events.put(event)

            link = AgentLink(sys.argv[1], sys.argv[2], on_event)
            runner = asyncio.create_task(link.run())
            try:
                while (await asyncio.wait_for(events.get(), 30))["event"] != "link_up":
                    pass
                chat = await link.new_chat()
                before = relay.requests
                await link.send_message(chat, "hello through the device")
                text = ""
                while True:
                    event = await asyncio.wait_for(events.get(), 60)
                    if event["event"] in ("delta", "stream_end", "message"):
                        text += str(event.get("text") or "")
                    if event["event"] == "turn_end":
                        break
                check("Stub reply to" in text and relay.requests > before,
                      f"nanobot answered through the relay ({relay.requests - before} request(s); "
                      f"reply starts {text.strip()[:40]!r})")
            finally:
                await link.close()
                runner.cancel()
    finally:
        await relay.stop()
    print("all compute checks passed")


if __name__ == "__main__":
    asyncio.run(main())
