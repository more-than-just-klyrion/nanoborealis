# NanoAurora agent

This folder is the NanoAurora agent kit. On NanoAurora the setup opens by itself the first time an administrator logs in. To run it again:

```bash
bash /usr/share/nanobot-os/install.sh
```

Re-running is safe: it keeps the agent's OpenRouter key, WebUI password, and memory.

## What it sets up

- **`nanobot-agent`**, an account that can't log in, owns nothing else, and runs the agent
- **The agent:** nanobot 0.3.5 in a rootless Podman container that systemd runs through Quadlet. Its WebUI is at `http://127.0.0.1:8765`, behind a password, and in the app menu as **NanoAurora**
- **Free Nemotron models with automatic fallback:** Ultra 550B, then Super 120B, then Lightning 30B
- **Skills:** `code-review`, `planning`, `simplify`
- **`/srv/nanoaurora/projects`**, shared by you and the agent, with a shortcut at `~/nanoaurora-projects`

## What the agent can and can't do

| It can | It can't |
|---|---|
| Use `sudo` inside its container: install packages, compile, run services | Change the host operating system, or touch your files outside the projects folder |
| Keep tools it installs in its home; keep apt packages by listing them in `~/.config/nanoaurora/apt-packages` | Reach your local network. A root-owned firewall blocks it, though DNS still works |
| Reach the internet: OpenRouter, package mirrors, git hosts | Turn that firewall off, because it has no root on the host |

## How it's contained

| Layer | What it does |
|---|---|
| Dedicated `nanobot-agent` account | Owns nothing but the agent. Anything that escapes the container lands in an empty account, not yours |
| Rootless Podman | Root inside the container is an unprivileged user on the host |
| One shared folder | The only host path the agent sees is the projects folder |
| Network guard | `nanoaurora-firewall.service` loads at boot, before any user services start, and drops the agent's traffic to private, link-local, and CGNAT addresses |
| SELinux | Enforcing, and the projects folder is labeled for container use |
| Loopback-only WebUI | Reachable only from this machine, and only with the password, until you run `nanoaurora remote on` |
| Read-only OS | Aurora's system image can't be modified by anything the agent can reach |

## What it doesn't protect against

- **The agent can read its own OpenRouter key.** nanobot has to hold the key to call the API, and the agent's shell inherits it. Use a dedicated key with a low credit limit.
- **Internet access is unrestricted.** The firewall stops the local network, not the internet.
- **Free providers may log prompts.** Keep personal files and logged-in accounts off this machine.
- **Secrets aren't encrypted at rest.** Podman keeps them in a file only `nanobot-agent` and root can read.
- **Remote access is plain HTTP.** With `nanoaurora remote on`, the WebUI password crosses your network unencrypted. Only turn it on for networks you trust.

## Day to day

| Command | Does |
|---|---|
| `nanoaurora update` | Update NanoAurora and your apps to the newest build (then reboot) |
| `nanoaurora open` | Open the WebUI |
| `nanoaurora status` / `logs` | Show whether the agent is running, or follow its logs |
| `nanoaurora restart` | Restart the agent in a fresh container |
| `nanoaurora shell` | Open a shell inside the agent's container |
| `nanoaurora password` | Show the WebUI password |
| `nanoaurora remote on` / `off` / `status` | Let other devices on your network use the agent through the NanoAurora client or a browser, or go back to this machine only |
| `nanoaurora set-key` | Swap the OpenRouter key |
| `nanoaurora rebuild [X.Y.Z]` | Rebuild the agent's container, optionally at a new nanobot version |
| `nanoaurora reset` | **Delete** the agent's home (memory, sessions, settings, tools) and start fresh. Projects are kept |
| `nanoaurora uninstall` | Remove the agent and its account. Projects are kept |

`nanobot-os` works as a name for the same command.

**The container is disposable; the home is not.** The agent's home directory, including config, memory, sessions, skills, and anything installed there, lives on the `nanobot-home` volume and survives restarts and rebuilds. Packages installed with apt disappear when the container is recreated, unless they're listed in `~/.config/nanoaurora/apt-packages`.

## Changing things

- **Models:** **Settings → Models** in the WebUI. Changes are saved in the agent's home.
- **nanobot version:** `nanoaurora rebuild 0.3.6`
- **Use the agent from another device:** run `nanoaurora remote on`, then connect with the [NanoAurora client](https://github.com/more-than-just-klyrion/nanobot-os/tree/main/client) or a browser at the address it prints. The password still applies. Reinstalling the agent turns remote access back off.
