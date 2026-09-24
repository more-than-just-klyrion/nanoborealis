# NanoBorealis agent

This folder is the NanoBorealis agent kit. On NanoBorealis the setup opens by itself the first time an administrator logs in. To run it again:

```bash
bash /usr/share/nanoborealis/install.sh
```

Re-running is safe: it keeps the agent's OpenRouter key, WebUI password, and memory.

## What it sets up

- **`nanobot-agent`**, an account that can't log in, owns nothing else, and runs the agent
- **The agent:** nanobot 0.3.5 in a rootless Podman container that systemd runs through Quadlet. Its WebUI is at `http://127.0.0.1:8765`, behind a password, and in the app menu as **NanoBorealis**
- **Free Nemotron models with automatic fallback:** Ultra 550B, then Super 120B, then Lightning 30B
- **Skills:** `code-review`, `debugging`, `git-workflow`, `new-project`, `planning`, `simplify`
- **`/srv/nanoborealis/projects`**, shared by you and the agent, with a shortcut at `~/nanoborealis-projects`

## What the agent can and can't do

| It can | It can't |
|---|---|
| Use `sudo` inside its container: install packages, compile, run services | Change the host operating system, or touch your files outside the projects folder |
| Keep tools it installs in its home; keep apt packages by listing them in `~/.config/nanoborealis/apt-packages` | Reach your local network. A root-owned firewall blocks it, though DNS still works |
| Reach the internet: OpenRouter, package mirrors, git hosts | Turn that firewall off, because it has no root on the host |

## How it's contained

| Layer | What it does |
|---|---|
| Dedicated `nanobot-agent` account | Owns nothing but the agent. Anything that escapes the container lands in an empty account, not yours |
| Rootless Podman | Root inside the container is an unprivileged user on the host |
| One shared folder | The only host path the agent sees is the projects folder |
| Network guard | `nanoborealis-firewall.service` loads at boot, before any user services start, and drops the agent's traffic to private, link-local, and CGNAT addresses. The only exceptions are devices you approve with `nanoborealis compute add`, each limited to one address and port, and, on a computer in a pool, this computer's pool relay, which offers chat only |
| SELinux | Enforcing, and the projects folder is labeled for container use |
| Loopback-only WebUI | Reachable only from this machine, and only with the password, until you run `nanoborealis remote on` |
| Read-only OS | Aurora's system image can't be modified by anything the agent can reach |

## What it doesn't protect against

- **The agent can read its own OpenRouter key.** nanobot has to hold the key to call the API, and the agent's shell inherits it. Use a dedicated key with a low credit limit.
- **Internet access is unrestricted.** The firewall stops the local network, not the internet.
- **Free providers may log prompts.** Keep personal files and logged-in accounts off this machine.
- **Secrets aren't encrypted at rest.** Podman keeps them in a file only `nanobot-agent` and root can read.
- **Remote access is plain HTTP.** With `nanoborealis remote on`, the WebUI password crosses your network unencrypted. Only turn it on for networks you trust.
- **A pool trusts its network.** exo has no password, so once a computer joins a pool, anyone on the network can use the pool and pick what it serves, which makes its computers download models. The node runs in its own account and container, away from your files and the agent. Only join on networks you trust, or join with `--private <name>`.

## Day to day

| Command | Does |
|---|---|
| `nanoborealis update` | Check the stable channel for a newer build, show what's new, and download it if you agree, along with app updates. It takes effect at the next reboot. `--testing` follows the testing channel |
| `nanoborealis rollback` | Go back to the build you ran before the last update (then reboot) |
| `nanoborealis version` | Show which build is running, which one is staged, and which channel this system follows |
| `nanoborealis open` | Open the WebUI |
| `nanoborealis status` / `logs` | Show whether the agent is running, or follow its logs |
| `nanoborealis restart` | Restart the agent in a fresh container |
| `nanoborealis shell` | Open a shell inside the agent's container |
| `nanoborealis password` | Show the WebUI password |
| `nanoborealis remote on` / `off` / `status` | Let other devices on your network use the agent through the NanoBorealis client or a browser, or go back to this machine only. While it's on, this machine announces itself over mDNS so clients find it without an address |
| `nanoborealis compute add` / `remove` / `use` / `list` | Run the agent on a model hosted by another device. The NanoBorealis client sets the device up and shows the exact `add` command; `use <name>` makes it the first choice, `use cloud` switches back |
| `nanoborealis pool join` / `serve` / `stop` / `status` / `logs` / `leave` | Pool this computer with others on your network so together they run models too big for any one of them. See [Pooling computers](#pooling-computers) |
| `nanoborealis set-key` | Swap the OpenRouter key |
| `nanoborealis rebuild [X.Y.Z]` | Rebuild the agent's container, optionally at a new nanobot version |
| `nanoborealis reset` | **Delete** the agent's home (memory, sessions, settings, tools) and start fresh. Projects are kept |
| `nanoborealis uninstall` | Remove the agent and its account. Projects are kept |

The earlier names `nanoaurora` and `nanobot-os` still work as well.

**The container is disposable; the home is not.** The agent's home directory, including config, memory, sessions, skills, and anything installed there, lives on the `nanobot-home` volume and survives restarts and rebuilds. Packages installed with apt disappear when the container is recreated, unless they're listed in `~/.config/nanoborealis/apt-packages`.

## Pooling computers

Every computer that runs `nanoborealis pool join` becomes a node of one pool, and their memory adds up: a model too big for any one of them is split into layers across several. The nodes run [exo](https://github.com/exo-explore/exo), pinned to a build that CI first proves by splitting a model across two nodes. Computers without NanoBorealis can join too, by running the same exo version.

```bash
nanoborealis pool join                                      # on every computer that lends its memory
nanoborealis pool serve mlx-community/Qwen3-30B-A3B-4bit    # on the computer with the agent
nanoborealis pool status                                    # the computers, their free memory, what's served
```

`serve` places the model where it fits, waits while each computer downloads its part, then makes it the agent's first choice. The cloud models stay as fallbacks, and `nanoborealis compute use cloud` puts them first again. The agent reaches the pool through a relay on its own computer that needs a token and passes on chat requests only, so it can't make the pool download or delete anything. `leave` takes the computer out and keeps its downloaded models for next time; `leave --delete-models` removes them.

Pools run on the processor today, which is slow for the agent's long prompts. A pool of NVIDIA GPUs needs exo's CUDA build, which comes next. Another engine, such as a fork of exo, builds from [`pool/Containerfile`](https://github.com/more-than-just-kyrion/nanoborealis/blob/main/pool/Containerfile) with `EXO_REPO` and `EXO_REF`.

## Changing things

- **Models:** **Settings → Models** in the WebUI. Changes are saved in the agent's home.
- **nanobot version:** `nanoborealis rebuild 0.3.6`
- **Use the agent from another device:** run `nanoborealis remote on`, then connect with the [NanoBorealis client](https://github.com/more-than-just-kyrion/nanoborealis/tree/main/client) or a browser at the address it prints. The password still applies. Reinstalling the agent turns remote access back off.
