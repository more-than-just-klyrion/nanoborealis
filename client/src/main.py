"""NanoBorealis: chat with your NanoBorealis agent from any device.

    python src/main.py                    # desktop window
    FLET_FORCE_WEB_SERVER=true FLET_SERVER_PORT=8550 python src/main.py   # serve to a browser
    flet build apk                        # Android (also ipa, windows, macos, linux)
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import tempfile
import time
import urllib.parse
import uuid
from datetime import datetime
from typing import Any

import flet as ft

import compute
import discovery
import stickmaker
import updater
from agent_link import AgentLink, AuthError, LinkError
from version import VERSION

NARROW = 760  # below this width the chat list moves into a drawer
READABLE = 860  # widest the conversation column gets
SEED = ft.Colors.TEAL
# Bundled in assets/fonts (SIL OFL): Flutter doesn't resolve a generic "monospace" family, so
# code and tool output would otherwise come out in the proportional UI font.
MONO = "JetBrains Mono"
PREF_ADDRESS = "nanoborealis.address"
PREF_PASSWORD = "nanoborealis.password"
PREF_CLIENT_ID = "nanoborealis.client_id"
PREF_COMPUTE = "nanoborealis.compute"  # JSON: consent, token, served model, speeds
PREF_AUTO_UPDATE = "nanoborealis.auto_update"  # "1": install new app versions without asking
PREF_UPDATE_CHANNEL = "nanoborealis.update_channel"  # stable, testing or dev
# The NanoBorealis build an install stick sets up: the same three tiers as the OS images.
STICK_BUILDS = [
    ("stable", "Stable: tested releases (recommended)"),
    ("testing", "Testing: candidates for the next stable build"),
    ("dev", "Development: every build, newest and least tested"),
]
CHANNEL_NAMES = {
    "stable": ("Stable", "Tested releases. Recommended."),
    "testing": ("Testing", "Candidates for the next stable version, a few days early."),
    "dev": ("Development", "Built from every change. Newest features, occasionally broken."),
}
SUGGESTIONS = [
    ("Plan a project", "Help me plan a small Python project. Ask me what it should do first."),
    ("Look at my projects", "Look through ~/projects and tell me what is there."),
    ("What can you do?", "What can you do on this machine, and what can't you do?"),
]


ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def logo(size: float) -> ft.Control:
    """The NanoBorealis star on its night-sky tile (rendered by branding/make-icons.py)."""
    return ft.Image(src="icon.png", width=size, height=size, fit=ft.BoxFit.CONTAIN)


def short_time(value: Any) -> str:
    """'2026-09-23T08:40:20.744108' -> '08:40' for today, 'Sep 21' for older."""
    if not isinstance(value, str) or not value:
        return ""
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone().replace(tzinfo=None)
    if stamp.date() == datetime.now().date():
        return stamp.strftime("%H:%M")
    return f"{stamp.strftime('%b')} {stamp.day}"


def tool_title(hint: str, event: dict[str, Any] | None) -> str:
    if hint.strip():
        return hint.strip().splitlines()[0]
    if not event:
        return "tool"
    args = event.get("arguments")
    name = event.get("name") or "tool"
    if isinstance(args, dict):
        # The same short forms nanobot uses for live progress, so a chat reads the same reopened.
        for tool, keys, template in HINTS:
            value = next((args[k] for k in keys if isinstance(args.get(k), str) and args[k]), None)
            if name == tool and value is not None:
                title = template.format(value.splitlines()[0] if value else value)
                return title if len(title) <= 140 else title[:137] + "..."
        inner = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items())
    else:
        inner = "" if args is None else str(args)
    title = f"{name}({inner})"
    return title if len(title) <= 140 else title[:137] + "..."


# nanobot's tool hint formats (nanobot/utils/tool_hints.py): tool, argument keys, template.
HINTS = [
    ("exec", ("command", "cmd"), "$ {}"),
    ("read_file", ("path", "file_path"), "read {}"),
    ("write_file", ("path", "file_path"), "write {}"),
    ("edit_file", ("path", "file_path"), "edit {}"),
    ("edit", ("file_path", "path"), "edit {}"),
    ("list_dir", ("path",), "ls {}"),
    ("grep", ("pattern",), 'grep "{}"'),
    ("find_files", ("query", "glob", "path"), "find {}"),
    ("web_search", ("query",), 'search "{}"'),
    ("web_fetch", ("url",), "fetch {}"),
]


def clip(text: str, limit: int = 4000) -> str:
    return text if len(text) <= limit else f"{text[:limit]}\n... ({len(text) - limit:,} more characters)"


def on(fn, *args):
    """An event handler that runs coroutine function fn(*args)."""

    async def handler(_event=None):
        await fn(*args)

    return handler


class ToolRow:
    """One tool call: a spinner while it runs, then its result tucked into an expander."""

    def __init__(self, title: str):
        self.lead = ft.Container(width=20, height=20, alignment=ft.Alignment.CENTER,
                                 content=ft.ProgressRing(width=14, height=14, stroke_width=2))
        self.result = ft.Text("", size=12, font_family=MONO, selectable=True)
        self.result_box = ft.Container(
            content=self.result, visible=False, padding=10, border_radius=8,
            bgcolor=ft.Colors.SURFACE_CONTAINER, margin=ft.Margin.only(left=12, right=12, bottom=10),
        )
        self.tile = ft.ExpansionTile(
            title=ft.Text(title, size=13, font_family=MONO, color=ft.Colors.ON_SURFACE_VARIANT,
                          max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            leading=self.lead,
            controls=[self.result_box],
            expanded_cross_axis_alignment=ft.CrossAxisAlignment.STRETCH,
            dense=True,
            maintain_state=True,
            tile_padding=ft.Padding.symmetric(horizontal=8),
            shape=ft.RoundedRectangleBorder(radius=12),
            collapsed_shape=ft.RoundedRectangleBorder(radius=12),
        )

    def finish(self, result: str, error: bool = False) -> None:
        self.lead.content = ft.Icon(
            ft.Icons.ERROR_OUTLINE_ROUNDED if error else ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED,
            size=16, color=ft.Colors.ERROR if error else ft.Colors.GREEN_400,
        )
        self.result.value = clip(result) if result else "(no output)"
        self.result_box.visible = True


class NanoBorealisApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.prefs = ft.SharedPreferences()
        self.clipboard = ft.Clipboard()
        self.link: AgentLink | None = None
        self.client_id = ""
        self.address = ""
        self.chat_id: str | None = None
        self.chats: list[dict[str, Any]] = []
        self.busy = False
        self.was_up = False
        self.refresh_pending = False
        self.in_chat_view = False
        # Pieces of the reply that is streaming in right now.
        self.reasoning: tuple[ft.Text, ft.Text, float] | None = None
        self.answers: dict[str, tuple[ft.Markdown, list[str]]] = {}
        self.tools: dict[str, ToolRow] = {}
        self.last_answer = ""
        self.dirty: dict[int, ft.Control] = {}
        self.flush_task: asyncio.Task | None = None
        self.scroll_task: asyncio.Future | None = None
        # Compute sharing: this device hosting a model for the agent, with the owner's consent.
        self.share: dict[str, Any] = {}
        self.relay: compute.Relay | None = None
        self.share_busy = False
        self.url_launcher = ft.UrlLauncher()
        # Install sticks: this app writes them too.
        self.file_picker = ft.FilePicker()
        self.sticks: list[stickmaker.Disk] = []
        self.stick_writing = False

    # -- Startup and connecting ------------------------------------------------

    async def start(self) -> None:
        p = self.page
        p.title = "NanoBorealis"
        p.fonts = {MONO: "fonts/JetBrainsMono.ttf"}
        if p.window is not None and os.path.exists(os.path.join(ASSETS, "icon.ico")):
            p.window.icon = os.path.join(ASSETS, "icon.ico")  # title bar and taskbar on Windows
        p.theme_mode = ft.ThemeMode.SYSTEM
        p.theme = ft.Theme(color_scheme_seed=SEED)
        p.dark_theme = ft.Theme(color_scheme_seed=SEED)
        p.padding = 0
        p.spacing = 0
        p.on_resize = self.on_resize
        # Draw first: services such as SharedPreferences reach the device with the first
        # page update, and calling them before that waits for a listener that isn't there.
        self.show_connect()
        self.address = await self.pref_get(PREF_ADDRESS)
        password = await self.pref_get(PREF_PASSWORD)
        self.client_id = await self.pref_get(PREF_CLIENT_ID)
        if not self.client_id:
            self.client_id = f"nanoborealis-client-{uuid.uuid4().hex[:12]}"
            await self.pref_set(PREF_CLIENT_ID, self.client_id)
        if self.address or password:
            self.address_field.value = self.address
            self.password_field.value = password
            self.page.update()
        self.page.run_task(self.check_for_update)
        if self.address and password:
            await self.connect(self.address, password, remember=True)

    # -- App updates -------------------------------------------------------------

    async def update_channel(self) -> str:
        """The owner's choice, or else the channel this build came from."""
        chosen = await self.pref_get(PREF_UPDATE_CHANNEL)
        return chosen if chosen in updater.CHANNELS else updater.channel_of(VERSION)

    async def check_for_update(self, quiet: bool = True) -> None:
        """Offer a newer app release, or install it straight away when auto-update is on."""
        if not updater.can_update():
            if not quiet:
                self.show_update_dialog(None, "stable", note="This copy runs from source; update it with git pull.")
            return
        channel = await self.update_channel()
        try:
            update = await asyncio.to_thread(updater.check, channel)
        except Exception as e:  # offline, rate-limited: try again next start
            if not quiet:
                self.show_update_dialog(None, channel, note=f"Couldn't check for updates: {e}")
            return
        if update is None:
            if not quiet:
                self.show_update_dialog(None, channel)
            return
        if await self.pref_get(PREF_AUTO_UPDATE) == "1":
            await self.apply_update(update)
        else:
            self.show_update_dialog(update, channel)

    def show_update_dialog(self, update: updater.Update | None, channel: str, note: str = "") -> None:
        async def toggle(e) -> None:
            await self.pref_set(PREF_AUTO_UPDATE, "1" if e.control.value else "0")

        auto = ft.Switch(label="Install new versions automatically", value=False, on_change=toggle)

        async def load_switch() -> None:
            auto.value = await self.pref_get(PREF_AUTO_UPDATE) == "1"
            self.page.update()

        async def switch_channel(e) -> None:
            if e.control.value and e.control.value != channel:
                await self.pref_set(PREF_UPDATE_CHANNEL, e.control.value)
                self.page.pop_dialog()
                await self.check_for_update(quiet=False)  # look again on the new channel

        picker = ft.Dropdown(
            label="Update channel", value=channel, dense=True, on_select=switch_channel,
            options=[ft.DropdownOption(key=key, text=f"{name}: {about}") for key, (name, about) in CHANNEL_NAMES.items()],
        )

        if update is None:
            body = note or f"NanoBorealis {VERSION} is the newest version on the {CHANNEL_NAMES[channel][0]} channel."
            steadiness = {"dev": 0, "testing": 1, "stable": 2}
            if not note and steadiness[updater.channel_of(VERSION)] < steadiness[channel]:
                # e.g. running a dev build with Stable chosen: nothing gets downgraded
                body += " You're running a newer build than it has, so you'll move over with its next release."
            actions = [ft.TextButton("Close", on_click=lambda _: self.page.pop_dialog())]
        else:
            body = f"NanoBorealis {update.version} is available. You have {VERSION}."
            actions = [ft.TextButton("Later", on_click=lambda _: self.page.pop_dialog()),
                       ft.FilledButton("Update", icon=ft.Icons.DOWNLOAD_ROUNDED, on_click=on(self.apply_update, update))]
        controls = [ft.Text(body, size=14)]
        if update is not None and update.notes_url:
            controls.append(ft.TextButton("What's new", icon=ft.Icons.OPEN_IN_NEW_ROUNDED,
                                          on_click=lambda _: self.page.run_task(self.url_launcher.launch_url, update.notes_url)))
        if updater.can_update():
            controls.append(picker)
            controls.append(auto)
            controls.append(ft.Text("Updates come from this project's GitHub releases and are checked against "
                                    "their published checksums before they install.",
                                    size=12, color=ft.Colors.ON_SURFACE_VARIANT))
        self.page.show_dialog(ft.AlertDialog(
            modal=True, scrollable=True,
            title=ft.Text("App updates", size=18, weight=ft.FontWeight.W_600),
            content=ft.Container(ft.Column(controls, tight=True, spacing=10), width=440),
            actions=actions,
        ))
        self.page.run_task(load_switch)

    async def apply_update(self, update: updater.Update) -> None:
        bar = ft.ProgressBar(value=0, width=400)
        status = ft.Text(f"Downloading NanoBorealis {update.version}...", size=13)
        try:
            self.page.pop_dialog()
        except Exception:
            pass
        self.page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text("Updating", size=18, weight=ft.FontWeight.W_600),
            content=ft.Container(ft.Column([status, bar], tight=True, spacing=12), width=440),
        ))
        progress = [0, update.size]

        def report(done: int, total: int) -> None:
            progress[0], progress[1] = done, total or progress[1]

        task = asyncio.ensure_future(asyncio.to_thread(updater.download, update, report))
        while not task.done():
            bar.value = progress[0] / progress[1] if progress[1] else None
            self.page.update()
            await asyncio.sleep(0.4)
        try:
            path = task.result()
        except Exception as e:
            status.value = f"The update didn't install: {e}"
            bar.visible = False
            self.page.update()
            return
        status.value = "Installing. NanoBorealis restarts by itself." if sys.platform != "darwin" \
            else "Drag NanoBorealis to Applications in the window that opens, then reopen it."
        bar.value = None
        self.page.update()
        updater.install(path)
        if sys.platform != "darwin":
            await asyncio.sleep(1.5)
            os._exit(0)  # the installer replaces these files and reopens the app

    async def pref_get(self, key: str) -> str:
        try:
            value = str(await self.prefs.get(key) or "")
            if not value and key.startswith("nanoborealis."):
                # Saved before the rename to NanoBorealis.
                value = str(await self.prefs.get("nanoaurora." + key.split(".", 1)[1]) or "")
            return value
        except Exception as e:  # storage is a convenience; never let it stop the app
            print(f"nanoborealis-client: could not read {key}: {e}")
            return ""

    async def pref_set(self, key: str, value: str | None) -> None:
        try:
            if value is None:
                await self.prefs.remove(key)
            else:
                await self.prefs.set(key, value)
        except Exception as e:
            print(f"nanoborealis-client: could not save {key}: {e}")

    def show_connect(self, address: str = "", password: str = "", error: str = "") -> None:
        self.in_chat_view = False
        self.page.drawer = None
        self.address_field = ft.TextField(
            label="Agent address", hint_text="192.168.1.20 or host:8765", value=address,
            prefix_icon=ft.Icons.LINK_ROUNDED, autofocus=not address, on_submit=self.on_connect_click,
        )
        self.password_field = ft.TextField(
            label="WebUI password", value=password, password=True, can_reveal_password=True,
            prefix_icon=ft.Icons.KEY_ROUNDED, autofocus=bool(address), on_submit=self.on_connect_click,
        )
        self.remember = ft.Checkbox(label="Remember on this device", value=True)
        self.found_status = ft.Text("Looking for NanoBorealis on your network...", size=12,
                                    color=ft.Colors.ON_SURFACE_VARIANT)
        self.found_row = ft.Row(wrap=True, spacing=8, run_spacing=8)
        self.connect_error = ft.Text(error, color=ft.Colors.ERROR, size=13, visible=bool(error))
        self.connect_button = ft.FilledButton("Connect", icon=ft.Icons.ARROW_FORWARD_ROUNDED,
                                              height=44, on_click=self.on_connect_click)
        self.connect_progress = ft.ProgressRing(width=20, height=20, stroke_width=2, visible=False)
        mono = ft.TextStyle(font_family=MONO, weight=ft.FontWeight.W_600)
        help_text = ft.Text(
            size=12, color=ft.Colors.ON_SURFACE_VARIANT,
            spans=[
                ft.TextSpan("On the NanoBorealis machine, "),
                ft.TextSpan("nanoborealis password", style=mono),
                ft.TextSpan(" shows the password and "),
                ft.TextSpan("nanoborealis remote on", style=mono),
                ft.TextSpan(" lets other devices connect."),
            ],
        )
        self.connect_card = ft.Container(
            width=self.card_width(),
            padding=28,
            border_radius=20,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            content=ft.Column(
                tight=True, spacing=16,
                controls=[
                    ft.Row([logo(44), ft.Column([
                        ft.Text("NanoBorealis", size=24, weight=ft.FontWeight.W_600),
                        ft.Text("Connect to your agent", color=ft.Colors.ON_SURFACE_VARIANT),
                    ], spacing=0, tight=True)], spacing=14),
                    self.found_status,
                    self.found_row,
                    self.address_field,
                    self.password_field,
                    self.remember,
                    self.connect_error,
                    ft.Row([self.connect_button, self.connect_progress], spacing=14),
                    help_text,
                    ft.Divider(height=1),
                    ft.TextButton("No NanoBorealis computer yet? Make an install stick",
                                  icon=ft.Icons.USB_ROUNDED, on_click=on(self.open_stick_dialog)),
                ],
            ),
        )
        self.page.controls.clear()
        self.page.add(ft.Container(content=self.connect_card, alignment=ft.Alignment.CENTER, expand=True, padding=16))
        self.page.run_task(self.find_machines, self.found_row)

    async def find_machines(self, row: ft.Row) -> None:
        """List NanoBorealis machines announcing themselves on this network."""
        found = await asyncio.to_thread(discovery.browse, 3.0)
        if self.in_chat_view or row is not self.found_row:
            return  # the sign-in screen was replaced meanwhile
        row.controls = [
            ft.OutlinedButton(f"{f.name} ({f.address})", icon=ft.Icons.COMPUTER_ROUNDED, on_click=on(self.use_found, f))
            for f in found
        ]
        row.controls.append(ft.TextButton("Search again", icon=ft.Icons.REFRESH_ROUNDED,
                                          on_click=on(self.search_again)))
        self.found_status.value = ("Found on your network:" if found else
                                   "No NanoBorealis found on this network. Run nanoborealis remote on there, "
                                   "or type its address.")
        self.page.update()

    async def search_again(self) -> None:
        self.found_status.value = "Looking for NanoBorealis on your network..."
        self.found_row.controls = []
        self.page.update()
        await self.find_machines(self.found_row)

    async def use_found(self, found: discovery.Found) -> None:
        self.address_field.value = f"{found.address}:{found.port}"
        self.page.update()
        await self.password_field.focus()
        self.page.update()

    def card_width(self) -> float:
        return min(440, max(280, (self.page.width or 440) - 32))

    async def on_connect_click(self, _event=None) -> None:
        await self.connect(self.address_field.value or "", self.password_field.value or "",
                           remember=bool(self.remember.value))

    async def connect(self, address: str, password: str, remember: bool) -> None:
        self.connect_button.disabled = True
        self.connect_progress.visible = True
        self.connect_error.visible = False
        self.page.update()
        error = ""
        link = None
        try:
            if not password:
                raise ValueError("Enter the WebUI password.")
            link = AgentLink(address, password, self.on_event, client_id=self.client_id)
            await link.bootstrap()  # fail fast on a wrong address or password
        except (ValueError, AuthError, LinkError) as e:
            error = str(e)
        if error or link is None:
            self.connect_button.disabled = False
            self.connect_progress.visible = False
            self.connect_error.value = error
            self.connect_error.visible = True
            self.page.update()
            return
        self.address = address.strip()
        await self.pref_set(PREF_ADDRESS, self.address)
        await self.pref_set(PREF_PASSWORD, password if remember else None)
        self.link = link
        self.was_up = False
        self.show_chat()
        self.page.run_task(self.keep_linked, link)
        if self.relay is None:
            self.page.run_task(self.resume_sharing_on_start)

    async def keep_linked(self, link: AgentLink) -> None:
        try:
            await link.run()
        except AuthError:
            if self.link is link:
                self.link = None
                await self.pref_set(PREF_PASSWORD, None)
                self.show_connect(self.address, "", "The agent no longer accepts this password. Enter the current one.")

    async def disconnect(self) -> None:
        link, self.link = self.link, None
        if link is not None:
            await link.close()
        self.chat_id = None
        self.show_connect(self.address, await self.pref_get(PREF_PASSWORD))

    # -- Chat screen -----------------------------------------------------------

    def show_chat(self) -> None:
        self.in_chat_view = True
        self.chat_list = ft.ListView(expand=True, spacing=2, padding=ft.Padding.symmetric(horizontal=8))
        self.sidebar = ft.Container(width=280, bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
                                    content=self.sidebar_column(self.chat_list))
        self.side_divider = ft.VerticalDivider(width=1)
        self.drawer = ft.NavigationDrawer(controls=[])
        self.page.drawer = self.drawer

        self.menu_button = ft.IconButton(ft.Icons.MENU_ROUNDED, tooltip="Chats", on_click=self.open_drawer)
        self.title_text = ft.Text("New chat", size=16, weight=ft.FontWeight.W_600, max_lines=1,
                                  overflow=ft.TextOverflow.ELLIPSIS, expand=True)
        self.model_text = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self.model_chip = ft.Container(content=self.model_text, visible=False, border_radius=20,
                                       padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                                       border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT))
        self.status_dot = ft.Container(width=10, height=10, border_radius=5, bgcolor=ft.Colors.AMBER,
                                       tooltip="Connecting")
        header = ft.Container(
            padding=ft.Padding.symmetric(horizontal=12, vertical=6),
            content=ft.Row([self.menu_button, self.title_text, self.model_chip, self.status_dot],
                           spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )
        self.progress = ft.ProgressBar(bar_height=2, visible=False)
        self.banner_text = ft.Text("", size=13, expand=True)
        self.banner = ft.Container(
            visible=False, bgcolor=ft.Colors.ERROR_CONTAINER, padding=ft.Padding.symmetric(horizontal=16, vertical=8),
            content=ft.Row([ft.Icon(ft.Icons.WIFI_OFF_ROUNDED, size=18), self.banner_text], spacing=10),
        )
        self.messages = ft.ListView(expand=True, spacing=12)
        self.welcome = self.welcome_view()
        self.composer = ft.TextField(
            hint_text="Message NanoBorealis", multiline=True, min_lines=1, max_lines=8, shift_enter=True,
            border=ft.NoInputBorder(), expand=True, autofocus=True, text_size=15,
            content_padding=ft.Padding.symmetric(vertical=10), on_submit=self.on_send,
        )
        self.send_button = ft.IconButton(ft.Icons.ARROW_UPWARD_ROUNDED, tooltip="Send (Enter)",
                                         bgcolor=ft.Colors.PRIMARY, icon_color=ft.Colors.ON_PRIMARY,
                                         on_click=self.on_send)
        self.stop_button = ft.IconButton(ft.Icons.STOP_ROUNDED, tooltip="Stop", visible=False,
                                         bgcolor=ft.Colors.ON_SURFACE, icon_color=ft.Colors.SURFACE,
                                         on_click=self.on_stop)
        self.footer = ft.Container(
            padding=ft.Padding.only(left=16, right=16, top=4, bottom=14),
            content=ft.Column(tight=True, spacing=6, controls=[
                ft.Container(
                    border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT), border_radius=26,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_LOW, padding=ft.Padding.only(left=18, right=8, top=4, bottom=4),
                    content=ft.Row([self.composer, self.send_button, self.stop_button], spacing=4,
                                   vertical_alignment=ft.CrossAxisAlignment.END),
                ),
                ft.Text("Enter to send, Shift+Enter for a new line. The agent can make mistakes; check its work.",
                        size=11, color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        )
        main = ft.Column(
            expand=True, spacing=0,
            controls=[header, self.progress, self.banner, ft.Stack([self.messages, self.welcome], expand=True),
                      self.footer],
        )
        self.page.controls.clear()
        self.page.add(ft.Row([self.sidebar, self.side_divider, main], expand=True, spacing=0,
                             vertical_alignment=ft.CrossAxisAlignment.STRETCH))
        self.apply_layout()
        self.render_chat_list()
        self.page.update()

    def sidebar_column(self, chat_list: ft.Control | None) -> ft.Column:
        top = [
            ft.Container(padding=ft.Padding.only(left=16, right=12, top=16, bottom=6),
                         content=ft.Row([logo(28), ft.Text("NanoBorealis", size=17, weight=ft.FontWeight.W_600)],
                                        spacing=10)),
            ft.Container(padding=ft.Padding.symmetric(horizontal=12),
                         content=ft.FilledTonalButton("New chat", icon=ft.Icons.ADD_ROUNDED,
                                                      on_click=on(self.open_chat, None))),
            ft.Container(ft.Text("Recent", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                         padding=ft.Padding.only(left=20, top=10, bottom=2)),
        ]
        sharing = self.relay is not None and self.relay.running
        share = ft.Container(
            padding=ft.Padding.symmetric(horizontal=8),
            content=ft.Container(
                border_radius=10, ink=True, padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                on_click=on(self.open_share_dialog),
                content=ft.Row([
                    ft.Icon(ft.Icons.MEMORY_ROUNDED, size=18,
                            color=ft.Colors.GREEN_400 if sharing else ft.Colors.ON_SURFACE_VARIANT),
                    ft.Column([
                        ft.Text("Sharing this device" if sharing else "Share this device's hardware", size=13),
                        ft.Text(self.share_summary(), size=11, color=ft.Colors.ON_SURFACE_VARIANT,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=0, tight=True, expand=True),
                ], spacing=10),
            ),
        )
        bottom = ft.Container(
            padding=ft.Padding.only(left=16, right=8, top=4, bottom=12),
            content=ft.Row([
                ft.Icon(ft.Icons.LINK_ROUNDED, size=16, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(self.link.base_url if self.link else "", size=12, color=ft.Colors.ON_SURFACE_VARIANT,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                ft.IconButton(ft.Icons.LOGOUT_ROUNDED, icon_size=18, tooltip="Disconnect", on_click=on(self.disconnect)),
            ], spacing=6),
        )
        stick = ft.Container(
            padding=ft.Padding.symmetric(horizontal=8),
            content=ft.Container(
                border_radius=10, ink=True, padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                on_click=on(self.open_stick_dialog),
                content=ft.Row([
                    ft.Icon(ft.Icons.USB_ROUNDED, size=18, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text("Make an install stick", size=13, expand=True),
                ], spacing=10),
            ),
        )
        updates = ft.Container(
            padding=ft.Padding.symmetric(horizontal=8),
            content=ft.Container(
                border_radius=10, ink=True, padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                on_click=lambda _: self.page.run_task(self.check_for_update, False),
                content=ft.Row([
                    ft.Icon(ft.Icons.SYSTEM_UPDATE_ALT_ROUNDED, size=18, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(f"App updates ({VERSION})", size=13, expand=True),
                ], spacing=10),
            ),
        )
        return ft.Column(expand=True, spacing=6,
                         controls=[*top, *([chat_list] if chat_list else []), ft.Divider(height=1), share, stick,
                                   updates, bottom])

    def welcome_view(self) -> ft.Control:
        chips = [
            ft.Container(
                content=ft.Text(label, size=13), padding=ft.Padding.symmetric(horizontal=14, vertical=10),
                border_radius=12, border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT), ink=True,
                on_click=on(self.send_text, prompt),
            )
            for label, prompt in SUGGESTIONS
        ]
        return ft.Container(
            expand=True, alignment=ft.Alignment.CENTER, padding=24,
            content=ft.Column(tight=True, spacing=16, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                logo(56),
                ft.Text("What should we work on?", size=24, weight=ft.FontWeight.W_500, text_align=ft.TextAlign.CENTER),
                ft.Text("Your agent runs on your NanoBorealis machine. It can write, run, and fix code there.",
                        size=14, color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER),
                ft.Row(chips, wrap=True, spacing=8, run_spacing=8, alignment=ft.MainAxisAlignment.CENTER),
            ]),
        )

    async def on_resize(self, event: ft.PageResizeEvent) -> None:
        if self.in_chat_view:
            self.apply_layout()
        elif getattr(self, "connect_card", None) is not None:
            self.connect_card.width = self.card_width()
        self.page.update()

    def apply_layout(self) -> None:
        width = self.page.width or 1100
        narrow = width < NARROW
        self.sidebar.visible = not narrow
        self.side_divider.visible = not narrow
        self.menu_button.visible = narrow
        room = width - (0 if narrow else 281)
        side = max(14, (room - READABLE) / 2)
        self.messages.padding = ft.Padding.only(left=side, right=side, top=12, bottom=12)
        self.footer.padding = ft.Padding.only(left=side, right=side, top=4, bottom=14)

    async def open_drawer(self, _event=None) -> None:
        self.render_chat_list()
        await self.page.show_drawer()

    def chat_row(self, chat: dict[str, Any]) -> ft.Control:
        selected = chat["chat_id"] == self.chat_id
        title = (chat.get("title") or chat.get("preview") or "Untitled chat").strip().splitlines()[0]
        return ft.Container(
            content=ft.Row([
                ft.Text(title, size=14, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                ft.Text(short_time(chat.get("updated_at")), size=11, color=ft.Colors.ON_SURFACE_VARIANT),
            ], spacing=8),
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            border_radius=10,
            bgcolor=ft.Colors.SECONDARY_CONTAINER if selected else None,
            ink=True,
            on_click=on(self.open_chat, chat["chat_id"]),
        )

    def render_chat_list(self) -> None:
        if not self.in_chat_view:
            return
        rows = [self.chat_row(c) for c in self.chats]
        empty = ft.Container(ft.Text("No chats yet", size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                             padding=ft.Padding.only(left=12, top=6))
        self.chat_list.controls = rows or [empty]
        # The drawer already scrolls, so it takes the rows directly rather than a nested list.
        drawer_side = self.sidebar_column(None)
        drawer_side.expand = False
        drawer_side.controls[3:3] = [ft.Container(r, padding=ft.Padding.symmetric(horizontal=8)) for r in rows] or [empty]
        self.drawer.controls = [drawer_side]
        for chat in self.chats:
            if chat["chat_id"] == self.chat_id and (chat.get("title") or chat.get("preview")):
                self.title_text.value = (chat.get("title") or chat.get("preview")).strip().splitlines()[0]

    async def refresh_chats(self) -> None:
        if self.link is None:
            return
        try:
            self.chats = await self.link.list_chats()
        except (LinkError, AuthError):
            return
        self.render_chat_list()
        self.page.update()

    async def refresh_chats_soon(self) -> None:
        if self.refresh_pending:
            return
        self.refresh_pending = True
        await asyncio.sleep(0.8)
        self.refresh_pending = False
        await self.refresh_chats()

    async def open_chat(self, chat_id: str | None) -> None:
        if self.page.width and self.page.width < NARROW:
            await self.page.close_drawer()
        self.chat_id = chat_id
        self.reset_turn()
        self.set_busy(False)
        self.messages.controls.clear()
        self.welcome.visible = chat_id is None
        self.title_text.value = "New chat"
        if chat_id is None:
            if self.link is not None:
                self.link.chat_id = None
            self.render_chat_list()
            self.page.update()
            return
        self.render_chat_list()
        self.page.update()
        if self.link is None:
            return
        thread: dict[str, Any] | None = None
        for attempt in range(3):  # right after the agent restarts, the first try can time out
            try:
                await self.link.attach(chat_id)
                thread = await self.link.load_thread(chat_id)
                break
            except (LinkError, AuthError, asyncio.TimeoutError) as e:
                if attempt == 2 or isinstance(e, AuthError):
                    self.add(self.error_row(f"Could not open this chat: {str(e) or type(e).__name__}"))
                    break
                await asyncio.sleep(2)
        if thread is not None:
            if self.chat_id != chat_id:
                return  # the user moved on while this loaded
            self.render_history(thread.get("messages") or [])
            if thread.get("active_turn_id"):
                self.set_busy(True)
        self.page.update()
        self.scroll_to_end()

    def render_history(self, messages: list[dict[str, Any]]) -> None:
        for m in messages:
            role = m.get("role")
            content = m.get("content")
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            if role == "user":
                self.messages.controls.append(self.user_bubble(text))
            elif role == "assistant":
                if isinstance(m.get("reasoning"), str) and m["reasoning"].strip():
                    tile, _title, _body = self.reasoning_view(m["reasoning"], "Thought process")
                    self.messages.controls.append(tile)
                if text.strip():
                    view, _md = self.answer_view(text)
                    self.messages.controls.append(view)
            elif role == "tool":
                events = [e for e in (m.get("toolEvents") or []) if isinstance(e, dict)]
                edits = [e for e in (m.get("fileEdits") or []) if isinstance(e, dict) and e.get("path")]
                if not events and edits:  # file writes are recorded as edits, not tool events
                    for edit in edits:
                        verb = "write" if edit.get("tool") == "write_file" else "edit"
                        row = ToolRow(f"{verb} {edit['path']}")
                        row.finish(f"{edit.get('status') or 'done'}: {edit['path']}", edit.get("status") == "error")
                        self.messages.controls.append(row.tile)
                    continue
                for event in events or [None]:
                    row = ToolRow(tool_title("" if event else text, event))
                    result = (event or {}).get("error") or (event or {}).get("result") or ""
                    row.finish(result if isinstance(result, str) else json.dumps(result), bool((event or {}).get("error")))
                    self.messages.controls.append(row.tile)

    # -- Message views -----------------------------------------------------------

    def user_bubble(self, text: str) -> ft.Control:
        return ft.Column(horizontal_alignment=ft.CrossAxisAlignment.END, controls=[
            ft.Container(
                content=ft.Text(text, size=15, selectable=True),
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST, border_radius=18,
                padding=ft.Padding.symmetric(horizontal=16, vertical=10), margin=ft.Margin.only(left=56),
            ),
        ])

    def answer_view(self, text: str) -> tuple[ft.Control, ft.Markdown]:
        md = ft.Markdown(text, selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                         code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK, auto_follow_links=True,
                         code_style_sheet=ft.MarkdownStyleSheet(
                             code_text_style=ft.TextStyle(font_family=MONO, size=13, height=1.5),
                             codeblock_padding=ft.Padding.symmetric(horizontal=16, vertical=14),
                             codeblock_decoration=ft.BoxDecoration(border_radius=10)),
                         md_style_sheet=ft.MarkdownStyleSheet(
                             code_text_style=ft.TextStyle(font_family=MONO, size=13)))
        copy = ft.IconButton(ft.Icons.CONTENT_COPY_ROUNDED, icon_size=16, tooltip="Copy",
                             icon_color=ft.Colors.ON_SURFACE_VARIANT, on_click=on(self.copy_markdown, md))
        return ft.Column([md, ft.Row([copy], spacing=0)], spacing=0), md

    def reasoning_view(self, text: str, title: str) -> tuple[ft.Control, ft.Text, ft.Text]:
        title_text = ft.Text(title, size=13, color=ft.Colors.ON_SURFACE_VARIANT)
        body = ft.Text(text, size=13, italic=True, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True)
        tile = ft.ExpansionTile(
            title=title_text,
            leading=ft.Icon(ft.Icons.PSYCHOLOGY_OUTLINED, size=18, color=ft.Colors.ON_SURFACE_VARIANT),
            controls=[ft.Container(body, padding=ft.Padding.only(left=16, right=16, bottom=12))],
            expanded_cross_axis_alignment=ft.CrossAxisAlignment.STRETCH,
            dense=True, maintain_state=True, tile_padding=ft.Padding.symmetric(horizontal=8),
            shape=ft.RoundedRectangleBorder(radius=12), collapsed_shape=ft.RoundedRectangleBorder(radius=12),
        )
        return tile, title_text, body

    def note_row(self, text: str, icon: ft.IconData = ft.Icons.INFO_OUTLINE_ROUNDED) -> ft.Control:
        return ft.Row([ft.Icon(icon, size=16, color=ft.Colors.ON_SURFACE_VARIANT),
                       ft.Text(text, size=13, color=ft.Colors.ON_SURFACE_VARIANT, expand=True, selectable=True)],
                      spacing=8)

    def error_row(self, text: str) -> ft.Control:
        return ft.Container(
            bgcolor=ft.Colors.ERROR_CONTAINER, border_radius=10, padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            content=ft.Row([ft.Icon(ft.Icons.ERROR_OUTLINE_ROUNDED, size=16, color=ft.Colors.ON_ERROR_CONTAINER),
                            ft.Text(text, size=13, color=ft.Colors.ON_ERROR_CONTAINER, expand=True, selectable=True)],
                           spacing=8),
        )

    def add(self, control: ft.Control) -> None:
        self.welcome.visible = False
        self.messages.controls.append(control)
        self.page.update()
        self.scroll_to_end()

    def scroll_to_end(self) -> None:
        """Follow the conversation as it grows (ListView.auto_scroll stops once the list moves)."""
        if self.scroll_task is not None and not self.scroll_task.done():
            return

        async def scroll() -> None:
            await asyncio.sleep(0.05)  # let the new content lay out first
            try:
                await self.messages.scroll_to(offset=-1, duration=200)
            except Exception:
                pass  # the chat view was replaced meanwhile

        self.scroll_task = asyncio.ensure_future(scroll())

    async def copy_markdown(self, md: ft.Markdown) -> None:
        await self.clipboard.set(md.value or "")
        self.page.show_dialog(ft.SnackBar(ft.Text("Copied"), duration=1500))

    # -- Streaming ---------------------------------------------------------------

    def reset_turn(self) -> None:
        self.reasoning = None
        self.answers = {}
        self.tools = {}
        self.last_answer = ""

    def mark_dirty(self, control: ft.Control) -> None:
        self.dirty[id(control)] = control
        if self.flush_task is None or self.flush_task.done():
            self.flush_task = asyncio.ensure_future(self.flush_soon())

    async def flush_soon(self) -> None:
        await asyncio.sleep(0.05)  # batch streamed text into ~20 redraws a second
        controls = list(self.dirty.values())
        self.dirty.clear()
        for control in controls:
            try:
                control.update()
            except Exception:
                pass  # the chat was switched away; nothing to redraw
        if self.busy:
            self.scroll_to_end()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        if not self.in_chat_view:
            return
        self.progress.visible = busy
        self.send_button.visible = not busy
        self.stop_button.visible = busy

    def close_reasoning(self) -> None:
        if self.reasoning is not None:
            title, _body, started = self.reasoning
            title.value = f"Thought for {max(1, round(time.monotonic() - started))}s"
            self.mark_dirty(title)
            self.reasoning = None

    async def on_event(self, event: dict[str, Any]) -> None:
        name = event["event"]
        if not self.in_chat_view:
            return
        if name == "link_up":
            await self.on_link_up()
            return
        if name == "link_down":
            self.status_dot.bgcolor = ft.Colors.AMBER
            self.status_dot.tooltip = "Reconnecting"
            self.banner_text.value = f"Connection lost. Retrying in {event.get('retry_in', 1):.0f}s. {event.get('detail', '')}"
            self.banner.visible = True
            self.page.update()
            return
        if name in ("session_updated", "turn_end"):
            self.page.run_task(self.refresh_chats_soon)
        if name == "runtime_model_updated":
            self.set_model(event.get("model_name"))
            return
        if event.get("chat_id") != self.chat_id or self.chat_id is None:
            return

        if name == "turn_model_updated":
            label = event.get("model_name")
            if event.get("fallback") and label:
                label = f"{label} (fallback)"
            self.set_model(label)
        elif name == "goal_status" and event.get("status") == "running":
            self.set_busy(True)
            self.page.update()
        elif name == "retry_status":
            if event.get("state") not in (None, "cleared"):
                self.add(self.note_row(f"The model had a problem; retrying (attempt {event.get('attempt')}).",
                                       ft.Icons.REFRESH_ROUNDED))
        elif name == "reasoning_delta":
            if self.reasoning is None:
                tile, title, body = self.reasoning_view("", "Thinking...")
                self.reasoning = (title, body, time.monotonic())
                self.add(tile)
            _title, body, _started = self.reasoning
            body.value = (body.value or "") + str(event.get("text") or "")
            self.mark_dirty(body)
        elif name == "reasoning_end":
            self.close_reasoning()
        elif name == "delta":
            self.close_reasoning()
            key = str(event.get("stream_id") or "")
            if key not in self.answers:
                view, md = self.answer_view("")
                self.answers[key] = (md, [])
                self.add(view)
            md, parts = self.answers[key]
            parts.append(str(event.get("text") or ""))
            md.value = "".join(parts)
            self.mark_dirty(md)
        elif name == "stream_end":
            key = str(event.get("stream_id") or "")
            if key in self.answers:
                md, parts = self.answers.pop(key)
                if isinstance(event.get("text"), str):
                    md.value = event["text"]
                self.last_answer = md.value or ""
                self.mark_dirty(md)
        elif name == "message":
            self.close_reasoning()
            self.on_agent_message(event)
        elif name == "user_message":
            self.add(self.user_bubble(str(event.get("text") or "")))
        elif name == "turn_end":
            self.close_reasoning()
            self.set_busy(False)
            latency = event.get("latency_ms")
            if isinstance(latency, (int, float)):
                self.add(ft.Text(f"{latency / 1000:.1f}s", size=11, color=ft.Colors.ON_SURFACE_VARIANT))
            self.reset_turn()
            self.page.update()
        elif name == "error":
            detail = str(event.get("detail") or "error")
            if event.get("reason"):
                detail = f"{detail}: {event['reason']}"
            self.add(self.error_row(detail))
            if detail.startswith(("message_rejected", "access_denied", "missing content", "attachment_rejected")):
                self.set_busy(False)
                self.page.update()

    def on_agent_message(self, event: dict[str, Any]) -> None:
        text = str(event.get("text") or "")
        kind = event.get("kind")
        tool_events = [e for e in (event.get("tool_events") or []) if isinstance(e, dict)]
        if kind in ("tool_hint", "progress") or tool_events:
            for tool_event in tool_events:
                call_id = str(tool_event.get("call_id") or len(self.tools))
                row = self.tools.get(call_id)
                if row is None:
                    row = ToolRow(tool_title(text, tool_event))
                    self.tools[call_id] = row
                    self.add(row.tile)
                if tool_event.get("phase") == "end":
                    result = tool_event.get("error") or tool_event.get("result") or ""
                    row.finish(result if isinstance(result, str) else json.dumps(result), bool(tool_event.get("error")))
                    self.page.update()
            if not tool_events and text.strip():
                self.add(self.note_row(text, ft.Icons.TERMINAL_ROUNDED))
            return
        if not text.strip() or text.strip() == self.last_answer.strip():
            return  # already shown by the stream
        view, _md = self.answer_view(text)
        self.last_answer = text
        self.add(view)

    def set_model(self, name: Any) -> None:
        if isinstance(name, str) and name.strip():
            full = name.strip()
            # "nvidia/nemotron-3-ultra-550b-a55b:free" shows as "nemotron-3-ultra-550b-a55b", which
            # leaves the chat title room on a phone; the tooltip keeps the whole name.
            self.model_text.value = full.rsplit("/", 1)[-1].split(":", 1)[0] or full
            self.model_chip.tooltip = full
            self.model_chip.visible = True
            self.page.update()

    async def on_link_up(self) -> None:
        self.status_dot.bgcolor = ft.Colors.GREEN_400
        self.status_dot.tooltip = f"Connected to {self.link.base_url if self.link else ''}"
        self.banner.visible = False
        if self.link is not None:
            self.set_model(self.link.model_name)
        self.page.update()
        reconnect = self.was_up
        self.was_up = True
        await self.refresh_chats()
        if reconnect and self.chat_id:
            await self.open_chat(self.chat_id)  # catch up on anything missed while offline
        if not reconnect and self.link is not None:
            self.page.run_task(self.keep_chats_fresh, self.link)

    async def keep_chats_fresh(self, link: AgentLink) -> None:
        """Chats live on the NanoBorealis machine; ones started on another device show up here too."""
        while self.link is link and self.in_chat_view:
            await asyncio.sleep(20)
            if self.link is link and link.connected:
                await self.refresh_chats()

    # -- Compute sharing -----------------------------------------------------------

    def share_summary(self) -> str:
        if self.relay is not None and self.relay.running:
            return (f"{self.share.get('tag', '')} · {self.share.get('gen_tps', 0):.0f} tokens/s · "
                    f"{self.relay.requests} requests")
        if self.share.get("consent") and self.share.get("served"):
            return "Paused. Open to resume."
        return "Let the agent use this GPU, CPU and RAM"

    def refresh_sidebar(self) -> None:
        if self.in_chat_view:
            self.sidebar.content = self.sidebar_column(self.chat_list)
            self.render_chat_list()  # rebuilds the drawer's copy too
            self.page.update()

    async def load_share(self) -> None:
        raw = await self.pref_get(PREF_COMPUTE)
        try:
            self.share = json.loads(raw) if raw else {}
        except ValueError:
            self.share = {}

    async def save_share(self) -> None:
        await self.pref_set(PREF_COMPUTE, json.dumps(self.share))

    async def resume_sharing_on_start(self) -> None:
        """Share again after a restart, but only if the owner already allowed it on this device."""
        await self.load_share()
        if self.share.get("consent") and self.share.get("served") and self.share.get("token"):
            if await asyncio.to_thread(compute.start_ollama):
                try:
                    installed = await asyncio.to_thread(compute.installed_models)
                except compute.OllamaError:
                    installed = set()
                if {self.share["served"], f"{self.share['served']}:latest"} & installed:
                    await self.start_relay()
        self.refresh_sidebar()

    async def start_relay(self) -> str | None:
        if self.relay is not None and self.relay.running:
            return None
        relay = compute.Relay(self.share["token"])
        try:
            await relay.start()
        except OSError as e:
            return f"Couldn't open port {compute.RELAY_PORT} on this device: {e}"
        self.relay = relay
        self.refresh_sidebar()
        return None

    def device_address(self) -> str:
        if self.link is not None:
            parts = urllib.parse.urlsplit(self.link.base_url)
            try:
                return compute.local_address_towards(parts.hostname or "", parts.port or 8765)
            except OSError:
                pass
        return "<this-device-address>"

    def set_share_body(self, controls: list[ft.Control], actions: list[ft.Control]) -> None:
        self.share_body.controls = controls
        self.share_actions.controls = actions
        self.page.update()

    @staticmethod
    def bullet(text: str) -> ft.Control:
        return ft.Row([ft.Text("•", size=13), ft.Text(text, size=13, expand=True)],
                      spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)

    @staticmethod
    def working(text: str) -> ft.Control:
        return ft.Row([ft.ProgressRing(width=16, height=16, stroke_width=2), ft.Text(text, size=13)], spacing=10)

    async def open_share_dialog(self) -> None:
        if self.page.width and self.page.width < NARROW:
            await self.page.close_drawer()
        self.share_body = ft.Column(tight=True, spacing=12)
        self.share_actions = ft.Row(spacing=8, wrap=True, alignment=ft.MainAxisAlignment.END)
        self.share_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Share this device's hardware", size=18, weight=ft.FontWeight.W_600),
            scrollable=True,
            content=ft.Container(self.share_body, width=500),
            actions=[self.share_actions],
        )
        self.page.show_dialog(self.share_dialog)
        if self.relay is not None and self.relay.running:
            self.show_share_running()
        elif self.share_busy:
            self.set_share_body([self.working("Setting up a model; this keeps going in the background.")],
                                [ft.TextButton("Hide", on_click=on(self.close_share_dialog))])
        else:
            await self.show_share_consent()

    async def close_share_dialog(self) -> None:
        self.page.pop_dialog()

    async def show_share_consent(self) -> None:
        self.set_share_body([self.working("Checking this device...")], [])
        hw = await asyncio.to_thread(compute.probe)
        options = compute.plans(hw)
        best = options[0] if options else None
        if best:
            place = "its GPU" if best.where == "gpu" else "its CPU and memory"
            first = (f"The first choice here is {best.model.tag}: a {best.model.download_gb:.1f} GB download "
                     f"with a {best.context // 1024}K context, running on {place}.")
        else:
            first = "No model fits right now. Close some apps to free memory or disk, then try again."
        self.set_share_body([
            ft.Text(hw.describe(), size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text("Your agent can run on a model hosted on this device instead of free cloud models.", size=14),
            self.bullet("NanoBorealis picks the most capable model that fits, downloads it with Ollama, and tests "
                        "its speed. Any model it downloads and then rejects is deleted again."),
            self.bullet(first),
            self.bullet(f"While this app is open, it answers the agent on port {compute.RELAY_PORT}: only with "
                        "this device's secret token, and only for chat. Your system may ask to allow network access."),
            self.bullet("You can stop sharing at any time."),
        ], [
            ft.TextButton("Not now", on_click=on(self.close_share_dialog)),
            *([ft.FilledButton("Allow on this device", icon=ft.Icons.MEMORY_ROUNDED,
                               on_click=on(self.allow_share, hw))] if best else []),
        ])

    async def allow_share(self, hw: compute.Hardware) -> None:
        self.share["consent"] = True
        self.share.setdefault("token", secrets.token_urlsafe(24))
        await self.save_share()
        self.set_share_body([self.working("Looking for Ollama...")], [])
        if not await asyncio.to_thread(compute.start_ollama):
            self.set_share_body([
                ft.Text("This needs Ollama, the free app that runs the models. Install it, then press Check again.",
                        size=14),
            ], [
                ft.TextButton("Cancel", on_click=on(self.close_share_dialog)),
                ft.OutlinedButton("Get Ollama", icon=ft.Icons.OPEN_IN_NEW_ROUNDED, on_click=on(self.open_ollama_site)),
                ft.FilledButton("Check again", icon=ft.Icons.REFRESH_ROUNDED, on_click=on(self.allow_share, hw)),
            ])
            return
        await self.choose_model(hw)

    async def open_ollama_site(self) -> None:
        await self.url_launcher.launch_url("https://ollama.com/download")

    async def choose_model(self, hw: compute.Hardware) -> None:
        status = ft.Text("Starting...", size=13)
        bar = ft.ProgressBar(value=None)
        steps = ft.Column(spacing=2, tight=True)
        self.set_share_body([status, bar, steps], [ft.TextButton("Hide", on_click=on(self.close_share_dialog))])
        loop = asyncio.get_running_loop()
        last = {"at": 0.0, "text": ""}

        def report(text: str, fraction: float | None) -> None:  # runs on the worker thread
            now = time.monotonic()
            if text == last["text"] and fraction is not None and now - last["at"] < 0.25:
                return  # download progress arrives many times a second
            last.update(at=now, text=text)

            def apply() -> None:
                status.value = text
                bar.value = fraction
                if fraction is None and not text.startswith("Testing"):
                    steps.controls.append(ft.Text(text, size=12, color=ft.Colors.ON_SURFACE_VARIANT))
                try:
                    self.page.update()
                except Exception:
                    pass

            loop.call_soon_threadsafe(apply)

        self.share_busy = True
        try:
            choice = await asyncio.to_thread(compute.choose, hw, report)
        except (compute.OllamaError, OSError, ValueError) as e:
            self.set_share_body([ft.Text(f"Couldn't set up a model: {e}", size=13, color=ft.Colors.ERROR)],
                                [ft.TextButton("Close", on_click=on(self.close_share_dialog))])
            return
        finally:
            self.share_busy = False
        self.share.update(tag=choice.plan.model.tag, served=choice.served, context=choice.plan.context,
                          gen_tps=round(choice.gen_tps, 1), prompt_tps=round(choice.prompt_tps))
        await self.save_share()
        error = await self.start_relay()
        if error:
            self.set_share_body([ft.Text(error, size=13, color=ft.Colors.ERROR)],
                                [ft.TextButton("Close", on_click=on(self.close_share_dialog))])
            return
        self.show_share_running()

    def show_share_running(self) -> None:
        name = compute.device_name()
        command = compute.host_command(name, self.device_address(), self.share["token"], self.share["served"])
        self.set_share_body([
            ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED, color=ft.Colors.GREEN_400),
                    ft.Text(f"Serving {self.share.get('tag')}: reads {self.share.get('prompt_tps', 0):.0f} and "
                            f"writes {self.share.get('gen_tps', 0):.0f} tokens/s.", size=14, expand=True)],
                   spacing=10),
            ft.Text("To let the agent use it, run this once on your NanoBorealis machine:", size=13),
            ft.Container(ft.Text(command, font_family=MONO, size=12, selectable=True),
                         bgcolor=ft.Colors.SURFACE_CONTAINER, border_radius=8, padding=10),
            ft.Text(f"Then nanoborealis compute use {name} makes it the agent's first choice. The agent falls "
                    "back to its cloud models whenever this device is off.", size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT),
        ], [
            ft.TextButton("Stop sharing", on_click=on(self.stop_sharing)),
            ft.OutlinedButton("Copy command", icon=ft.Icons.CONTENT_COPY_ROUNDED, on_click=on(self.copy_text, command)),
            ft.FilledButton("Done", on_click=on(self.close_share_dialog)),
        ])

    async def stop_sharing(self) -> None:
        if self.relay is not None:
            await self.relay.stop()
            self.relay = None
        self.share["consent"] = False  # don't start again on the next launch
        await self.save_share()
        self.set_share_body([
            ft.Text("This device has stopped sharing. The agent is back on its cloud models.", size=14),
            ft.Text(f"To take it off the agent's list too, run nanoborealis compute remove {compute.device_name()} "
                    "on your NanoBorealis machine.", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
        ], [ft.FilledButton("Done", on_click=on(self.close_share_dialog))])
        self.refresh_sidebar()

    async def copy_text(self, text: str) -> None:
        await self.clipboard.set(text)
        self.page.show_dialog(ft.SnackBar(ft.Text("Copied"), duration=1500))

    # -- Install sticks ------------------------------------------------------------

    async def open_stick_dialog(self) -> None:
        if self.in_chat_view and self.page.width and self.page.width < NARROW:
            await self.page.close_drawer()
        self.stick_body = ft.Column(tight=True, spacing=12)
        self.stick_actions = ft.Row(spacing=8, wrap=True, alignment=ft.MainAxisAlignment.END)
        self.stick_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Make a NanoBorealis install stick", size=18, weight=ft.FontWeight.W_600),
            scrollable=True,
            content=ft.Container(self.stick_body, width=520),
            actions=[self.stick_actions],
        )
        self.page.show_dialog(self.stick_dialog)
        if not self.stick_writing:
            await self.show_stick_form()

    def set_stick_body(self, controls: list[ft.Control], actions: list[ft.Control]) -> None:
        self.stick_body.controls = controls
        self.stick_actions.controls = actions
        self.page.update()

    async def close_stick_dialog(self) -> None:
        self.page.pop_dialog()

    async def show_stick_form(self) -> None:
        self.set_stick_body([self.working("Looking for USB sticks...")], [])
        try:
            self.sticks = await asyncio.to_thread(stickmaker.list_sticks)
        except Exception as e:
            self.sticks = []
            print(f"nanoborealis-client: listing sticks failed: {e}")
        self.stick_choice = ft.Dropdown(
            label="USB stick", expand=True,
            options=[ft.DropdownOption(key=s.id, text=s.label) for s in self.sticks],
            value=self.sticks[0].id if len(self.sticks) == 1 else None,
        )
        self.stick_key = ft.TextField(
            label="OpenRouter API key (optional)", password=True, can_reveal_password=True,
            helper="Saved on the stick so setup doesn't ask for it. Use a dedicated key with a low credit limit.",
            helper_max_lines=2, expand=True,
        )
        self.stick_channel = ft.Dropdown(
            label="NanoBorealis build", value="stable", dense=True, expand=True,
            options=[ft.DropdownOption(key=key, text=text) for key, text in STICK_BUILDS],
        )
        self.stick_iso = ""
        self.stick_iso_text = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self.stick_source = ft.RadioGroup(value="latest", content=ft.Column(tight=True, spacing=0, controls=[
            ft.Radio(value="latest", label="Download the latest NanoBorealis (about 5.3 GB, straight onto the stick)"),
            ft.Radio(value="file", label="Use an installer ISO I already have"),
        ]))
        if self.sticks:
            pick = ft.Row([self.stick_choice, ft.IconButton(ft.Icons.REFRESH_ROUNDED, tooltip="Look again",
                                                            on_click=on(self.show_stick_form))])
        else:
            pick = ft.Row([ft.Icon(ft.Icons.USB_ROUNDED, color=ft.Colors.ON_SURFACE_VARIANT),
                           ft.Text("Plug in a USB stick of 8 GB or more, then look again.", size=13, expand=True),
                           ft.IconButton(ft.Icons.REFRESH_ROUNDED, tooltip="Look again", on_click=on(self.show_stick_form))])
        self.set_stick_body([
            ft.Text("The stick is erased and becomes a NanoBorealis installer. Boot a computer from it to install.",
                    size=13, color=ft.Colors.ON_SURFACE_VARIANT),
            pick,
            ft.Row([self.stick_key]),
            ft.Row([self.stick_channel]),
            ft.Text("Each build has its own installer. If one isn't published yet, the stick carries the stable "
                    "installer and the new computer moves to your build at first login.",
                    size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            self.stick_source,
            ft.Row([ft.OutlinedButton("Choose ISO file", icon=ft.Icons.FOLDER_OPEN_ROUNDED, on_click=on(self.pick_iso)),
                    self.stick_iso_text], spacing=10),
        ], [
            ft.TextButton("Cancel", on_click=on(self.close_stick_dialog)),
            ft.FilledButton("Next", icon=ft.Icons.ARROW_FORWARD_ROUNDED, on_click=on(self.confirm_stick),
                            disabled=not self.sticks),
        ])

    async def pick_iso(self) -> None:
        files = await self.file_picker.pick_files(dialog_title="Choose a NanoBorealis installer ISO",
                                                  allowed_extensions=["iso"])
        if files and files[0].path:
            self.stick_iso = files[0].path
            self.stick_iso_text.value = os.path.basename(self.stick_iso)
            self.stick_source.value = "file"
            self.page.update()

    async def confirm_stick(self) -> None:
        stick = next((s for s in self.sticks if s.id == self.stick_choice.value), None)
        if stick is None:
            self.stick_choice.error_text = "Choose a stick"
            self.page.update()
            return
        if self.stick_source.value == "file" and not self.stick_iso:
            self.stick_iso_text.value = "Choose the ISO file first"
            self.page.update()
            return
        source = "latest" if self.stick_source.value == "latest" else self.stick_iso
        key = (self.stick_key.value or "").strip()
        channel = self.stick_channel.value or "stable"
        # What the installed system reads from the stick: the key, and which build to follow.
        setup: dict[str, str] | None = {"written_by": "NanoBorealis client"}
        if key:
            setup["openrouter_api_key"] = key
        if channel != "stable":
            setup["channel"] = channel
        if len(setup) == 1:
            setup = None
        build = dict(STICK_BUILDS)[channel].split(":")[0]
        details = [ft.Text(f"Build: {build}", size=13)]
        if source == "latest":
            self.set_stick_body([self.working("Finding the installer...")], [])
            try:
                release = await asyncio.to_thread(stickmaker.latest_release, channel)
                details.append(ft.Text(f"Installer: {release.iso_name}", size=13, selectable=True))
                if channel != "stable" and not release.tag.startswith(f"nanoborealis-{channel}-"):
                    details.append(ft.Text(f"There's no {build} installer yet, so this is the stable one. The new "
                                           f"computer moves to {build} at first login.",
                                           size=12, color=ft.Colors.ON_SURFACE_VARIANT))
            except Exception as e:
                print(f"nanoborealis-client: finding the installer failed: {e}")
        elif channel != "stable":
            details.append(ft.Text(f"The new computer moves to {build} at first login.",
                                   size=12, color=ft.Colors.ON_SURFACE_VARIANT))
        self.set_stick_body([
            ft.Row([ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=ft.Colors.ERROR),
                    ft.Text(f"Erase {stick.label}? Everything on it will be lost.", size=14, expand=True)], spacing=10),
            *details,
            ft.Text("Windows will ask for permission to write the stick." if sys.platform == "win32"
                    else "Your system will ask for your password to write the stick.",
                    size=13, color=ft.Colors.ON_SURFACE_VARIANT),
        ], [
            ft.TextButton("Back", on_click=on(self.show_stick_form)),
            ft.FilledButton("Erase and write", icon=ft.Icons.USB_ROUNDED, bgcolor=ft.Colors.ERROR,
                            color=ft.Colors.ON_ERROR, on_click=on(self.write_stick, stick, source, setup)),
        ])

    async def write_stick(self, stick: stickmaker.Disk, source: str, setup: dict | None) -> None:
        status = ft.Text("Waiting for permission...", size=13)
        bar = ft.ProgressBar(value=None)
        self.set_stick_body([status, bar,
                             ft.Text("Keep the stick plugged in. This takes about ten minutes.", size=12,
                                     color=ft.Colors.ON_SURFACE_VARIANT)],
                            [ft.TextButton("Hide", on_click=on(self.close_stick_dialog))])
        progress_file = os.path.join(tempfile.gettempdir(), f"nanoborealis-stick-{uuid.uuid4().hex[:8]}.json")
        try:
            await asyncio.to_thread(stickmaker.launch_elevated, stick, source, setup, progress_file)
        except stickmaker.StickError as e:
            self.show_stick_result(False, str(e))
            return
        self.stick_writing = True
        started = time.monotonic()
        last = None
        try:
            while True:
                await asyncio.sleep(0.5)
                try:
                    with open(progress_file, encoding="utf-8") as f:
                        state = json.load(f)
                except (OSError, ValueError):
                    if time.monotonic() - started > 120 and last is None:
                        self.show_stick_result(False, "The writer never started. Was the permission prompt declined?")
                        return
                    continue
                last = state
                if state.get("phase") == "error":
                    self.show_stick_result(False, state.get("error") or "Something went wrong")
                    return
                if state.get("phase") == "done":
                    self.show_stick_result(True, "")
                    return
                total = state.get("total") or 0
                bar.value = (state.get("done", 0) / total) if total else None
                verb = {"write": "Writing", "verify": "Checking"}.get(state.get("phase"), "")
                status.value = state.get("message", "")
                if total and verb:
                    status.value += f" ({state.get('done', 0) / 1e9:.1f} of {total / 1e9:.1f} GB)"
                self.page.update()
        finally:
            self.stick_writing = False
            try:
                os.remove(progress_file)
            except OSError:
                pass

    def show_stick_result(self, ok: bool, error: str) -> None:
        if ok:
            self.set_stick_body([
                ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED, color=ft.Colors.GREEN_400),
                        ft.Text("The stick is ready and verified.", size=14, expand=True)], spacing=10),
                ft.Text("Boot the new computer from it: open its boot menu at power-on (F9 on HP, F12 on Dell and "
                        "Lenovo, Option on a Mac), install, and tick \"Make this user administrator\". At first "
                        "login, setup uses the key you saved on the stick.", size=13),
            ], [ft.FilledButton("Done", on_click=on(self.close_stick_dialog))])
        else:
            self.set_stick_body([ft.Text(f"The stick wasn't written: {error}", size=13, color=ft.Colors.ERROR)],
                                [ft.TextButton("Close", on_click=on(self.close_stick_dialog)),
                                 ft.FilledButton("Try again", on_click=on(self.show_stick_form))])

    # -- Sending -----------------------------------------------------------------

    async def send_text(self, text: str) -> None:
        self.composer.value = text
        await self.on_send()

    async def on_send(self, _event=None) -> None:
        text = (self.composer.value or "").strip()
        if not text or self.busy:
            return
        if self.link is None or not self.link.connected:
            self.add(self.error_row("Not connected to the agent yet."))
            return
        self.composer.value = ""
        self.page.update()
        if self.chat_id is None:
            try:
                self.chat_id = await self.link.new_chat()
            except (LinkError, asyncio.TimeoutError) as e:
                self.composer.value = text
                self.add(self.error_row(f"Could not start a chat: {e}"))
                return
            self.title_text.value = text.splitlines()[0][:80]
        self.reset_turn()
        self.add(self.user_bubble(text))
        self.set_busy(True)
        self.page.update()
        try:
            await self.link.send_message(self.chat_id, text)
        except LinkError as e:
            self.add(self.error_row(str(e)))
            self.set_busy(False)
            self.page.update()
        await self.composer.focus()

    async def on_stop(self, _event=None) -> None:
        if self.link is None or self.chat_id is None:
            return
        try:
            await self.link.stop_turn(self.chat_id)
        except LinkError as e:
            self.add(self.error_row(str(e)))
            return
        # nanobot answers /stop with a short message but never sends turn_end for the
        # cancelled turn, so the turn is over as far as this window is concerned.
        self.close_reasoning()
        self.reset_turn()
        self.set_busy(False)
        self.page.update()


async def main(page: ft.Page) -> None:
    await NanoBorealisApp(page).start()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "write":
        # The packaged app relaunching itself, elevated, to write an install stick.
        sys.exit(stickmaker._cli(sys.argv[1:]))
    # Under pythonw (no console) these are None, and Flet writes download progress to them.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    ft.run(main, assets_dir=ASSETS)
