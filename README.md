# smb-tui

A terminal-based manager for Samba (`smb.conf`) configuration and users.

Comes in two flavors:

- **`smb-tui`** — interactive TUI (built with [Textual](https://github.com/Textualize/textual))
- **`smb`** — non-interactive CLI for scripting

Both tools edit `smb.conf` in-place while preserving comments, indentation, and formatting. Every write is preceded by an automatic timestamped backup.

---

## Requirements

- Python 3.10+
- Samba (`smbpasswd`, `pdbedit`, `testparm`)
- [Textual](https://github.com/Textualize/textual) (TUI only)

```bash
sudo apt install samba samba-common-bin -y
pip install textual
```

---

## TUI — `smb_tui.py`

```
python smb_tui.py [--config /path/to/smb.conf] [--dry-run]
```

### Keyboard shortcuts

**Main screen (share list)**

| Key | Action |
|-----|--------|
| `Enter` | View share details |
| `a` | Add share |
| `E` | Edit share |
| `e` | Enable share |
| `d` | Disable share |
| `Ctrl+D` | Remove share |
| `u` | Manage users |
| `v` | Validate config (`testparm`) |
| `b` | Backup config |
| `r` | Reload config from disk |
| `Ctrl+S` / `s` | Save |
| `Ctrl+Q` | Quit |

**Share detail screen**

| Key | Action |
|-----|--------|
| `a` | Add parameter |
| `e` | Edit parameter |
| `Ctrl+D` | Remove parameter |
| `t` | Toggle share enabled/disabled |
| `Esc` | Back |

**User list screen**

| Key | Action |
|-----|--------|
| `a` | Add user |
| `Ctrl+D` | Remove user |
| `e` | Enable user |
| `d` | Disable user |
| `p` | Change password |
| `Esc` | Back |

If the config file requires root access, the TUI will prompt for your sudo password once and cache it for the session.

---

## CLI — `smb_cli.py`

```
python smb_cli.py [--config /path/to/smb.conf] [--dry-run] COMMAND
```

### Share commands

```bash
# List all shares
smb list

# Show all parameters of a share
smb show <name>

# Add a share
smb add <name> <path> [--comment TEXT] [--guest-ok yes|no]
        [--read-only yes|no] [--browseable yes|no]
        [--create-mask MASK] [--directory-mask MASK]
        [--valid-users user1,user2] [--write-list user1,user2]

# Remove a share
smb remove <name> [--force]

# Set / unset a parameter
smb set <name> <key> <value>
smb unset <name> <key>

# Enable / disable a share
smb enable <name>
smb disable <name> [--force]

# Validate config syntax
smb validate

# Create a timestamped backup
smb backup
```

### User commands

```bash
smb user list [--verbose]
smb user add <name> [--password PASSWORD]
smb user remove <name> [--force]
smb user enable <name>
smb user disable <name> [--force]
smb user passwd <name> [--password PASSWORD]
```

---

## Standalone binary

A self-contained Linux binary of `smb-tui` (built with PyInstaller) is available on the [Releases](../../releases) page — no Python installation required.

To build it yourself:

```bash
pip install pyinstaller textual
pyinstaller smb-tui.spec
# output: dist/smb-tui
```

---

## How config editing works

`smb_config.py` reads `smb.conf` as raw lines and tracks sections and parameters by line index. Edits are applied directly to the line list, so comments, blank lines, and indentation are preserved exactly. Disabled sections and parameters are represented by a leading `;` prefix — enabling/disabling toggles that prefix rather than deleting lines.

---

## License

MIT — see [LICENSE](LICENSE).
