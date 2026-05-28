#!/usr/bin/env python3
"""smb-tui - Interactive terminal UI for Samba configuration management."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
)

from smb_config import SmbConfig
from smb_users import SmbUserManager

DEFAULT_CONFIG = "/etc/samba/smb.conf"


# ---------------------------------------------------------------------------
# Sudo helpers
# ---------------------------------------------------------------------------


def _cache_sudo(password):
    """Validate sudo password and cache a timestamp. Returns True on success."""
    result = subprocess.run(
        ["sudo", "-S", "-v"],
        capture_output=True,
        text=True,
        input=password + "\n",
        timeout=10,
    )
    return result.returncode == 0


def _sudo_write_file(content, path):
    """Write content to path using sudo cp (needs cached sudo timestamp)."""
    import tempfile

    tmp = tempfile.NamedTemporaryFile(mode="w", delete=False, prefix="smb-tui-")
    try:
        tmp.write(content)
        tmp.close()
        result = subprocess.run(
            ["sudo", "cp", tmp.name, path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise OSError(result.stderr.strip() or "sudo cp failed")
    finally:
        os.unlink(tmp.name)


def _sudo_copy(src, dst):
    """Copy src to dst using sudo cp (needs cached sudo timestamp)."""
    result = subprocess.run(
        ["sudo", "cp", src, dst],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or "sudo cp failed")


def _check_writable(path):
    """Check if a file or its parent directory is writable."""
    if os.path.exists(path):
        return os.access(path, os.W_OK)
    parent = os.path.dirname(path) or "."
    return os.access(parent, os.W_OK)


# ---------------------------------------------------------------------------
# Modal screens
# ---------------------------------------------------------------------------


class ConfirmModal(ModalScreen[bool]):
    """A generic yes/no confirmation dialog."""

    BINDINGS = [Binding("escape", "dismiss_no", "No")]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(self._message, id="confirm-msg", markup=False)
            with Horizontal(id="confirm-buttons"):
                yield Button("Yes", variant="primary", id="btn-yes")
                yield Button("No", variant="default", id="btn-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-yes":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_dismiss_no(self) -> None:
        self.dismiss(False)


class InfoModal(ModalScreen[None]):
    """Display informational text (validation output, etc.)."""

    BINDINGS = [Binding("escape", "dismiss_ok", "OK")]

    def __init__(self, title: str, content: str) -> None:
        super().__init__()
        self._title = title
        self._content = content

    def compose(self) -> ComposeResult:
        with Vertical(id="info-box"):
            yield Static(self._title, id="info-title", markup=False)
            yield Static(self._content, id="info-body", markup=False)
            with Horizontal(id="info-buttons"):
                yield Button("OK", variant="primary", id="btn-ok")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()

    def action_dismiss_ok(self) -> None:
        self.dismiss()


class EditParamModal(ModalScreen[tuple[str, str] | None]):
    """Add or edit a single parameter on a share."""

    BINDINGS = [Binding("escape", "dismiss_cancel", "Cancel")]

    def __init__(self, section_name: str, key: str = "", value: str = "") -> None:
        super().__init__()
        self._section = section_name
        self._existing_key = key
        self._existing_value = value

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-param-box"):
            title = "Edit Parameter" if self._existing_key else "Add Parameter"
            yield Static(title, id="edit-param-title")
            yield Label("Key:")
            yield Input(value=self._existing_key, id="param-key", placeholder="Parameter name")
            yield Label("Value:")
            yield Input(value=self._existing_value, id="param-value", placeholder="Parameter value")
            with Horizontal(id="edit-param-buttons"):
                yield Button("Save", variant="primary", id="btn-save")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#param-key", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        else:
            key = self.query_one("#param-key", Input).value.strip()
            value = self.query_one("#param-value", Input).value.strip()
            if not key:
                self.notify("Key cannot be empty.", severity="error")
                return
            self.dismiss((key, value))

    def action_dismiss_cancel(self) -> None:
        self.dismiss(None)


class AddShareModal(ModalScreen[bool]):
    """Form to create or edit a share.
    If editing, pass edit_name to pre-fill fields and update instead of add."""

    BINDINGS = [Binding("escape", "dismiss_cancel", "Cancel")]

    def __init__(self, edit_name: str = "") -> None:
        super().__init__()
        self._edit_name = edit_name

    def compose(self) -> ComposeResult:
        is_edit = bool(self._edit_name)
        title = f"Edit Share: {self._edit_name}" if is_edit else "Add New Share"
        btn_label = "Update" if is_edit else "Add Share"

        with VerticalScroll(id="add-share-form"):
            yield Static(title, id="form-title", markup=False)
            yield Label("")
            yield Label("Name")
            yield Input(
                value=self._edit_name,
                id="share-name",
                placeholder="Share name",
                disabled=is_edit,
            )
            yield Label("Path *")
            yield Input(id="share-path", placeholder="/path/to/directory")
            yield Label("Comment")
            yield Input(id="share-comment", placeholder="Description")
            yield Label("Guest Ok")
            yield Select(
                [("(not set)", "-"), ("yes", "yes"), ("no", "no")],
                id="share-guest-ok",
            )
            yield Label("Read Only")
            yield Select(
                [("(not set)", "-"), ("yes", "yes"), ("no", "no")],
                id="share-read-only",
            )
            yield Label("Browseable")
            yield Select(
                [("(not set)", "-"), ("yes", "yes"), ("no", "no")],
                id="share-browseable",
            )
            yield Label("Create Mask")
            yield Input(id="share-create-mask", placeholder="e.g. 0700")
            yield Label("Directory Mask")
            yield Input(id="share-dir-mask", placeholder="e.g. 0700")
            yield Label("Valid Users")
            yield Input(id="share-valid-users", placeholder="user1,user2")
            yield Label("Write List")
            yield Input(id="share-write-list", placeholder="user1,user2")
            with Horizontal(id="add-share-buttons"):
                yield Button(btn_label, variant="primary", id="btn-add")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        if self._edit_name:
            self._prefill()
        self.query_one("#share-path", Input).focus()

    def _prefill(self) -> None:
        """Pre-fill form fields from existing share config."""
        cfg = self.app.config  # type: ignore[attr-defined]

        def get(key):
            try:
                return cfg.get_param(self._edit_name, key)
            except KeyError:
                return ""

        self.query_one("#share-path", Input).value = get("path")
        self.query_one("#share-comment", Input).value = get("comment")
        self.query_one("#share-create-mask", Input).value = get("create mask")
        self.query_one("#share-dir-mask", Input).value = get("directory mask")
        self.query_one("#share-valid-users", Input).value = get("valid users")
        self.query_one("#share-write-list", Input).value = get("write list")
        self._preselect("share-guest-ok", get("guest ok"))
        self._preselect("share-read-only", get("read only"))
        self._preselect("share-browseable", get("browseable"))

    def _preselect(self, select_id, value):
        if value and value != "-":
            try:
                self.query_one(f"#{select_id}", Select).value = value
            except Exception:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(False)
            return

        name = self._edit_name or self.query_one("#share-name", Input).value.strip()
        path = self.query_one("#share-path", Input).value.strip()

        if not name:
            self.notify("Name is required.", severity="error")
            return
        if not path:
            self.notify("Path is required.", severity="error")
            return

        cfg = self.app.config  # type: ignore[attr-defined]

        if not self._edit_name:
            try:
                cfg.add_section(name)
            except ValueError as e:
                self.notify(str(e), severity="error")
                return

        cfg.set_param(name, "path", path)

        optional_str_fields = [
            ("share-comment", "comment"),
            ("share-create-mask", "create mask"),
            ("share-dir-mask", "directory mask"),
            ("share-valid-users", "valid users"),
            ("share-write-list", "write list"),
        ]
        for input_id, param_name in optional_str_fields:
            val = self.query_one(f"#{input_id}", Input).value.strip()
            if val:
                cfg.set_param(name, param_name, val)
            elif self._edit_name:
                try:
                    cfg.remove_param(name, param_name)
                except KeyError:
                    pass

        optional_select_fields = [
            ("share-guest-ok", "guest ok"),
            ("share-read-only", "read only"),
            ("share-browseable", "browseable"),
        ]
        for select_id, param_name in optional_select_fields:
            val = self.query_one(f"#{select_id}", Select).value
            if val and val != "-":
                cfg.set_param(name, param_name, str(val))
            elif self._edit_name:
                try:
                    cfg.remove_param(name, param_name)
                except KeyError:
                    pass

        self.dismiss(True)

    def action_dismiss_cancel(self) -> None:
        self.dismiss(False)


class SudoPasswordModal(ModalScreen[str | None]):
    """Prompt for the sudo password (cached for the session)."""

    BINDINGS = [Binding("escape", "dismiss_cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-param-box"):
            yield Static("Sudo: enter your password", id="edit-param-title")
            yield Label("Sudo password:")
            yield Input(id="sudo-pw", password=True, placeholder="Enter sudo password")
            with Horizontal(id="edit-param-buttons"):
                yield Button("OK", variant="primary", id="btn-ok")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#sudo-pw", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        else:
            pw = self.query_one("#sudo-pw", Input).value
            if not pw:
                self.notify("Password cannot be empty.", severity="error")
                return
            self.dismiss(pw)

    def action_dismiss_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Main screens
# ---------------------------------------------------------------------------


class ShareDetailScreen(Screen[None]):
    """Show all parameters for a single share."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("a", "add_param", "Add Param"),
        Binding("e", "edit_param", "Edit"),
        Binding("ctrl+d", "remove_param", "Remove"),
        Binding("t", "toggle_section", "Toggle"),
    ]

    def __init__(self, section_name: str) -> None:
        super().__init__()
        self._section = section_name

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="section-info", markup=False)
        yield DataTable(id="params-table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#params-table", DataTable)
        table.cursor_type = "row"
        table.add_column("", width=2)
        table.add_column("Key")
        table.add_column("Value")
        self._refresh()

    def _refresh(self) -> None:
        table = self.query_one("#params-table", DataTable)
        table.clear()
        cfg = self.app.config  # type: ignore[attr-defined]
        try:
            enabled = cfg.is_enabled(self._section)
        except KeyError:
            self.notify(f"Share [{self._section}] not found.", severity="error")
            return

        status_str = "yes" if enabled else "no"
        self.query_one("#section-info", Static).update(
            f"Share: {self._section}  (enabled: {status_str})"
        )

        try:
            params = cfg.section_params(self._section)
        except KeyError:
            params = []

        for key, value, _, param_enabled in params:
            flag = " " if param_enabled else "D"
            table.add_row(flag, key, value, key=key)

    def _get_selected_key(self) -> str | None:
        table = self.query_one("#params-table", DataTable)
        if table.cursor_coordinate is not None:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
            return str(cell_key.row_key.value)  # type: ignore[no-any-return]
        return None

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_add_param(self) -> None:
        self.app.push_screen(EditParamModal(self._section), self._on_param_done)

    def action_edit_param(self) -> None:
        key = self._get_selected_key()
        if key is None:
            self.notify("No parameter selected.", severity="warning")
            return
        cfg = self.app.config  # type: ignore[attr-defined]
        try:
            value = cfg.get_param(self._section, key)
        except KeyError:
            value = ""
        self.app.push_screen(
            EditParamModal(self._section, key=key, value=value),
            self._on_param_done,
        )

    def action_remove_param(self) -> None:
        key = self._get_selected_key()
        if key is None:
            self.notify("No parameter selected.", severity="warning")
            return

        def on_confirmed(confirmed: bool) -> None:
            if confirmed:
                cfg = self.app.config  # type: ignore[attr-defined]
                try:
                    cfg.remove_param(self._section, key)
                except KeyError as e:
                    self.notify(str(e), severity="error")
                    return
                self.app.dirty = True  # type: ignore[attr-defined]
                self._refresh()

        self.app.push_screen(
            ConfirmModal(f"Remove parameter '{key}'?"), on_confirmed
        )

    def action_toggle_section(self) -> None:
        cfg = self.app.config  # type: ignore[attr-defined]
        try:
            if cfg.is_enabled(self._section):
                cfg.disable_section(self._section)
            else:
                cfg.enable_section(self._section)
        except KeyError as e:
            self.notify(str(e), severity="error")
            return
        self.app.dirty = True  # type: ignore[attr-defined]
        self._refresh()

    def _on_param_done(self, result: tuple[str, str] | None) -> None:
        if result is None:
            return
        key, value = result
        cfg = self.app.config  # type: ignore[attr-defined]
        try:
            cfg.set_param(self._section, key, value)
        except KeyError as e:
            self.notify(str(e), severity="error")
            return
        self.app.dirty = True  # type: ignore[attr-defined]
        self._refresh()


