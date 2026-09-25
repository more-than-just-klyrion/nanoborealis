"""A terminal on a paired NanoBorealis computer, and one-off commands there.

Both run as the person who approved this device at the computer's screen (see
/usr/libexec/nanoborealis-remote), over TLS pinned to the computer's certificate, with this
device's password. The terminal's traffic travels in frames: a kind byte (d data, r resize
"rows cols", x exit status), a 4-byte length, then the bytes. Nothing here imports Flet.
"""

from __future__ import annotations

import asyncio
import re

from pairing import DEVICE_HEADER, Machine, NotPaired, PairingError, call

# Colors, cursor movement and window titles: the app's console shows plain text.
_ESCAPES = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Za-z0-9]|\x1b[=>78DEHMc]")


def _visible(line: str) -> str:
    """What a terminal line shows: a carriage return goes back to its start, a backspace one left."""
    cells: list[str] = []
    column = 0
    for ch in line:
        if ch == "\r":
            column = 0
        elif ch == "\b":
            column = max(0, column - 1)
        elif ch >= " " or ch == "\t":
            if column < len(cells):
                cells[column] = ch
            else:
                cells.append(ch)
            column += 1
    return "".join(cells)


def plain(text: str) -> str:
    """Terminal output as plain text, for the app's console."""
    return "\n".join(_visible(line) for line in _ESCAPES.sub("", text).replace("\r\n", "\n").split("\n"))


def run_command(machine: Machine, command: str, timeout: int = 120) -> tuple[int | None, str]:
    """Run a command in a login shell there; returns (exit status, None if it timed out, output). Blocks."""
    status, data, _ = call(machine.host, machine.port, "POST", "/nanoborealis/command", context=machine.context(),
                           body={"command": command, "timeout": timeout}, headers={DEVICE_HEADER: machine.password},
                           timeout=timeout + 30)
    if status == 401:
        raise NotPaired("This computer doesn't know this device anymore. Pair it again.")
    if status != 200:
        raise PairingError(data.get("error") or f"The computer answered HTTP {status}.")
    return data.get("exit"), str(data.get("output", ""))


class Terminal:
    """One terminal session. `await open()`, then `send()` keys and read output with `read()`
    (b"" when the shell has ended; `exit_status` then holds its status)."""

    def __init__(self, machine: Machine, rows: int = 24, cols: int = 80, console: bool = False):
        self.machine, self.rows, self.cols, self.console = machine, rows, cols, console
        self.exit_status: int | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def open(self) -> None:
        try:
            self._reader, self._writer = await asyncio.wait_for(asyncio.open_connection(
                self.machine.host, self.machine.port, ssl=self.machine.context(), server_hostname=None), 15)
        except (OSError, asyncio.TimeoutError) as e:
            if "CERTIFICATE_VERIFY_FAILED" in str(e):
                raise NotPaired("The computer at this address isn't the one this app paired with.") from e
            raise PairingError(f"Can't reach {self.machine.name}: {e}") from e
        mode = "&mode=console" if self.console else ""
        self._writer.write(
            f"GET /nanoborealis/terminal?rows={self.rows}&cols={self.cols}{mode} HTTP/1.1\r\n"
            f"Host: {self.machine.host}:{self.machine.port}\r\nUpgrade: nanoborealis-terminal\r\n"
            f"Connection: Upgrade\r\n{DEVICE_HEADER}: {self.machine.password}\r\n\r\n".encode())
        await self._writer.drain()
        head = await asyncio.wait_for(self._reader.readuntil(b"\r\n\r\n"), 20)
        status = head.split(b" ", 2)[1] if head.count(b" ") >= 2 else b""
        if status == b"101":
            return
        body = await self._reader.read(4096)
        self.close()
        if status == b"401":
            raise NotPaired("This computer doesn't know this device anymore. Pair it again.")
        message = re.search(rb'"error":\s*"([^"]*)"', body)
        raise PairingError(message.group(1).decode() if message else f"The computer answered {status.decode()}.")

    async def send(self, data: bytes | str) -> None:
        payload = data.encode() if isinstance(data, str) else data
        if self._writer is not None:
            self._writer.write(b"d" + len(payload).to_bytes(4, "big") + payload)
            await self._writer.drain()

    async def resize(self, rows: int, cols: int) -> None:
        self.rows, self.cols = rows, cols
        if self._writer is not None:
            payload = f"{rows} {cols}".encode()
            self._writer.write(b"r" + len(payload).to_bytes(4, "big") + payload)
            await self._writer.drain()

    async def read(self) -> bytes:
        """The next output, or b"" once the shell has ended or the connection closed."""
        while self._reader is not None:
            try:
                head = await self._reader.readexactly(5)
                payload = await self._reader.readexactly(int.from_bytes(head[1:], "big"))
            except (asyncio.IncompleteReadError, ConnectionError, OSError):
                return b""
            if head[:1] == b"d":
                return payload
            if head[:1] == b"x":
                try:
                    self.exit_status = int(payload.decode() or 0)
                except ValueError:
                    self.exit_status = -1
                return b""
        return b""

    def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None
