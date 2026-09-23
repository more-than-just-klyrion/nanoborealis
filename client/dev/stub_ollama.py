"""A stand-in Ollama for testing compute sharing without downloading real models.

It implements the parts of Ollama's API the client uses (version, tags, pull, create,
generate, delete) plus the OpenAI-compatible chat endpoint, which answers like
stub_llm.py. STUB_SPEEDS sets the benchmark speed per model tag in tokens/s, for
example "qwen3:14b=6,*=40", so tests can make large models too slow.

    python dev/stub_ollama.py [port]        # default 18434
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(__file__))
from stub_llm import Handler as ChatHandler  # noqa: E402

MODELS: set[str] = set(filter(None, os.environ.get("STUB_INSTALLED", "").split(",")))
CREATED: dict[str, str] = {}  # served name -> base tag
LOG: list[str] = []
LOCK = threading.Lock()


def speed_for(tag: str) -> float:
    table = dict(item.split("=", 1) for item in os.environ.get("STUB_SPEEDS", "*=40").split(",") if "=" in item)
    return float(table.get(tag, table.get("*", 40)))


class Handler(ChatHandler):
    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:
        if self.path == "/api/version":
            self._json({"version": "0.0.0-stub"})
        elif self.path == "/api/tags":
            with LOCK:
                names = sorted(MODELS | set(CREATED))
            self._json({"models": [{"name": n, "model": n} for n in names]})
        elif self.path == "/stub/log":
            with LOCK:
                self._json({"log": LOG, "models": sorted(MODELS | set(CREATED))})
        else:
            super().do_GET()

    def do_DELETE(self) -> None:
        name = self._body().get("model", "")
        with LOCK:
            LOG.append(f"delete {name}")
            found = name in MODELS or name in CREATED
            MODELS.discard(name)
            CREATED.pop(name, None)
        self._json({} if found else {"error": "not found"}, 200 if found else 404)

    def do_POST(self) -> None:
        if self.path.startswith("/v1/"):
            super().do_POST()
            return
        body = self._body()
        name = body.get("model", "")
        if self.path == "/api/pull":
            with LOCK:
                LOG.append(f"pull {name}")
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            for done in (0, 50, 100):
                self.wfile.write(json.dumps({"status": "pulling", "total": 100, "completed": done}).encode() + b"\n")
                self.wfile.flush()
                time.sleep(0.05)
            self.wfile.write(b'{"status": "success"}\n')
            with LOCK:
                MODELS.add(name)
        elif self.path == "/api/create":
            base = body.get("from") or body.get("modelfile", "").split("\n", 1)[0].removeprefix("FROM ").strip()
            with LOCK:
                LOG.append(f"create {name} from {base} ctx={body.get('parameters', {}).get('num_ctx')}")
                if base not in MODELS:
                    self._json({"error": f"base model {base} not found"}, 404)
                    return
                CREATED[name] = base
            self._json({"status": "success"})
        elif self.path == "/api/generate":
            with LOCK:
                base = CREATED.get(name, name)
                LOG.append(f"generate {name}")
            tps = speed_for(base)
            self._json({"model": name, "response": "Benchmark done.", "done": True,
                        "prompt_eval_count": 1200, "prompt_eval_duration": int(1200 / (tps * 20) * 1e9),
                        "eval_count": 64, "eval_duration": int(64 / tps * 1e9)})
        else:
            self._json({"error": f"unsupported path {self.path}"}, 404)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18434
    print(f"stub Ollama on http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