class UserPasswordModal(ModalScreen[tuple[str, str] | None]):
    """Modal to enter and confirm a password."""

    BINDINGS = [Binding("escape", "dismiss_cancel", "Cancel")]

    def __init__(self, username: str, action: str = "change") -> None:
        super().__init__()
        self._username = username
        self._action = action  # "add" or "change"

    def compose(self) -> ComposeResult:
        title = f"Set password for {self._username}" if self._action == "add" \
                else f"Change password for {self._username}"
        with Vertical(id="edit-param-box"):
            yield Static(title, id="edit-param-title")
            yield Label("Password:")
            yield Input(id="pw1", password=True, placeholder="Enter password")
            yield Label("Confirm:")
            yield Input(id="pw2", password=True, placeholder="Retype password")
            with Horizontal(id="edit-param-buttons"):
                yield Button("OK", variant="primary", id="btn-save")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#pw1", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
            return
        pw1 = self.query_one("#pw1", Input).value
        pw2 = self.query_one("#pw2", Input).value
        if not pw1:
            self.notify("Password cannot be empty.", severity="error")
            return
        if pw1 != pw2:
            self.notify("Passwords do not match.", severity="error")
            return
        self.dismiss((pw1, pw2))

    def action_dismiss_cancel(self) -> None:
        self.dismiss(None)


