# NanoBorealis client

The NanoBorealis app, for desktop and mobile. Use it to chat with your agent from any computer or phone, lend a device's hardware to the agent, and make install sticks for new computers.

Your chats live on the NanoBorealis machine, so they carry over everywhere. A chat started in the WebUI on the laptop, in this app on your PC, or on your phone shows up in all of them. The chat list refreshes by itself, and a chat open on two devices updates on both as the agent replies.

- Finds NanoBorealis machines on your network by itself
- Chat list with history, and new chats
- Replies stream in as the agent writes them, rendered as Markdown with highlighted code
- The agent's thinking and each tool it runs, collapsed under the reply, with the tool's output one click away
- Stop button for a turn that's going the wrong way
- Reconnects by itself if the network drops
- Adapts to phone screens: the chat list moves into a drawer

## Connect it to your agent

On the NanoBorealis machine:

```bash
nanoborealis remote on     # lets devices on your network reach the agent; prints its address
nanoborealis password      # the password to sign in with
```

The client lists NanoBorealis machines it finds on your network (they announce themselves over mDNS, like printers), so usually you just pick yours and enter the password. You can also type the address `remote on` printed.  **Remember on this device** stores both in the app's local storage, unencrypted, so only tick it on your own devices.

The connection is plain HTTP. Anyone watching the network could read the password, so use remote access on networks you trust. `nanoborealis remote off` closes it again.

## Make an install stick

**Make an install stick** (on the sign-in screen and in the sidebar) turns a USB stick into a NanoBorealis installer:

1. Pick the stick. Only USB drives of 8 to 512 GB are offered, never the system disk or a large external drive.
2. Optionally paste your OpenRouter API key. It goes on the stick, and setup on the new computer uses it instead of asking.
3. Pick the **NanoBorealis build**: **Stable** (tested releases, recommended), **Testing** (candidates for the next stable build) or **Development** (every build). Each build has its own installer, and the new computer keeps following the build you pick. If a build has no installer yet, the stick carries the stable one and the computer moves to your build at first login; the confirm screen says which installer you'll get.
4. Choose the latest release or an ISO you already have. The latest release streams straight onto the stick, with no copy on this computer.

Writing a whole disk needs administrator rights, so your system asks for permission once. The app writes the installer byte for byte, then the key block just past it, and reads everything back to check it. The installer image itself isn't modified, so its checksum and the installer's media check still pass. The key sits on the stick unencrypted, so treat the stick like a password.

## Share a device's hardware with the agent

The agent normally runs on free cloud models. **Share this device's hardware** in the sidebar lets it run on a model hosted by the computer you're using instead. It asks first, on every device, and does nothing until you choose **Allow on this device**.

When you allow it, the client:

1. Checks the device's GPU, video memory, RAM and free disk.
2. Picks the most capable [Qwen3](https://ollama.com/library/qwen3) model that fits. All sizes support the tool calls the agent needs: 30B (a mixture-of-experts model that runs well even from system RAM), 14B, 8B, 4B, 1.7B and 0.6B.
3. Downloads it with [Ollama](https://ollama.com) and fixes its context size, then tests reading and writing speed. If it's too slow to be useful (under 10 tokens/s writing, or 150 reading), it deletes what it downloaded and tries the next size down. Models that were already on the device are never deleted.
4. Serves the model on port 11435 while the client is open. Requests need this device's secret token, and only the chat API is exposed, so the agent can't download, delete, or change models.
5. Shows the command to run once on your NanoBorealis machine, for example `nanoborealis compute add my-pc http://192.168.1.20:11435/v1 <token> nanoborealis-qwen3-8b-32k`. That opens the agent's firewall to this one address and port, and adds the device to the agent's models. Then `nanoborealis compute use my-pc` makes it the agent's first choice, with the cloud models as fallbacks for whenever the device is off.

You need Ollama installed; the client links to it if it's missing. **Stop sharing** closes the port and keeps the client from sharing again on its next start. `nanoborealis compute remove my-pc` takes the device off the agent's list.

## Run it

**Install it:** download it from the [latest release](https://github.com/more-than-just-kyrion/nanoborealis/releases/latest). No Python needed.

- **Windows:** run `NanoBorealis-Setup-….exe`. It installs for your user, with Start menu and desktop shortcuts, and uninstalls from Settings → Apps.
- **macOS:** open `NanoBorealis-…-macos.dmg` and drag NanoBorealis to Applications. It isn't notarized yet, so the first time, right-click it and choose **Open**.
- **Linux:** unpack `NanoBorealis-…-linux-x86_64.tar.gz` and run `./install.sh` (`./install.sh --remove` uninstalls).

**Updates:** the app checks for a newer version each time it starts, and offers it; **App updates** in the sidebar checks on demand. Turn on **Install new versions automatically** there to skip the question. It also picks the **update channel**:

| Channel | Versions | What you get |
|---|---|---|
| **Stable** (default) | `0.3.0` | Tested releases |
| **Testing** | `0.3.0-rc.61` | Candidates for the next stable version, plus stable releases |
| **Development** | `0.3.1-dev.72` | A build of every change to the app, plus everything above |

Moving to a steadier channel never downgrades: the app switches over with that channel's next newer release. Either way, a download only installs after it matches the checksums published with the release. On Windows and Linux the app then restarts by itself; on macOS, drag the new app over the old one.

**From source:** on Windows double-click `run-windows.cmd`, on Linux and macOS run `./run.sh`. Both need Python 3.10 or newer, and set up a private environment on first run. Releases are frozen with PyInstaller by [`.github/workflows/client-release.yml`](../.github/workflows/client-release.yml).

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
