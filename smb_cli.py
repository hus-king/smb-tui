#!/usr/bin/env python3
"""smb - Samba configuration file management CLI."""

import argparse
import getpass
import os
import subprocess
import sys

from smb_config import SmbConfig
from smb_users import SmbUserManager

DEFAULT_CONFIG = '/etc/samba/smb.conf'

KEY_PARAMS = ['path', 'comment', 'guest ok', 'read only', 'browseable',
              'valid users', 'write list', 'create mask', 'directory mask']


def confirm(msg):
    answer = input(f'{msg} [y/N] ').strip().lower()
    return answer in ('y', 'yes')


def main():
    parser = argparse.ArgumentParser(
        prog='smb',
        description='Manage Samba (smb.conf) configuration files.')
    parser.add_argument('--config', '-c', default=DEFAULT_CONFIG,
                        help=f'Path to smb.conf (default: {DEFAULT_CONFIG})')
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help='Show what would be done without writing')

    sub = parser.add_subparsers(dest='command', metavar='COMMAND')
    sub.required = True

    # list
    sub.add_parser('list', help='List all shares and their key parameters')

    # show
    p_show = sub.add_parser('show', help='Show full configuration of a share')
    p_show.add_argument('name', help='Share name')

    # add
    p_add = sub.add_parser('add', help='Add a new share')
    p_add.add_argument('name', help='Share name')
    p_add.add_argument('path', help='Directory path to share')
    p_add.add_argument('--comment', '-C', help='Share description')
    p_add.add_argument('--guest-ok', choices=['yes', 'no'], default=None)
    p_add.add_argument('--read-only', choices=['yes', 'no'], default=None)
    p_add.add_argument('--browseable', choices=['yes', 'no'], default=None)
    p_add.add_argument('--create-mask', help='File creation mask (e.g. 0700)')
    p_add.add_argument('--directory-mask', help='Directory creation mask (e.g. 0700)')
    p_add.add_argument('--valid-users', help='Comma-separated list of valid users')
    p_add.add_argument('--write-list', help='Comma-separated list of users with write access')

    # remove
    p_remove = sub.add_parser('remove', aliases=['rm'], help='Remove a share')
    p_remove.add_argument('name', help='Share name')
    p_remove.add_argument('--force', '-f', action='store_true',
                          help='Skip confirmation')

    # set
    p_set = sub.add_parser('set', help='Set a parameter on a share')
    p_set.add_argument('name', help='Share name')
    p_set.add_argument('key', help='Parameter name')
    p_set.add_argument('value', help='Parameter value')

    # unset
    p_unset = sub.add_parser('unset', help='Remove a parameter from a share')
    p_unset.add_argument('name', help='Share name')
    p_unset.add_argument('key', help='Parameter name')

    # enable
    p_enable = sub.add_parser('enable', help='Enable a disabled share')
    p_enable.add_argument('name', help='Share name')

    # disable
    p_disable = sub.add_parser('disable', help='Disable a share')
    p_disable.add_argument('name', help='Share name')
    p_disable.add_argument('--force', '-f', action='store_true',
                           help='Skip confirmation')

    # validate
    sub.add_parser('validate', help='Run testparm to check configuration syntax')

    # backup
    sub.add_parser('backup', help='Create a timestamped backup of the config file')

    # user
    p_user = sub.add_parser('user', help='Manage Samba users')
    user_sub = p_user.add_subparsers(dest='user_command', metavar='ACTION')
    user_sub.required = True

    p_ulist = user_sub.add_parser('list', help='List all Samba users')
    p_ulist.add_argument('--verbose', '-v', action='store_true')

    p_uadd = user_sub.add_parser('add', help='Add a Samba user')
    p_uadd.add_argument('name', help='Username')
    p_uadd.add_argument('--password', '-p', help='Password (will prompt if omitted)')

    p_urm = user_sub.add_parser('remove', aliases=['rm'], help='Remove a Samba user')
    p_urm.add_argument('name', help='Username')
    p_urm.add_argument('--force', '-f', action='store_true', help='Skip confirmation')

    p_uen = user_sub.add_parser('enable', help='Enable a Samba user')
    p_uen.add_argument('name', help='Username')

    p_udis = user_sub.add_parser('disable', help='Disable a Samba user')
    p_udis.add_argument('name', help='Username')
    p_udis.add_argument('--force', '-f', action='store_true', help='Skip confirmation')

    p_upw = user_sub.add_parser('passwd', help='Change a Samba user password')
    p_upw.add_argument('name', help='Username')
    p_upw.add_argument('--password', '-p', help='New password (will prompt if omitted)')

    args = parser.parse_args()
    cfg = SmbConfig()
    cfg.load(args.config)

    cmd = args.command

    if cmd == 'list':
        cmd_list(cfg)

    elif cmd == 'show':
        cmd_show(cfg, args.name)

    elif cmd == 'add':
        cmd_add(cfg, args)
        cfg.save(dry_run=args.dry_run)

    elif cmd in ('remove', 'rm'):
        if not args.force and not confirm(f'Remove share [{args.name}]?'):
            sys.exit(0)
        cmd_remove(cfg, args.name)
        cfg.save(dry_run=args.dry_run)

    elif cmd == 'set':
        cmd_set(cfg, args.name, args.key, args.value)
        cfg.save(dry_run=args.dry_run)

    elif cmd == 'unset':
        cmd_unset(cfg, args.name, args.key)
        cfg.save(dry_run=args.dry_run)

    elif cmd == 'enable':
        cmd_enable(cfg, args.name)
        cfg.save(dry_run=args.dry_run)

    elif cmd == 'disable':
        if not args.force and not confirm(f'Disable share [{args.name}]?'):
            sys.exit(0)
        cmd_disable(cfg, args.name)
        cfg.save(dry_run=args.dry_run)

    elif cmd == 'validate':
        cmd_validate(args.config)

    elif cmd == 'backup':
        cmd_backup(args.config, dry_run=args.dry_run)

    elif cmd == 'user':
        cmd_user(args)