class UserListScreen(Screen[None]):
    """Screen listing all Samba users."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("a", "add_user", "Add"),
        Binding("ctrl+d", "remove_user", "Remove"),
        Binding("e", "enable_user", "Enable"),
        Binding("d", "disable_user", "Disable"),
        Binding("p", "passwd_user", "Passwd"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="users-table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#users-table", DataTable)
        table.cursor_type = "row"
        table.add_column("User")
        table.add_column("UID")
        table.add_column("Full Name")
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one("#users-table", DataTable)
        table.clear()
        users = SmbUserManager.list_users(use_sudo=self._use_sudo)
        for u in users:
            table.add_row(u["name"], u.get("uid", ""), u.get("fullname", ""), key=u["name"])

    @property
    def _use_sudo(self) -> bool:
        return self.app._sudo_ok  # type: ignore[attr-defined]

    def _ensure_sudo(self, on_ready):
        """Prompt for sudo password if needed, then call on_ready(True/False)."""
        self.app._ensure_sudo(on_ready)  # type: ignore[attr-defined]

    def _get_selected_user(self) -> str | None:
        table = self.query_one("#users-table", DataTable)
        if table.cursor_coordinate is not None:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
            return str(cell_key.row_key.value)  # type: ignore[no-any-return]
        return None

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_add_user(self) -> None:
        self.app.push_screen(
            AddUserModal(),
            lambda result: self._on_add_user(result) if result else None,
        )

    def _on_add_user(self, result: tuple[str, str]) -> None:
        username, password = result

        def do_add(ready: bool) -> None:
            if not ready:
                return
            ok, msg = SmbUserManager.add_user(username, password, use_sudo=self._use_sudo)
            if ok:
                self.notify(msg, severity="info")
                self._refresh_table()
            else:
                self.notify(msg, severity="error")

        self._ensure_sudo(do_add)

    def action_remove_user(self) -> None:
        name = self._get_selected_user()
        if name is None:
            self.notify("No user selected.", severity="warning")
            return

        def on_confirmed(confirmed: bool) -> None:
            if confirmed:
                def do_remove(ready: bool) -> None:
                    if not ready:
                        return
                    ok, msg = SmbUserManager.remove_user(name, use_sudo=self._use_sudo)
                    if ok:
                        self.notify(msg, severity="info")
                        self._refresh_table()
                    else:
                        self.notify(msg, severity="error")
                self._ensure_sudo(do_remove)

        self.app.push_screen(
            ConfirmModal(f"Remove Samba user [{name}]?"), on_confirmed
        )

    def action_enable_user(self) -> None:
        name = self._get_selected_user()
        if name is None:
            self.notify("No user selected.", severity="warning")
            return

        def do_enable(ready: bool) -> None:
            if not ready:
                return
            ok, msg = SmbUserManager.enable_user(name, use_sudo=self._use_sudo)
            if ok:
                self.notify(msg, severity="info")
                self._refresh_table()
            else:
                self.notify(msg, severity="error")

        self._ensure_sudo(do_enable)

    def action_disable_user(self) -> None:
        name = self._get_selected_user()
        if name is None:
            self.notify("No user selected.", severity="warning")
            return

        def do_disable(ready: bool) -> None:
            if not ready:
                return
            ok, msg = SmbUserManager.disable_user(name, use_sudo=self._use_sudo)
            if ok:
                self.notify(msg, severity="info")
                self._refresh_table()
            else:
                self.notify(msg, severity="error")

        self._ensure_sudo(do_disable)

    def action_passwd_user(self) -> None:
        name = self._get_selected_user()
        if name is None:
            self.notify("No user selected.", severity="warning")
            return

        def on_password(result: tuple[str, str] | None) -> None:
            if result is None:
                return
            pw1, _ = result

            def do_passwd(ready: bool) -> None:
                if not ready:
                    return
                ok, msg = SmbUserManager.change_password(name, pw1, use_sudo=self._use_sudo)
                self.notify(msg, severity="info" if ok else "error")

            self._ensure_sudo(do_passwd)

        self.app.push_screen(UserPasswordModal(name, action="change"), on_password)


class AddUserModal(ModalScreen[tuple[str, str] | None]):
    """Form to add a new Samba user (username + password)."""

    BINDINGS = [Binding("escape", "dismiss_cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-param-box"):
            yield Static("Add Samba User", id="edit-param-title")
            yield Label("Username:")
            yield Input(id="new-user-name", placeholder="Username")
            yield Label("Password:")
            yield Input(id="new-user-pw1", password=True, placeholder="Enter password")
            yield Label("Confirm:")
            yield Input(id="new-user-pw2", password=True, placeholder="Retype password")
            with Horizontal(id="edit-param-buttons"):
                yield Button("Add", variant="primary", id="btn-save")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#new-user-name", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
            return
        name = self.query_one("#new-user-name", Input).value.strip()
        pw1 = self.query_one("#new-user-pw1", Input).value
        pw2 = self.query_one("#new-user-pw2", Input).value
        if not name:
            self.notify("Username is required.", severity="error")
            return
        if not pw1:
            self.notify("Password cannot be empty.", severity="error")
            return
        if pw1 != pw2:
            self.notify("Passwords do not match.", severity="error")
            return
        self.dismiss((name, pw1))

    def action_dismiss_cancel(self) -> None:
        self.dismiss(None)


class MainListScreen(Screen[None]):
    """Primary screen listing all shares."""

    BINDINGS = [
        Binding("enter", "view_detail", "View"),
        Binding("a", "add_share", "Add"),
        Binding("e", "enable_share", "Enable"),
        Binding("E", "edit_share", "Edit"),
        Binding("d", "disable_share", "Disable"),
        Binding("ctrl+d", "remove_share", "Remove"),
        Binding("v", "validate", "Validate"),
        Binding("b", "backup", "Backup"),
        Binding("r", "reload", "Reload"),
        Binding("s", "save", "save", "Save"),
        Binding("u", "users", "Users"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="shares-table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#shares-table", DataTable)
        table.cursor_type = "row"
        table.add_column("Status", width=7)
        table.add_column("Share")
        table.add_column("Path")
        table.add_column("Comment")
        self._refresh_table()

    def on_screen_resume(self) -> None:
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one("#shares-table", DataTable)
        table.clear()
        cfg = self.app.config  # type: ignore[attr-defined]
        for name, enabled, _ in cfg.sections():
            path = "-"
            comment = ""
            try:
                path = cfg.get_param(name, "path")
            except KeyError:
                pass
            try:
                comment = cfg.get_param(name, "comment")
            except KeyError:
                pass
            status = "yes" if enabled else "no"
            table.add_row(status, name, str(path), str(comment), key=name)

    def _get_selected_share_name(self) -> str | None:
        table = self.query_one("#shares-table", DataTable)
        if table.cursor_coordinate is not None:
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
            return str(cell_key.row_key.value)  # type: ignore[no-any-return]
        return None

    def action_view_detail(self) -> None:
        name = self._get_selected_share_name()
        if name is None:
            self.notify("No share selected.", severity="warning")
            return
        self.app.push_screen(ShareDetailScreen(name))

    def action_add_share(self) -> None:
        def on_done(result: bool) -> None:
            if result:
                self.app.dirty = True  # type: ignore[attr-defined]
                self._refresh_table()

        self.app.push_screen(AddShareModal(), on_done)

    def action_edit_share(self) -> None:
        name = self._get_selected_share_name()
        if name is None:
            self.notify("No share selected.", severity="warning")
            return

        def on_done(result: bool) -> None:
            if result:
                self.app.dirty = True  # type: ignore[attr-defined]
                self._refresh_table()

        self.app.push_screen(AddShareModal(edit_name=name), on_done)

    def action_enable_share(self) -> None:
        name = self._get_selected_share_name()
        if name is None:
            self.notify("No share selected.", severity="warning")
            return
        cfg = self.app.config  # type: ignore[attr-defined]
        try:
            if cfg.is_enabled(name):
                self.notify(f"[{name}] is already enabled.", severity="info")
                return
            cfg.enable_section(name)
        except KeyError as e:
            self.notify(str(e), severity="error")
            return
        self.app.dirty = True  # type: ignore[attr-defined]
        self._refresh_table()

    def action_disable_share(self) -> None:
        name = self._get_selected_share_name()
        if name is None:
            self.notify("No share selected.", severity="warning")
            return
        cfg = self.app.config  # type: ignore[attr-defined]
        try:
            if not cfg.is_enabled(name):
                self.notify(f"[{name}] is already disabled.", severity="info")
                return
            cfg.disable_section(name)
        except KeyError as e:
            self.notify(str(e), severity="error")
            return
        self.app.dirty = True  # type: ignore[attr-defined]
        self._refresh_table()

    def action_remove_share(self) -> None:
        name = self._get_selected_share_name()
        if name is None:
            self.notify("No share selected.", severity="warning")
            return

        def on_confirmed(confirmed: bool) -> None:
            if confirmed:
                cfg = self.app.config  # type: ignore[attr-defined]
                try:
                    cfg.remove_section(name)
                except KeyError as e:
                    self.notify(str(e), severity="error")
                    return
                self.app.dirty = True  # type: ignore[attr-defined]
                self._refresh_table()

        self.app.push_screen(
            ConfirmModal(f"Remove share [{name}]?"), on_confirmed
        )

    def action_validate(self) -> None:
        config_path = self.app.config_path  # type: ignore[attr-defined]
        if not os.path.exists(config_path):
            self.app.push_screen(
                InfoModal("Validation", f"Config file not found:\n{config_path}")
            )
            return
        try:
            result = subprocess.run(
                ["testparm", "-s", config_path],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                msg = "Configuration OK."
            else:
                msg = result.stderr or result.stdout or "Unknown error."
        except FileNotFoundError:
            msg = "testparm not found. Is samba installed?"
        self.app.push_screen(InfoModal("Validation Result", msg))

    def action_backup(self) -> None:
        config_path = self.app.config_path  # type: ignore[attr-defined]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = f"{config_path}.bak.{ts}"
        dry_run = self.app.dry_run  # type: ignore[attr-defined]

        if dry_run:
            self.notify(f"[dry-run] Would backup to {bak}", severity="info")
            return

        if not os.path.exists(config_path):
            self.notify(f"Config file not found: {config_path}", severity="error")
            return

        app = self.app  # type: ignore[attr-defined]
        needs_sudo = app.needs_sudo

        def do_backup(ready: bool) -> None:
            if not ready:
                return
            try:
                if needs_sudo:
                    _sudo_copy(config_path, bak)
                else:
                    shutil.copy2(config_path, bak)
                self.notify(f"Backed up to {bak}", severity="info")
            except OSError as e:
                self.notify(f"Backup failed: {e}", severity="error")

        if needs_sudo:
            app._ensure_sudo(do_backup)
        else:
            do_backup(True)

    def action_reload(self) -> None:
        cfg = self.app.config  # type: ignore[attr-defined]
        config_path = self.app.config_path  # type: ignore[attr-defined]

        if self.app.dirty:  # type: ignore[attr-defined]
            def on_confirmed(confirmed: bool) -> None:
                if confirmed:
                    cfg.load(config_path)
                    self.app.dirty = False  # type: ignore[attr-defined]
                    self._refresh_table()
                    self.notify("Configuration reloaded.", severity="info")

            self.app.push_screen(
                ConfirmModal("Discard unsaved changes and reload?"), on_confirmed
            )
        else:
            cfg.load(config_path)
            self._refresh_table()
            self.notify("Configuration reloaded.", severity="info")

    def action_save(self) -> None:
        self.app.action_save()

    def action_users(self) -> None:
        self.app.push_screen(UserListScreen())


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class SmbTuiApp(App[None]):
    """Interactive TUI for managing Samba smb.conf."""

    TITLE = "Samba Config Manager"
    SUB_TITLE = "smb-tui"

    BINDINGS = [
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    CSS = """
    Screen {
        align: center middle;
    }

    #shares-table, #params-table {
        height: 1fr;
        margin: 1 2;
    }

    #section-info {
        margin: 0 2;
        text-style: bold;
        color: $accent;
    }

    /* --- Modal shared styles --- */
    #confirm-box, #edit-param-box {
        width: 50;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #info-box {
        width: 60;
        max-height: 30;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #add-share-form {
        width: 52;
        max-height: 30;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #info-body {
        margin: 1 0;
        max-height: 20;
    }

    #confirm-msg {
        margin: 1 0;
        content-align: center middle;
    }

    #form-title, #edit-param-title, #info-title {
        text-style: bold;
        content-align: center middle;
        margin-bottom: 1;
    }

    Horizontal {
        align: center middle;
        height: auto;
        margin-top: 1;
    }

    Button {
        margin: 0 1;
        min-width: 12;
    }

    Label {
        margin-top: 1;
    }

    Input, Select {
        margin-bottom: 1;
    }
    """

    def __init__(self, config_path: str, dry_run: bool = False) -> None:
        super().__init__()
        self.config_path = config_path
        self.dry_run = dry_run
        self.config = SmbConfig()
        self.dirty = False
        self._sudo_ok = False
        self.needs_sudo = False

    def on_mount(self) -> None:
        try:
            self.config.load(self.config_path)
        except FileNotFoundError:
            self.notify(
                f"Config file not found: {self.config_path}",
                severity="error",
                timeout=10,
            )
        except PermissionError:
            self.notify(
                f"Permission denied: {self.config_path}",
                severity="error",
                timeout=10,
            )
        self.needs_sudo = not _check_writable(self.config_path)
        self.push_screen(MainListScreen())

        if self.needs_sudo:
            self._ensure_sudo(lambda _: None)

    def _ensure_sudo(self, on_ready):
        """If sudo is needed and not yet cached, prompt for password and cache.
        Then call on_ready(True/False)."""
        if not self.needs_sudo or self._sudo_ok:
            on_ready(True)
            return

        def on_pw(password):
            if not password:
                on_ready(False)
                return
            if _cache_sudo(password):
                self._sudo_ok = True
                on_ready(True)
            else:
                self.notify("Sudo password incorrect.", severity="error")
                on_ready(False)

        self.push_screen(SudoPasswordModal(), on_pw)

    def _save_config(self) -> None:
        """Actually write the config, using sudo if needed."""
        content = "\n".join(self.config.lines) + "\n"
        if self.dry_run:
            print(f"[dry-run] Would write to {self.config_path}:")
            for line in self.config.lines:
                print(line)
        elif self.needs_sudo:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            bak = f"{self.config_path}.bak.{ts}"
            if os.path.exists(self.config_path):
                _sudo_copy(self.config_path, bak)
            _sudo_write_file(content, self.config_path)
        else:
            self.config.save(dry_run=False)

    def action_save(self) -> None:
        def do_save(ready: bool) -> None:
            if not ready:
                return
            try:
                self._save_config()
                self.dirty = False
                msg = "[dry-run] Changes would be written." if self.dry_run else "Configuration saved."
                self.notify(msg, severity="info")
            except OSError as e:
                self._sudo_ok = False
                self.notify(f"Save failed: {e}", severity="error")

        self._ensure_sudo(do_save)

    def action_quit(self) -> None:
        if self.dirty:

            def do_save_and_exit() -> None:
                try:
                    self._save_config()
                except OSError:
                    pass
                self.exit()

            def on_quit_confirm(confirmed: bool) -> None:
                if confirmed:
                    self._ensure_sudo(lambda ready: do_save_and_exit() if ready else None)
                else:
                    self.push_screen(
                        ConfirmModal("Quit without saving?"),
                        lambda r: self.exit() if r else None,
                    )

            self.push_screen(
                ConfirmModal("Save changes before quitting?"),
                on_quit_confirm,
            )
        else:
            self.exit()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="smb-tui",
        description="Interactive TUI for managing Samba (smb.conf) configuration.",
    )
    parser.add_argument(
        "--config",
        "-c",
        default=DEFAULT_CONFIG,
        help=f"Path to smb.conf (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be done without writing",
    )
    args = parser.parse_args()
    SmbTuiApp(args.config, args.dry_run).run()


if __name__ == "__main__":
    main()
