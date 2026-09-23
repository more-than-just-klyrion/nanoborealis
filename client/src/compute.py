"""Runs a local model on this device for the NanoAurora agent, with the owner's consent.

Ollama does the model work. This module picks the most capable model that fits the
device's memory, checks that it's fast enough, and serves it to the agent through a relay
that needs this device's token and only exposes the OpenAI-compatible chat API, so the
agent can't pull, delete, or reconfigure models. Nothing here imports Flet.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

OLLAMA_URL = os.environ.get("NANOAURORA_OLLAMA_URL", "http://127.0.0.1:11434")
RELAY_PORT = 11435
MIN_GEN_TPS = 10.0  # tokens/s while writing; slower than this feels broken in an agent
MIN_PROMPT_TPS = 150.0  # tokens/s while reading; agent prompts run to thousands of tokens
KV_GB_PER_16K = 2.5  # rough KV-cache cost of a 16K context for these models
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


@dataclass(frozen=True)
class Model:
    tag: str
    download_gb: float
    active_b: float  # billions of parameters used per token, which sets the speed
    moe: bool = False  # mixture of experts: large, but light per token


# Qwen3 supports tool calling at every size in Ollama. Most capable first.
LADDER = [
    Model("qwen3:30b", 19.0, 3.3, moe=True),
    Model("qwen3:14b", 9.3, 14.8),
    Model("qwen3:8b", 5.2, 8.2),
    Model("qwen3:4b", 2.5, 4.0),
    Model("qwen3:1.7b", 1.4, 1.7),
    Model("qwen3:0.6b", 0.52, 0.6),
]


@dataclass
class Hardware:
    system: str
    cpu: str
    cores: int
    ram_gb: float
    ram_free_gb: float
    gpus: list[dict] = field(default_factory=list)  # {"name", "vram_gb", "vram_free_gb"}
    unified_memory: bool = False  # Apple silicon: the GPU shares system memory
    disk_free_gb: float = 0.0

    def describe(self) -> str:
        parts = [f"{self.cores}-core CPU", f"{self.ram_gb:.0f} GB RAM ({self.ram_free_gb:.0f} GB free)"]
        for gpu in self.gpus:
            parts.append(f"{gpu['name']} ({gpu['vram_free_gb']:.1f} of {gpu['vram_gb']:.1f} GB free)")
        if self.unified_memory:
            parts.append("GPU shares system memory")
        parts.append(f"{self.disk_free_gb:.0f} GB free disk")
        return ", ".join(parts)


def _run(cmd: list[str], timeout: float = 10) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              creationflags=_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _memory_gb() -> tuple[float, float]:
    if sys.platform == "win32":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                        ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                        ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                        ("avail_ext_virtual", ctypes.c_ulonglong)]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return status.total_phys / 2**30, status.avail_phys / 2**30
    if sys.platform == "darwin":
        total = int(_run(["sysctl", "-n", "hw.memsize"]).strip() or 0)
        page = int(_run(["sysctl", "-n", "hw.pagesize"]).strip() or 4096)
        stats = _run(["vm_stat"])
        pages = sum(int(m) for m in re.findall(r"Pages (?:free|inactive|speculative|purgeable):\s+(\d+)", stats))
        return total / 2**30, (pages * page / 2**30) if pages else total / 2**30 / 2
    info: dict[str, int] = {}
    with open("/proc/meminfo", encoding="ascii") as meminfo:
        for line in meminfo:
            key, _, value = line.partition(":")
            info[key] = int(value.split()[0]) * 1024
    return info["MemTotal"] / 2**30, info.get("MemAvailable", info["MemFree"]) / 2**30


def _nvidia_gpus() -> list[dict]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    gpus = []
    out = _run([exe, "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"])
    for line in out.strip().splitlines():
        name, _, rest = line.partition(",")
        numbers = [p.strip() for p in rest.split(",")]
        try:
            gpus.append({"name": name.strip(), "vram_gb": float(numbers[0]) / 1024,
                         "vram_free_gb": float(numbers[1]) / 1024})
        except (ValueError, IndexError):
            continue
    return gpus


def _cpu_name() -> str:
    if sys.platform == "darwin":
        return _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip() or platform.machine()
    if sys.platform.startswith("linux"):
        try:
            text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
            match = re.search(r"^model name\s*:\s*(.+)$", text, re.MULTILINE)
            if match:
                return match.group(1).strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()


def models_dir() -> Path:
    return Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models")


def probe() -> Hardware:
    ram, ram_free = _memory_gb()
    target = models_dir()
    while not target.exists() and target != target.parent:
        target = target.parent
    return Hardware(
        system=platform.system(),
        cpu=_cpu_name(),
        cores=os.cpu_count() or 1,
        ram_gb=ram,
        ram_free_gb=ram_free,
        gpus=_nvidia_gpus(),
        unified_memory=sys.platform == "darwin" and platform.machine() == "arm64",
        disk_free_gb=shutil.disk_usage(target).free / 2**30,
    )


@dataclass(frozen=True)
class Plan:
    model: Model
    context: int  # tokens
    where: str  # "gpu" or "cpu"


def plans(hw: Hardware) -> list[Plan]:
    """Models that fit this device, most capable first, with the context each can afford."""
    gpu_free = max((g["vram_free_gb"] for g in hw.gpus), default=0.0)
    if hw.unified_memory:
        gpu_free = min(hw.ram_free_gb, hw.ram_gb * 0.65)
    ram_budget = hw.ram_free_gb * 0.8
    out = []
    for model in LADDER:
        if model.download_gb * 1.1 > hw.disk_free_gb:
            continue
        # Any fit on the GPU beats a fit in system RAM; within each, the longer context wins.
        for where in ("gpu", "cpu"):
            fit = None
            for context in (32768, 16384):
                need = model.download_gb + KV_GB_PER_16K * context / 16384 + 0.5
                if where == "gpu":
                    ok = bool(gpu_free) and need <= gpu_free
                else:
                    # Dense models past ~4B are too slow from system RAM; MoE models are not.
                    ok = (model.moe or model.active_b <= 4.5) and need <= ram_budget + (gpu_free if model.moe else 0)
                if ok:
                    fit = Plan(model, context, where)
                    break
            if fit:
                out.append(fit)
                break
    return out


# -- Ollama ----------------------------------------------------------------------


class OllamaError(Exception):
    pass


def _ollama(method: str, path: str, payload: dict | None = None, timeout: float = 30):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(f"{OLLAMA_URL}{path}", data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise OllamaError(f"Ollama answered HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, OSError) as e:
        raise OllamaError(f"Ollama isn't reachable at {OLLAMA_URL}: {getattr(e, 'reason', e)}") from e


def ollama_version() -> str | None:
    try:
        with _ollama("GET", "/api/version", timeout=3) as response:
            return json.loads(response.read()).get("version")
    except (OllamaError, ValueError):
        return None


def ollama_executable() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    candidates = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
                  Path("/Applications/Ollama.app/Contents/Resources/ollama"), Path("/usr/local/bin/ollama")]
    return next((str(p) for p in candidates if p.is_file()), None)


def start_ollama(wait_s: float = 20) -> bool:
    """Start `ollama serve` if Ollama is installed but not running. Returns True once it answers."""
    if ollama_version():
        return True
    exe = ollama_executable()
    if not exe:
        return False
    flags = _NO_WINDOW | (subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0)
    subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, creationflags=flags, start_new_session=sys.platform != "win32")
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if ollama_version():
            return True
        time.sleep(0.5)
    return False


def installed_models() -> set[str]:
    with _ollama("GET", "/api/tags") as response:
        return {m.get("name", "") for m in json.loads(response.read()).get("models", [])}


def pull(tag: str, progress: Callable[[float, str], None]) -> None:
    """Download a model, reporting (fraction done, status) as it goes."""
    with _ollama("POST", "/api/pull", {"model": tag, "stream": True}, timeout=600) as response:
        for line in response:
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("error"):
                raise OllamaError(event["error"])
            total, done = event.get("total"), event.get("completed")
            progress(done / total if total and done else 0.0, str(event.get("status", "")))


def served_name(plan: Plan) -> str:
    return f"nanoaurora-{plan.model.tag.replace(':', '-')}-{plan.context // 1024}k"


def create_served_model(plan: Plan) -> str:
    """A copy of the model with its context size fixed, since Ollama otherwise defaults to a small one."""
    name = served_name(plan)
    try:
        with _ollama("POST", "/api/create", {"model": name, "from": plan.model.tag,
                                             "parameters": {"num_ctx": plan.context}, "stream": False}, timeout=300):
            pass
    except OllamaError:  # older Ollama releases take a Modelfile instead
        modelfile = f"FROM {plan.model.tag}\nPARAMETER num_ctx {plan.context}\n"
        with _ollama("POST", "/api/create", {"model": name, "modelfile": modelfile, "stream": False}, timeout=300):
            pass
    return name


def benchmark(name: str) -> tuple[float, float]:
    """Returns (prompt tokens/s, generated tokens/s) for a realistic agent-sized prompt."""
    prompt = ("NanoAurora benchmark. " + "The agent reads a long system prompt with tools and notes. " * 120
              + "\nReply with one short sentence.")
    with _ollama("POST", "/api/generate", {"model": name, "prompt": prompt, "stream": False, "think": False,
                                           "options": {"num_predict": 64, "temperature": 0}}, timeout=900) as r:
        stats = json.loads(r.read())
    prompt_tps = stats.get("prompt_eval_count", 0) / max(stats.get("prompt_eval_duration", 0) / 1e9, 1e-6)
    gen_tps = stats.get("eval_count", 0) / max(stats.get("eval_duration", 0) / 1e9, 1e-6)
    return prompt_tps, gen_tps


def remove_model(name: str) -> None:
    try:
        with _ollama("DELETE", "/api/delete", {"model": name}):
            pass
    except OllamaError:
        pass


@dataclass
class Choice:
    plan: Plan
    served: str
    prompt_tps: float
    gen_tps: float


def choose(hw: Hardware, report: Callable[[str, float | None], None]) -> Choice:
    """Download, size, and test models from the most capable down until one is fast enough.

    Models this downloads and rejects are deleted again; models that were already on the
    device are left alone.
    """
    options = plans(hw)
    if not options:
        raise OllamaError("No model fits this device's free memory and disk space.")
    already = installed_models()
    for plan in options:
        tag = plan.model.tag
        if tag not in already:
            report(f"Downloading {tag} ({plan.model.download_gb:.1f} GB)", 0.0)
            pull(tag, lambda fraction, status, tag=tag: report(f"Downloading {tag}: {status}", fraction))
        report(f"Testing {tag} with a {plan.context // 1024}K context", None)
        served = create_served_model(plan)
        prompt_tps, gen_tps = benchmark(served)
        report(f"{tag}: reads {prompt_tps:.0f} and writes {gen_tps:.1f} tokens/s", None)
        if gen_tps >= MIN_GEN_TPS and prompt_tps >= MIN_PROMPT_TPS:
            return Choice(plan, served, prompt_tps, gen_tps)
        remove_model(served)
        if tag not in already:
            remove_model(tag)
    raise OllamaError("None of the models that fit this device ran fast enough to be useful.")


# -- Serving the agent -----------------------------------------------------------


def device_name() -> str:
    name = re.sub(r"[^a-z0-9-]+", "-", socket.gethostname().lower()).strip("-")
    return (name or "device")[:24].strip("-")


def local_address_towards(host: str, port: int) -> str:
    """This device's address on the network that reaches `host`."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe_socket:
        probe_socket.connect((host, port))
        return probe_socket.getsockname()[0]


