"""End-to-end protocol check: drives a real nanobot gateway through agent_link.

Start dev/stub_llm.py and a gateway whose custom provider points at it, then:

    python dev/smoke.py http://127.0.0.1:8765 <webui-password>

Exits non-zero on the first failed check.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_link import AgentLink, AuthError  # noqa: E402


async def main(address: str, password: str) -> None:
    events: asyncio.Queue[dict] = asyncio.Queue()

    async def on_event(event: dict) -> None:
        await events.put(event)

    async def until(name: str, timeout: float = 60) -> list[dict]:
        seen = []
        while True:
            event = await asyncio.wait_for(events.get(), timeout)
            seen.append(event)
            if event["event"] == name:
                return seen

    def check(ok: bool, what: str) -> None:
        print(("ok   " if ok else "FAIL ") + what, flush=True)
        if not ok:
            raise SystemExit(1)

    # A wrong password must fail fast with AuthError, not retry forever.
    bad = AgentLink(address, password + "-wrong", on_event)
    try:
        await asyncio.wait_for(bad.run(), 20)
        check(False, "wrong password is rejected")
    except AuthError:
        check(True, "wrong password is rejected")

    link = AgentLink(address, password, on_event)
    runner = asyncio.create_task(link.run())
    try:
        await until("link_up", 30)
        check(True, "connected")

        chat_id = await link.new_chat()
        check(bool(chat_id), f"new chat {chat_id}")

        await link.send_message(chat_id, "hello from the smoke test")
        seen = await until("turn_end")
        names = [e["event"] for e in seen]
        print("     events:", " ".join(dict.fromkeys(names)))
        streamed = "".join(e.get("text", "") for e in seen if e["event"] == "delta" and e.get("chat_id") == chat_id)
        finals = [e.get("text", "") for e in seen if e["event"] == "message" and not e.get("kind")]
        answer = streamed or " ".join(finals)
        check("Stub reply to" in answer, "streamed a reply")
        check(any(e["event"] == "reasoning_delta" for e in seen), "reasoning arrived")

        await link.send_message(chat_id, "please use a tool")
        seen = await until("turn_end")
        hints = [e for e in seen if e["event"] == "message" and e.get("kind") in ("tool_hint", "progress")]
        print("     tool activity:", [h.get("text", "")[:60] for h in hints])
        check(bool(hints), "tool activity arrived")
        check("The tool finished" in "".join(e.get("text", "") for e in seen if e["event"] in ("delta", "stream_end", "message")),
              "answered after the tool")

        # nanobot answers /stop with a message and sends no turn_end for the cancelled turn.
        await link.send_message(chat_id, "use a tool, then get stopped")
        await asyncio.sleep(1.0)
        await link.stop_turn(chat_id)
        stopped = False
        try:
            while not stopped:
                event = await asyncio.wait_for(events.get(), 20)
                stopped = event["event"] == "message" and str(event.get("text", "")).startswith("Stopped")
        except asyncio.TimeoutError:
            pass
        check(stopped, "stop cancels a running turn")

        chats = await link.list_chats()
        check(any(c["chat_id"] == chat_id for c in chats), f"chat is listed ({len(chats)} chats)")
        row = next(c for c in chats if c["chat_id"] == chat_id)
        print("     chat row keys:", sorted(row))

        thread = await link.load_thread(chat_id)
        print("     thread keys:", sorted(thread))
        check(bool(thread), "thread history loads")

        other_events: list[dict] = []

        async def on_other(event: dict) -> None:
            other_events.append(event)

        second = AgentLink(address, password, on_other)
        second_task = asyncio.create_task(second.run())
        for _ in range(100):
            if second.connected:
                break
            await asyncio.sleep(0.1)
        await second.attach(chat_id)
        check(second.chat_id == chat_id, "a second client can attach to the chat")
        await link.send_message(chat_id, "hello again")
        await until("turn_end")
        await asyncio.sleep(0.5)
        check(any(e["event"] in ("delta", "message", "stream_end") for e in other_events),
              "the second client sees the reply too")
        await second.close()
        second_task.cancel()
    finally:
        await link.close()
        runner.cancel()
    print("all checks passed")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
