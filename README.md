# NanoAurora

A Linux desktop with an AI agent built in. NanoAurora is [Aurora](https://getaurora.dev) (KDE Plasma on Fedora Atomic) plus a sandboxed [nanobot](https://github.com/HKUDS/nanobot) agent that runs on free models through [OpenRouter](https://openrouter.ai), with its WebUI in your app menu.

## Install

1. Download the installer from [Releases](../../releases/latest). It comes in parts; the release notes show how to join them and check the hash.
2. Write it to a USB stick with Fedora Media Writer, Rufus, or balenaEtcher, and boot from it.
3. In the installer, create your account and tick **Make this user administrator**.
4. Log in. The agent setup opens by itself and asks for your password and an OpenRouter API key. Use a **dedicated key with a low credit limit**: the agent can read its own key.
5. Open **NanoAurora** from the app menu.

Already running Aurora? Switch instead of reinstalling:

```bash
sudo bootc switch ghcr.io/more-than-just-klyrion/nanobot-os:latest
systemctl reboot
```

## What the agent can do

- Anything inside its own Debian container. It has `sudo` there, so it installs its own tools and builds and runs code.
- Work in `~/nanoaurora-projects`, a folder it shares with you.
- Reach the internet, but not your local network. A firewall the agent can't change blocks it.

It has no rights on the operating system itself. [`/usr/share/nanobot-os/README.md`](system_files/usr/share/nanobot-os/README.md) has the details, including what the sandbox doesn't protect against.

## Updates

GitHub builds a fresh image every day on top of the latest Aurora, but nothing updates on its own. Run `nanoaurora update` when you want the newest build, then reboot. If a build misbehaves, choose the previous one in the boot menu or run `sudo bootc rollback`.

## Managing the agent

`nanoaurora help` lists everything: update, open, status, logs, restart, shell, password, set-key, rebuild, reset, uninstall.

## Building

Pushing to `main` rebuilds and signs the image; `cosign.pub` verifies it. The **Build disk images** workflow builds the installer ISO and publishes it as a release. The **Test agent container** workflow checks the agent and its network guard on every change.
