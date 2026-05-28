"""Samba user management via smbpasswd and pdbedit."""

import subprocess
import sys


def _run(cmd, stdin=None, use_sudo=False):
    """Run a command, return (returncode, stdout, stderr).
    If use_sudo is True, prepend sudo (assumes sudo timestamp already cached)."""
    if use_sudo:
        cmd = ["sudo"] + cmd

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            input=stdin,
            timeout=30,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}. Is samba installed?"
    except subprocess.TimeoutExpired:
        return -2, "", "Command timed out."


class SmbUserManager:
    """Manage Samba users via smbpasswd / pdbedit.
    Set use_sudo=True to run commands with sudo (requires cached timestamp)."""

    @staticmethod
    def list_users(verbose=False, use_sudo=False):
        """Return list of dicts with keys: name, uid, fullname, [flags, home, ... if verbose]."""
        if verbose:
            return SmbUserManager._list_verbose(use_sudo)
        rc, out, err = _run(["pdbedit", "-L"], use_sudo=use_sudo)
        if rc != 0:
            return []
        users = []
        for line in out.strip().splitlines():
            parts = line.split(":")
            if len(parts) >= 3:
                users.append({
                    "name": parts[0],
                    "uid": parts[1],
                    "fullname": parts[2],
                })
        return users

    @staticmethod
    def _list_verbose(use_sudo=False):
        rc, out, err = _run(["pdbedit", "-L", "-v"], use_sudo=use_sudo)
        if rc != 0:
            return []
        users = []
        current = {}
        for line in out.strip().splitlines():
            if line.startswith("---"):
                if current:
                    users.append(current)
                    current = {}
                continue
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                if key == "Unix username":
                    current["name"] = value
                elif key == "User SID":
                    current["sid"] = value
                elif key == "Full Name":
                    current["fullname"] = value
                elif key == "Account Flags":
                    current["flags"] = value
                elif key == "Home Directory":
                    current["home"] = value
        if current:
            users.append(current)
        return users

    @staticmethod
    def user_info(username, use_sudo=False):
        """Get detailed info for a single user."""
        rc, out, err = _run(
            ["pdbedit", "-L", "-v", username], use_sudo=use_sudo
        )
        if rc != 0:
            return None
        info = {}
        for line in out.strip().splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                if key == "Unix username":
                    info["name"] = value
                elif key == "User SID":
                    info["sid"] = value
                elif key == "Full Name":
                    info["fullname"] = value
                elif key == "Account Flags":
                    info["flags"] = value
                elif key == "Home Directory":
                    info["home"] = value
        return info

    @staticmethod
    def add_user(username, password=None, use_sudo=False):
        """Add a new Samba user. Requires the Unix user to exist first.
        Returns (ok, message)."""
        try:
            import pwd
            pwd.getpwnam(username)
        except KeyError:
            return False, f"System user '{username}' does not exist. Create it first with: sudo useradd {username}"
        except ImportError:
            pass

        cmd = ["smbpasswd", "-a", username]
        if password is not None:
            stdin = f"{password}\n{password}\n"
        else:
            return False, "Password required (non-interactive mode)."
        rc, out, err = _run(cmd, stdin=stdin, use_sudo=use_sudo)
        if rc == 0:
            return True, f"User '{username}' added."
        else:
            return False, err or out

    @staticmethod
    def remove_user(username, use_sudo=False):
        """Remove a Samba user. Returns (ok, message)."""
        rc, out, err = _run(
            ["smbpasswd", "-x", username], use_sudo=use_sudo
        )
        if rc == 0:
            return True, f"User '{username}' removed."
        return False, err or out

    @staticmethod
    def enable_user(username, use_sudo=False):
        """Enable a disabled Samba user. Returns (ok, message)."""
        rc, out, err = _run(
            ["smbpasswd", "-e", username], use_sudo=use_sudo
        )
        if rc == 0:
            return True, f"User '{username}' enabled."
        return False, err or out

    @staticmethod
    def disable_user(username, use_sudo=False):
        """Disable a Samba user. Returns (ok, message)."""
        rc, out, err = _run(
            ["smbpasswd", "-d", username], use_sudo=use_sudo
        )
        if rc == 0:
            return True, f"User '{username}' disabled."
        return False, err or out

    @staticmethod
    def change_password(username, password, use_sudo=False):
        """Change a Samba user's password. Returns (ok, message)."""
        cmd = ["smbpasswd", username]
        stdin = f"{password}\n{password}\n"
        rc, out, err = _run(cmd, stdin=stdin, use_sudo=use_sudo)
        if rc == 0:
            return True, f"Password changed for '{username}'."
        return False, err or out
