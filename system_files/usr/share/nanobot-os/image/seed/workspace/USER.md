# About this setup

- I run you on **NanoAurora**, a dedicated laptop (Aurora Linux with KDE) that exists for you to work on. Nothing personal lives on it.
- You run inside your own Debian container as the user `nanobot`, with **passwordless `sudo` inside that container**. Install whatever you need with `sudo apt-get install`.
- The container is recreated on restarts and updates, so packages installed with apt disappear then. To keep one, add its name on its own line to `~/.config/nanoaurora/apt-packages`; everything listed there is reinstalled on every start. Tools you install into your home directory (`uv tool install`, `pip install --user`, npm with a home prefix, `cargo install`) persist on their own.
- Your home directory persists. **Put projects in `~/projects/`**. That folder is shared with me on the desktop, so I can open and run what you build.
- You can reach the internet, but **not the local network**: a firewall on the laptop blocks it. Don't try to reach other machines on the LAN.
- You have no rights on the laptop's operating system itself, only root inside your container.
