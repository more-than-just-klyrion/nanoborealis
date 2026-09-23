# nanobot OS

[Aurora](https://getaurora.dev) with a sandboxed [nanobot](https://github.com/HKUDS/nanobot) AI agent built in. Built from [ublue-os/image-template](https://github.com/ublue-os/image-template).

## Switch to it

From an installed Aurora, after its first-boot setup:

```bash
sudo bootc switch ghcr.io/more-than-just-klyrion/nanobot-os:latest
systemctl reboot
```

Log in and the nanobot OS installer opens in a terminal. It asks for your password and a **dedicated OpenRouter API key with a low credit limit**, then adds **nanobot** to the app menu.

## What's in the image

- Everything in Aurora
- `/usr/share/nanobot-os`: the installer, the agent's container definition, its config, and skills. Its README covers how the agent is contained and what that doesn't protect against
- the `nanobot-os` management command
- a login launcher that opens the installer once, for administrators only

## Updates and trust

GitHub Actions rebuilds this image every day on top of the latest Aurora stable, and Aurora installs updates automatically. **Every machine running this image installs whatever this repository publishes.** Keep 2FA on the account, and never share its tokens.
