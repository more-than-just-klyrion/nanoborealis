# nanobot OS

Turns a fresh **Aurora** install into an agentic workstation. nanobot runs as a sandboxed background service, its WebUI sits in your app menu, and it's wired to free Nemotron models on OpenRouter.

There's no nanobot-based distro out there, so this is one: stock Aurora plus one install script.

> **Running the nanobot OS system image?** Then this kit is already installed at `/usr/share/nanobot-os`, and the installer opens on its own the first time an administrator logs in. To run it again later: `bash /usr/share/nanobot-os/install.sh`.

## What you get

- **The nanobot 0.3.5 WebUI** at `http://127.0.0.1:8765`, password-protected, listed in the app menu as *nanobot*
- **Free Nemotron models with automatic fallback:** Ultra 550B, then Super 120B, then Lightning 30B
- **Skills:** `code-review`, `planning`, `simplify`
- **`nanobot-os`**, a command for running and maintaining it

## Install

1. Install Aurora and finish its first-boot setup.
2. Create a **dedicated OpenRouter key** at https://openrouter.ai/keys and give it a **low credit limit**. The reason is under [What it does not protect against](#what-it-does-not-protect-against).
3. Copy this `nanobot-os` folder to the machine, then run:

   ```bash
   cd nanobot-os
   bash install.sh
   ```

   It asks for your sudo password and the OpenRouter key. The first run takes a few minutes and downloads about 200 MB.
4. Open **nanobot** from the app menu and sign in with the password the installer printed.
5. Smoke test. Paste this into a new topic:

   ```
   What model are you? Run "git --version" to confirm you have shell access.
   ```

   If it *describes* running the command instead of actually running it, the model isn't making tool calls. Switch to the `super` preset under **Settings → Models**.

## How the agent is contained

| Layer | What it does |
|---|---|
| Dedicated `nanobot-agent` account | Can't log in and owns nothing but the agent. If something escapes the container, it lands in an empty account, not yours |
| Rootless Podman | Root inside the container is an unprivileged user on the host |
| No capabilities, `no-new-privileges` | Every Linux capability is dropped, and nothing inside can gain privileges |
| No host folders mounted | The agent sees only its own volume, never your files |
| SELinux | Enforcing on Aurora, and the volume is labeled for that one container |
| Loopback-only WebUI | Reachable only from this machine, and only with the password |
| Read-only OS | Aurora's system image can't be modified by anything the agent can reach |

## What it does not protect against

- **The agent can read its own OpenRouter key.** nanobot has to hold the key to call the API, and the shell commands the agent runs inherit it. That's why the key must be dedicated and capped. If it leaks, the loss is limited to that cap.
- **It has full network access.** The agent can reach the internet and your LAN. nanobot's web tools block private addresses, but a `curl` from the shell doesn't. Network isolation was left out on purpose for now.
- **Free providers may log prompts.** Anything the agent reads can end up in a provider's logs, so keep personal files and logged-in accounts off this machine.
- **Secrets aren't encrypted at rest.** Podman stores them in a file that only `nanobot-agent` and root can read. That's safer than a config file, but it isn't encryption.
- **None of this has been run on a real Aurora machine yet.** It was written against the nanobot 0.3.5, Podman, and Quadlet documentation. Expect to fix something on the first install. `nanobot-os logs` is the place to start.

## Day to day

| Command | Does |
|---|---|
| `nanobot-os open` | Open the WebUI |
| `nanobot-os status` | Show whether the service is running |
| `nanobot-os logs` | Follow the agent's logs |
| `nanobot-os restart` | Restart with a fresh container |
| `nanobot-os shell` | Open a shell in the agent's container, to see what it sees |
| `nanobot-os password` | Show the WebUI password |
| `nanobot-os set-key` | Swap the OpenRouter key |
| `nanobot-os rebuild [X.Y.Z]` | Rebuild the image with the newest base-image security fixes and an optional new nanobot version |
| `nanobot-os reset` | **Delete** memory, sessions, skills, and settings, then start fresh |
| `nanobot-os uninstall` | Remove everything, including the `nanobot-agent` account |

**The container is disposable.** nanobot's config, memory, skills, sessions, and workspace live on the `nanobot-data` volume and survive restarts and rebuilds. Anything the agent installs elsewhere in the container doesn't survive a rebuild, and may not survive a restart. The agent runs as a regular user, so it can `pip` or `uv` install into its own space but can't `apt install` system packages.

## Changing things

- **Models:** use **Settings → Models** in the WebUI. Changes are saved to the volume.
- **nanobot version:** `nanobot-os rebuild 0.3.6`
- **Use the WebUI from another machine:** in `~nanobot-agent/.config/containers/systemd/nanobot.container`, change `127.0.0.1` in `PublishPort` to this machine's LAN address. Then run `sudo systemctl --user -M nanobot-agent@ daemon-reload` and `nanobot-os restart`. The password still applies.

## Files

| File | Role |
|---|---|
| `install.sh` | One-time setup. Safe to re-run, and keeps the agent's data |
| `nanobot-os` | The management command, installed to `/usr/local/bin` |
| `nanobot.container` | Quadlet unit that runs the container as a systemd service |
| `image/Containerfile` | The agent image: Debian with Python 3.12 and nanobot from PyPI |
| `image/entrypoint.sh` | Seeds the config and skills into the volume on first start |
| `image/seed/` | The starting config (model chain plus WebUI) and the three skills |

Secrets never appear in these files. The config refers to `${OPENROUTER_API_KEY}` and `${NANOBOT_WEBUI_SECRET}`, which nanobot fills in at startup from Podman secrets.
