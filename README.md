<p align="center">
  <img src="branding/banner.jpg" alt="NanoBorealis: the agentic Linux desktop. Free AI, on your own hardware." width="100%">
</p>

<p align="center">
  <a href="https://github.com/more-than-just-klyrion/nanoborealis/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/more-than-just-klyrion/nanoborealis?label=installer&color=2dd4bf"></a>
  <a href="https://github.com/more-than-just-klyrion/nanoborealis/actions/workflows/build.yml"><img alt="Build" src="https://img.shields.io/github/actions/workflow/status/more-than-just-klyrion/nanoborealis/build.yml?label=build"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/github/license/more-than-just-klyrion/nanoborealis?color=8b5cf6"></a>
</p>

**NanoBorealis** is a Linux desktop with an AI agent built in. The agent writes, runs and fixes code on your computer, and it's free: it runs on free cloud models and on the hardware you already own.

It's built on [Aurora](https://getaurora.dev), a polished KDE Plasma desktop on Fedora Atomic from the [Universal Blue](https://universal-blue.org) family. The agent is [nanobot](https://github.com/HKUDS/nanobot), running in a sandbox it can't escape to your files or your network.

## Why NanoBorealis

|  |  |
|---|---|
| ✦ **An agent, not a chatbot** | It has its own Linux environment with `sudo`, installs its own tools, and builds and tests real projects in a folder you share with it. |
| ✦ **Free to run** | It uses free models through [OpenRouter](https://openrouter.ai), with automatic fallback when one is busy. |
| ✦ **Your hardware, pooled** | Lend a PC's GPU to the agent from the NanoBorealis app. It picks the best model that fits and benchmarks it. Pooling several machines for bigger models is in progress. |
| ✦ **Contained by design** | The agent runs rootless, in its own account, behind a firewall that keeps it off your local network. It has no rights on the operating system. |
| ✦ **Every device, one history** | Chat from the desktop, the WebUI, or the NanoBorealis app on any computer or phone. Your chats live on your machine and show up everywhere. |
| ✦ **Updates you control** | Nothing updates by itself. Builds are tested, then promoted to stable, then installed only when you say so, and the previous version stays one reboot away. |

## Get started

### The easy way: the NanoBorealis app

The [NanoBorealis app](client/) makes the install stick for you: pick a USB stick, paste your OpenRouter key, and it downloads the installer straight onto the stick and checks it. On Windows, download this repository and double-click `client\run-windows.cmd` (it needs [Python 3.10+](https://www.python.org/downloads/)). Then:

1. Boot the new computer from the stick. Its boot menu opens with **F9** on HP, **F12** on Dell and Lenovo, or **Option** on a Mac.
2. Install, and tick **Make this user administrator**.
3. Log in. Setup opens by itself and uses the key from the stick.
4. Open **NanoBorealis** from the app menu, and start a chat.

### The manual way

1. Download the installer from [Releases](../../releases/latest). It comes in parts; the release notes show how to join them and check the hash.
2. Write it to a USB stick with Fedora Media Writer, Rufus or balenaEtcher, and install as above. Setup asks for your OpenRouter key at first login.

**Already on Aurora?** Switch without reinstalling:

```bash
sudo bootc switch ghcr.io/more-than-just-klyrion/nanoborealis:stable
systemctl reboot
```

Use a **dedicated OpenRouter key with a low credit limit**. The agent can read its own key.

## Everyday use

```bash
nanoborealis help           # everything below, and more
nanoborealis update         # see what's new, then install it at the next reboot
nanoborealis rollback       # go back to the previous version
nanoborealis remote on      # use the agent from your other devices
nanoborealis compute list   # devices lending their hardware to the agent
```

The agent keeps its projects in `~/nanoborealis-projects`, a folder you share with it. Details on what it can and can't do, and what the sandbox doesn't protect against, are in the [agent guide](system_files/usr/share/nanoborealis/README.md).

## How it's built

NanoBorealis is a [bootc](https://containers.github.io/bootc/) image: the whole OS is one signed container image, rebuilt from the latest Aurora every day.

- **Every build is checked** before it's published: [`tests/image-checks.sh`](tests/image-checks.sh) runs inside the new image, and the agent and app test suites run against a real nanobot.
- **Testing, then stable.** Builds land on the `testing` channel. A build reaches `stable`, which installed systems and the installer follow, only when it's promoted by hand, after it's been tried.
- **Signed.** Images are signed with [cosign](https://github.com/sigstore/cosign), and [`cosign.pub`](cosign.pub) verifies them.

| Directory | What's inside |
|---|---|
| [`system_files/`](system_files) | Everything NanoBorealis adds to Aurora: the agent kit, the network guard, commands, artwork |
| [`client/`](client) | The NanoBorealis app, for any computer or phone (Python, [Flet](https://flet.dev)) |
| [`branding/`](branding) | The logo, and the scripts that paint the wallpaper and this banner |
| [`tests/`](tests) | Checks that run inside every built image |
| [`.github/workflows/`](.github/workflows) | Builds, tests, promotion, installer ISOs |

## Roadmap

- **Hardware pools.** Several machines serving one large model, with [exo](https://github.com/exo-explore/exo) (in testing).
- **The full NanoBorealis look.** Boot splash, login screen and desktop theme around the new artwork.
- **Guided first run.** A welcome app in place of the setup terminal.

## Credits

NanoBorealis stands on [Aurora](https://getaurora.dev) and [Universal Blue](https://universal-blue.org), [nanobot](https://github.com/HKUDS/nanobot) by HKUDS, [exo](https://github.com/exo-explore/exo), [Ollama](https://ollama.com), [Flet](https://flet.dev) and [OpenRouter](https://openrouter.ai). The wordmark is set in [Inter](https://rsms.me/inter/).

Licensed under [Apache 2.0](LICENSE). The artwork in `branding/` and the wallpapers are [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).

<sub>Formerly known as nanobot OS and NanoAurora. Systems set up under those names move over by themselves.</sub>
