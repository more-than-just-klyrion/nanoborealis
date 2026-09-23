"""Talks to a NanoAurora agent over the nanobot gateway's WebUI protocol.

Same flow as nanobot's own WebUI: GET /webui/bootstrap with the WebUI password returns a
one-time WebSocket token and a short-lived REST token, then typed JSON envelopes travel
over the WebSocket in both directions. Nothing here imports Flet, so the protocol can be
exercised on its own (see dev/smoke.py).
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import websockets

DEFAULT_PORT = 8765
SESSION_KEY_PREFIX = "websocket:"  # nanobot stores WebUI chats as "websocket:<chat_id>"

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class AuthError(Exception):
    """The agent rejected the password."""


class LinkError(Exception):
    """The agent could not be reached, or answered with something unexpected."""


def normalize_address(raw: str) -> str:
    """'192.168.1.20' -> 'http://192.168.1.20:8765'. Full URLs are kept as given."""
    text = raw.strip().rstrip("/")
    if not text:
        raise ValueError("Enter the agent's address.")
    if "://" not in text:
        parts = urllib.parse.urlsplit(f"http://{text}")
        netloc = parts.netloc if parts.port else f"{parts.netloc}:{DEFAULT_PORT}"
        text = f"http://{netloc}{parts.path}"
    parts = urllib.parse.urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Use an address like 192.168.1.20 or http://host:8765.")
    return text


def _with_query(url: str, **params: str) -> str:
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query) + list(params.items())
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def _get_json(url: str, bearer: str, timeout: float = 15) -> Any:
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise AuthError("The agent rejected that password.") from e
        raise LinkError(f"The agent answered HTTP {e.code} for {urllib.parse.urlsplit(url).path}.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise LinkError(f"Cannot reach the agent: {reason}") from e
    except json.JSONDecodeError as e:
        raise LinkError("The agent's answer was not JSON. Is this a NanoAurora address?") from e


@dataclass(frozen=True)
class Bootstrap:
    ws_token: str
    ws_url: str
    api_token: str | None
    expires_in: float
    model_name: str | None


class AgentLink:
    """One client connection to the agent. Call run() in a task; it reconnects by itself."""

    def __init__(self, address: str, password: str, on_event: EventHandler, *, client_id: str | None = None):
        self.base_url = normalize_address(address)
        self._password = password
        self._on_event = on_event
        self.client_id = client_id or f"nanoaurora-client-{uuid.uuid4().hex[:12]}"
        self.model_name: str | None = None
        # The chat the UI is showing; re-attached after every reconnect so replies keep arriving.
        self.chat_id: str | None = None
        self._ws: Any = None
        self._stopped = False
        self._api_token: str | None = None
        self._api_token_expiry = 0.0
        self._new_chat_waiters: list[asyncio.Future[str]] = []
        self._attach_waiters: dict[str, asyncio.Future[str]] = {}

    @property
    def connected(self) -> bool:
        return self._ws is not None

    # -- HTTP ----------------------------------------------------------------

    async def bootstrap(self) -> Bootstrap:
        data = await asyncio.to_thread(_get_json, f"{self.base_url}/webui/bootstrap", self._password)
        token = data.get("token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token:
            raise LinkError("The agent did not issue a connection token.")
        ws_url = data.get("ws_url")
        if not isinstance(ws_url, str) or not ws_url.startswith(("ws://", "wss://")):
            parts = urllib.parse.urlsplit(self.base_url)
            scheme = "wss" if parts.scheme == "https" else "ws"
            ws_url = f"{scheme}://{parts.netloc}{data.get('ws_path') or '/'}"
        expires_in = float(data.get("expires_in") or 300)
        api_token = data.get("api_token") if isinstance(data.get("api_token"), str) else None
        if api_token:
            self._api_token = api_token
            self._api_token_expiry = time.monotonic() + expires_in - 30
        model_name = data.get("model_name") if isinstance(data.get("model_name"), str) else None
        return Bootstrap(token, ws_url, api_token, expires_in, model_name)

    async def _api_get(self, path: str) -> Any:
        if not self._api_token or time.monotonic() > self._api_token_expiry:
            await self.bootstrap()
        if not self._api_token:
            raise LinkError("The agent did not issue an API token.")
        return await asyncio.to_thread(_get_json, f"{self.base_url}{path}", self._api_token)

    async def list_chats(self) -> list[dict[str, Any]]:
        """Saved WebUI chats, newest first. Each row carries 'chat_id' plus nanobot's fields."""
        data = await self._api_get("/api/sessions")
        rows = data.get("sessions", []) if isinstance(data, dict) else []
        chats = []
        for row in rows:
            key = row.get("key") if isinstance(row, dict) else None
            if isinstance(key, str) and key.startswith(SESSION_KEY_PREFIX):
                chats.append({**row, "chat_id": key[len(SESSION_KEY_PREFIX):]})
        return chats

    async def load_thread(self, chat_id: str, limit: int = 200) -> dict[str, Any]:
        key = urllib.parse.quote(f"{SESSION_KEY_PREFIX}{chat_id}", safe="")
        data = await self._api_get(f"/api/sessions/{key}/webui-thread?limit={limit}")
        return data if isinstance(data, dict) else {}

    # -- WebSocket -----------------------------------------------------------

    async def run(self) -> None:
        """Stay connected until close(). Raises AuthError at once; other failures are retried."""
        delay = 1.0
        while not self._stopped:
            detail = ""
            try:
                boot = await self.bootstrap()
                self.model_name = boot.model_name or self.model_name
                url = _with_query(boot.ws_url, client_id=self.client_id, token=boot.ws_token)
                async with websockets.connect(url, max_size=32 * 1024 * 1024, open_timeout=15) as ws:
                    self._ws = ws
                    delay = 1.0
                    await self._emit({"event": "link_up", "model_name": self.model_name})
                    if self.chat_id:
                        await self._send({"type": "attach", "chat_id": self.chat_id})
                    async for raw in ws:
                        if isinstance(raw, str):
                            await self._dispatch(raw)
                    detail = "The agent closed the connection."
            except AuthError:
                raise
            except (LinkError, OSError, asyncio.TimeoutError, websockets.WebSocketException) as e:
                detail = str(e) or type(e).__name__
            finally:
                self._ws = None
                self._fail_waiters()
            if self._stopped:
                break
            await self._emit({"event": "link_down", "detail": detail, "retry_in": delay})
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)

    async def close(self) -> None:
        self._stopped = True
        ws = self._ws
        if ws is not None:
            await ws.close()

    async def _dispatch(self, raw: str) -> None:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(event, dict) or not isinstance(event.get("event"), str):
            return
        if event["event"] == "attached":
            chat_id = event.get("chat_id")
            waiter = self._attach_waiters.pop(chat_id, None) if isinstance(chat_id, str) else None
            if waiter is None and self._new_chat_waiters:
                waiter = self._new_chat_waiters.pop(0)
            if waiter is not None and not waiter.done():
                waiter.set_result(chat_id)
        elif event["event"] in ("runtime_model_updated", "turn_model_updated"):
            if isinstance(event.get("model_name"), str) and event["event"] == "runtime_model_updated":
                self.model_name = event["model_name"]
        await self._emit(event)

    async def _emit(self, event: dict[str, Any]) -> None:
        try:
            await self._on_event(event)
        except Exception as e:  # a UI bug must not take the connection down
            print(f"nanoaurora-client: event handler failed on {event.get('event')}: {e!r}")

    async def _send(self, envelope: dict[str, Any]) -> None:
        ws = self._ws
        if ws is None:
            raise LinkError("Not connected to the agent.")
        await ws.send(json.dumps(envelope, ensure_ascii=False))

    def _fail_waiters(self) -> None:
        for waiter in [*self._new_chat_waiters, *self._attach_waiters.values()]:
            if not waiter.done():
                waiter.set_exception(LinkError("Connection lost."))
        self._new_chat_waiters.clear()
        self._attach_waiters.clear()

    # -- Commands ------------------------------------------------------------

    async def new_chat(self) -> str:
        """Create a chat on the agent and return its id."""
        waiter: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._new_chat_waiters.append(waiter)
        try:
            await self._send({"type": "new_chat"})
            chat_id = await asyncio.wait_for(waiter, 20)
        finally:
            if waiter in self._new_chat_waiters:
                self._new_chat_waiters.remove(waiter)
        self.chat_id = chat_id
        return chat_id

    async def attach(self, chat_id: str) -> None:
        """Subscribe to an existing chat so its replies (including in-flight ones) arrive here."""
        waiter: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._attach_waiters[chat_id] = waiter
        try:
            await self._send({"type": "attach", "chat_id": chat_id})
            await asyncio.wait_for(waiter, 20)
        finally:
            self._attach_waiters.pop(chat_id, None)
        self.chat_id = chat_id

    async def send_message(self, chat_id: str, text: str) -> None:
        await self._send({"type": "message", "chat_id": chat_id, "content": text})

    async def stop_turn(self, chat_id: str) -> None:
        """Cancel the agent's current turn in this chat (nanobot's /stop command)."""
        await self.send_message(chat_id, "/stop")
