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

## Share a device's hardware with the agent

The agent normally runs on free cloud models. **Share this device's hardware** in the sidebar lets it run on a model hosted by the computer you're using instead. It asks first, on every device, and does nothing until you choose **Allow on this device**.

When you allow it, the client:

1. Checks the device's GPU, video memory, RAM and free disk.
2. Picks the most capable [Qwen3](https://ollama.com/library/qwen3) model that fits. All sizes support the tool calls the agent needs: 30B (a mixture-of-experts model that runs well even from system RAM), 14B, 8B, 4B, 1.7B and 0.6B.
3. Downloads it with [Ollama](https://ollama.com) and fixes its context size, then tests reading and writing speed. If it's too slow to be useful (under 10 tokens/s writing, or 150 reading), it deletes what it downloaded and tries the next size down. Models that were already on the device are never deleted.
4. Serves the model on port 11435 while the client is open. Requests need this device's secret token, and only the chat API is exposed, so the agent can't download, delete, or change models.
5. Shows the command to run once on your NanoAurora machine, for example `nanoaurora compute add my-pc http://192.168.1.20:11435/v1 <token> nanoaurora-qwen3-8b-32k`. That opens the agent's firewall to this one address and port, and adds the device to the agent's models. Then `nanoaurora compute use my-pc` makes it the agent's first choice, with the cloud models as fallbacks for whenever the device is off.

You need Ollama installed; the client links to it if it's missing. **Stop sharing** closes the port and keeps the client from sharing again on its next start. `nanoaurora compute remove my-pc` takes the device off the agent's list.

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

`dev/stub_ollama.py` does the same for compute sharing: it acts like Ollama with configurable model speeds, and `dev/compute_smoke.py` checks model fitting, the choose-and-benchmark loop, the relay's guards, and a full chat turn from nanobot through the relay (see its docstring for the setup).

CI runs both on every change to the client.