# --- Command implementations ---

def cmd_list(cfg):
    sections = cfg.sections()
    if not sections:
        print("No shares defined.")
        return
    print(f"{'SHARE':<20} {'ENABLED':<8} {'PATH':<30} {'COMMENT'}")
    print('-' * 80)
    for name, enabled, _ in sections:
        path = ''
        comment = ''
        try:
            path = cfg.get_param(name, 'path')
        except KeyError:
            pass
        try:
            comment = cfg.get_param(name, 'comment')
        except KeyError:
            pass
        enabled_str = 'yes' if enabled else 'no'
        print(f'{name:<20} {enabled_str:<8} {path:<30} {comment}')


def cmd_show(cfg, name):
    try:
        enabled = cfg.is_enabled(name)
    except KeyError:
        print(f"Share [{name}] not found.", file=sys.stderr)
        sys.exit(1)

    enabled_str = 'yes' if enabled else 'no'
    print(f'[{name}]  (enabled: {enabled_str})')
    params = cfg.section_params(name)
    if not params:
        print('  (no parameters)')
    else:
        max_key = max(len(k) for k, _, _, _ in params) if params else 0
        for key, value, _, param_enabled in params:
            status = ' ' if param_enabled else 'D'
            print(f'  {status} {key:<{max_key}} = {value}')


def cmd_add(cfg, args):
    try:
        cfg.add_section(args.name)
    except ValueError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    cfg.set_param(args.name, 'path', args.path)
    if args.comment:
        cfg.set_param(args.name, 'comment', args.comment)
    for opt in ['guest_ok', 'read_only', 'browseable']:
        val = getattr(args, opt)
        if val is not None:
            cfg.set_param(args.name, opt.replace('_', ' '), val)
    if args.create_mask:
        cfg.set_param(args.name, 'create mask', args.create_mask)
    if args.directory_mask:
        cfg.set_param(args.name, 'directory mask', args.directory_mask)
    if args.valid_users:
        cfg.set_param(args.name, 'valid users', args.valid_users)
    if args.write_list:
        cfg.set_param(args.name, 'write list', args.write_list)

    print(f"Share [{args.name}] added.")


