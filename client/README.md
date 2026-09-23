# NanoAurora client

A desktop and mobile app for chatting with your NanoAurora agent from another computer or phone. It speaks the same protocol as the agent's built-in WebUI, so it sees the same chats.

- Chat list with history, and new chats
- Replies stream in as the agent writes them, rendered as Markdown with highlighted code
- The agent's thinking and each tool it runs, collapsed under the reply, with the tool's output one click away
- Stop button for a turn that's going the wrong way
- Reconnects by itself if the network drops
- Adapts to phone screens: the chat list moves into a drawer

## Connect it to your agent

On the NanoAurora machine:

```bash
nanoaurora remote on     # lets devices on your network reach the agent; prints its address
nanoaurora password      # the password to sign in with
```

Then enter that address and password in the client. **Remember on this device** stores both in the app's local storage, unencrypted, so only tick it on your own devices.

The connection is plain HTTP. Anyone watching the network could read the password, so use remote access on networks you trust. `nanoaurora remote off` closes it again.

## Run it

**Windows:** double-click `run-windows.cmd`. You need [Python 3.10 or newer](https://www.python.org/downloads/). The first run sets up a private Python environment and downloads the window runtime, which takes a minute.

**Linux and macOS:** run `./run.sh`. It needs Python 3.10 or newer with the `venv` module.

**Phones:** build an app with Flet. It installs Flutter the first time, so this takes a while:

```bash
pip install "flet[all]==1.0.1"
flet build apk     # Android; `flet build ipa` for iPhone needs a Mac with Xcode
```

**From source:** `pip install "flet[desktop]==1.0.1" websockets`, then `python src/main.py`.

## How it works

`src/agent_link.py` handles the protocol and has no UI code:

1. `GET /webui/bootstrap` with `Authorization: Bearer <password>` returns a one-time WebSocket token and a short-lived API token.
2. The WebSocket carries typed JSON envelopes: `new_chat`, `attach`, and `message` go out, and `delta`, `reasoning_delta`, `message`, `turn_end` and the rest come back.
3. `GET /api/sessions` lists chats, and `GET /api/sessions/<key>/webui-thread` loads one.

`src/main.py` is the Flet interface on top.

## Testing without spending tokens

`dev/stub_llm.py` is a stand-in OpenAI-compatible model that streams canned Markdown, emits reasoning, and calls a tool when your message contains "tool". Point a real nanobot gateway at it, then run the protocol checks:

```bash
pip install nanobot-ai==0.3.5 websockets
python dev/stub_llm.py 18080 &
nanobot gateway --foreground --config dev/gateway-config.json &
python dev/smoke.py http://127.0.0.1:18765 test-password
```

CI runs the same checks on every change to the client.
