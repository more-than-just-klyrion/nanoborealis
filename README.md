# NanoBorealis

A Linux desktop with an AI agent built in. NanoBorealis builds on [Aurora](https://getaurora.dev) (KDE Plasma on Fedora Atomic) and adds a sandboxed [nanobot](https://github.com/HKUDS/nanobot) agent that runs on free models through [OpenRouter](https://openrouter.ai), or on models hosted by your own devices.

## Install

1. Download the installer from [Releases](../../releases/latest). It comes in parts; the release notes show how to join them and check the hash.
2. Write it to a USB stick with Fedora Media Writer, Rufus, or balenaEtcher, and boot from it.
3. In the installer, create your account and tick **Make this user administrator**.
4. Log in. The agent setup opens by itself and asks for your password and an OpenRouter API key. Use a **dedicated key with a low credit limit**: the agent can read its own key.
5. Open **NanoBorealis** from the app menu.

Already running Aurora? Switch instead of reinstalling:

```bash
sudo bootc switch ghcr.io/more-than-just-klyrion/nanoborealis:stable
systemctl reboot
```

## What the agent can do

- Anything inside its own Debian container. It has `sudo` there, so it installs its own tools and builds and runs code.
- Work in `~/nanoborealis-projects`, a folder it shares with you.
- Reach the internet, but not your local network. A firewall the agent can't change blocks it.

It has no rights on the operating system itself. [`/usr/share/nanoborealis/README.md`](system_files/usr/share/nanoborealis/README.md) has the details, including what the sandbox doesn't protect against.

## Updates

Nothing updates on its own. NanoBorealis follows Aurora, and every upstream change can break the NanoBorealis layer, so a new build goes through three gates before it reaches your computer:

1. **Build checks.** Every build, daily and on every change, runs [`tests/image-checks.sh`](tests/image-checks.sh) inside the new image, plus the agent and client test suites. A build that fails never gets published.
2. **Testing channel.** Builds that pass go to `nanoborealis:testing`. Try them on a spare machine with `nanoborealis update --testing`.
3. **Stable channel.** A build reaches `nanoborealis:stable`, which installed systems and the installer follow, only when someone runs the **Promote a build to stable** workflow. That re-checks the exact build and confirms its tests passed first.

On your computer, `nanoborealis update` shows what's new and asks before downloading anything. The update takes effect at the next reboot, and the build you were running stays in the boot menu. If something misbehaves, pick it there or run `nanoborealis rollback`.

## Managing the agent

`nanoborealis help` lists everything: update, rollback, version, open, status, logs, restart, shell, password, remote, compute, set-key, rebuild, reset, uninstall. The earlier names `nanoaurora` and `nanobot-os` still work.

## Using it from other devices

The [NanoBorealis client](client/) is a desktop and mobile app for chatting with the agent from another computer or phone. On the NanoBorealis machine, run `nanoborealis remote on` once, then connect the client to the address it prints, using the password from `nanoborealis password`. The client can also share its device's hardware with the agent.

## Building

Pushing to `main` builds, checks, signs and publishes to the testing channel; `cosign.pub` verifies the signatures. **Promote a build to stable** moves a tested build to stable. **Build disk images** builds the installer ISO from stable and publishes it as a release. **Test agent container** and **Test client** cover the agent, its network guard, and the client on every change.

This project was called nanobot OS and then NanoAurora. Systems set up under those names move to the new ones by themselves: `nanoborealis-migrate` runs at boot, and `nanoborealis update` moves them to the new image name.