def cmd_remove(cfg, name):
    try:
        cfg.remove_section(name)
    except KeyError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    print(f"Share [{name}] removed.")


def cmd_set(cfg, name, key, value):
    try:
        cfg.set_param(name, key, value)
    except KeyError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    print(f"[{name}] {key} = {value}")


def cmd_unset(cfg, name, key):
    try:
        cfg.remove_param(name, key)
    except KeyError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    print(f"[{name}] removed '{key}'.")


def cmd_enable(cfg, name):
    if cfg.is_enabled(name):
        print(f"Share [{name}] is already enabled.")
        return
    cfg.enable_section(name)
    print(f"Share [{name}] enabled.")


def cmd_disable(cfg, name):
    if not cfg.is_enabled(name):
        print(f"Share [{name}] is already disabled.")
        return
    cfg.disable_section(name)
    print(f"Share [{name}] disabled.")


def cmd_validate(config_path):
    if not os.path.exists(config_path):
        print(f"Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    try:
        result = subprocess.run(['testparm', '-s', config_path],
                                capture_output=True, text=True)
        if result.returncode == 0:
            print("Configuration OK.")
        else:
            print(result.stderr or result.stdout)
    except FileNotFoundError:
        print("testparm not found. Is samba installed?", file=sys.stderr)
        sys.exit(1)


def cmd_backup(config_path, dry_run=False):
    ts = __import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = f'{config_path}.bak.{ts}'
    if dry_run:
        print(f"[dry-run] Would backup {config_path} -> {bak}")
        return
    if not os.path.exists(config_path):
        print(f"Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    import shutil
    shutil.copy2(config_path, bak)
    print(f"Backed up to {bak}")


def cmd_user(args):
    ucmd = args.user_command

    if ucmd == 'list':
        cmd_user_list(args.verbose)

    elif ucmd == 'add':
        password = args.password
        if password is None:
            password = getpass.getpass(f"New SMB password for {args.name}: ")
            confirm = getpass.getpass("Retype new SMB password: ")
            if password != confirm:
                print("Passwords do not match.", file=sys.stderr)
                sys.exit(1)
        ok, msg = SmbUserManager.add_user(args.name, password)
        print(msg)
        if not ok:
            sys.exit(1)

    elif ucmd in ('remove', 'rm'):
        if not args.force and not confirm(f'Remove Samba user [{args.name}]?'):
            sys.exit(0)
        ok, msg = SmbUserManager.remove_user(args.name)
        print(msg)
        if not ok:
            sys.exit(1)

    elif ucmd == 'enable':
        ok, msg = SmbUserManager.enable_user(args.name)
        print(msg)
        if not ok:
            sys.exit(1)

    elif ucmd == 'disable':
        if not args.force and not confirm(f'Disable Samba user [{args.name}]?'):
            sys.exit(0)
        ok, msg = SmbUserManager.disable_user(args.name)
        print(msg)
        if not ok:
            sys.exit(1)

    elif ucmd == 'passwd':
        password = args.password
        if password is None:
            password = getpass.getpass(f"New SMB password for {args.name}: ")
            confirm = getpass.getpass("Retype new SMB password: ")
            if password != confirm:
                print("Passwords do not match.", file=sys.stderr)
                sys.exit(1)
        ok, msg = SmbUserManager.change_password(args.name, password)
        print(msg)
        if not ok:
            sys.exit(1)


def cmd_user_list(verbose=False):
    users = SmbUserManager.list_users(verbose=verbose)
    if not users:
        print("No Samba users found.")
        return
    if verbose:
        for u in users:
            flags = u.get("flags", "")
            home = u.get("home", "")
            sid = u.get("sid", "")
            print(f"{u['name']:<20}  flags: {flags}")
            print(f"  SID: {sid}")
            print(f"  Full Name: {u.get('fullname', '')}")
            if home:
                print(f"  Home: {home}")
            print()
    else:
        print(f"{'USER':<20} {'UID':<8} {'FULL NAME'}")
        print("-" * 50)
        for u in users:
            print(f"{u['name']:<20} {u.get('uid', ''):<8} {u.get('fullname', '')}")


if __name__ == '__main__':
    main()