class Relay:
    """Forwards the agent's OpenAI-style requests to the local Ollama.

    Requests need `Authorization: Bearer <token>` and may only use the chat API paths.
    """

    ALLOWED = ("/v1/chat/completions", "/v1/completions", "/v1/models", "/v1/embeddings")
    HOP_BY_HOP = {"authorization", "connection", "host", "keep-alive", "proxy-connection",
                  "transfer-encoding", "upgrade", "content-length", "te", "trailer"}
    MAX_BODY = 32 * 1024 * 1024

    def __init__(self, token: str, port: int = RELAY_PORT, host: str = "0.0.0.0", upstream: str = OLLAMA_URL):
        self.token = token
        self.port = port
        self.host = host
        parts = urllib.request.urlparse(upstream)
        self.upstream = (parts.hostname or "127.0.0.1", parts.port or 11434)
        self.requests = 0
        self.rejected = 0
        self._server: asyncio.base_events.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, host=self.host, port=self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    @property
    def running(self) -> bool:
        return self._server is not None

    async def _respond(self, writer: asyncio.StreamWriter, status: str, message: str) -> None:
        body = json.dumps({"error": message}).encode()
        writer.write(f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n"
                     f"Connection: close\r\n\r\n".encode() + body)
        await writer.drain()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 30)
            request_line, *lines = head.decode("latin-1").split("\r\n")
            method, target, _version = request_line.split(" ", 2)
            headers = [(k.strip(), v.strip()) for k, _, v in (line.partition(":") for line in lines if ":" in line)]
            lookup = {k.lower(): v for k, v in headers}
            if lookup.get("authorization", "") != f"Bearer {self.token}":
                self.rejected += 1
                await self._respond(writer, "401 Unauthorized", "missing or wrong device token")
                return
            if target.split("?", 1)[0] not in self.ALLOWED:
                self.rejected += 1
                await self._respond(writer, "403 Forbidden", "only the chat API is shared")
                return
            if "chunked" in lookup.get("transfer-encoding", "").lower():
                await self._respond(writer, "411 Length Required", "send Content-Length")
                return
            length = int(lookup.get("content-length") or 0)
            if length > self.MAX_BODY:
                await self._respond(writer, "413 Payload Too Large", "request too large")
                return
            body = await reader.readexactly(length) if length else b""
            self.requests += 1
            up_reader, up_writer = await asyncio.open_connection(*self.upstream)
            forwarded = "".join(f"{k}: {v}\r\n" for k, v in headers if k.lower() not in self.HOP_BY_HOP)
            up_writer.write(f"{method} {target} HTTP/1.1\r\nHost: {self.upstream[0]}:{self.upstream[1]}\r\n"
                            f"{forwarded}Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("latin-1")
                            + body)
            await up_writer.drain()
            try:
                while chunk := await up_reader.read(65536):
                    writer.write(chunk)
                    await writer.drain()
            finally:
                up_writer.close()
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ValueError):
            pass
        except OSError:
            try:
                await self._respond(writer, "502 Bad Gateway", "Ollama isn't answering on this device")
            except OSError:
                pass
        finally:
            try:
                writer.close()
            except OSError:
                pass


def host_command(name: str, address: str, token: str, served: str, port: int = RELAY_PORT) -> str:
    """What to run on the NanoAurora machine to let the agent use this device."""
    return f"nanoaurora compute add {name} http://{address}:{port}/v1 {token} {served}"
