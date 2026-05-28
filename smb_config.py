"""Samba smb.conf parser and manipulator with format preservation."""

import os
import re
import shutil
from datetime import datetime

SECTION_RE = re.compile(r'^[;#]?\s*\[(.+?)\]\s*$')
PARAM_RE = re.compile(r'^(\s*[;#]?\s*)([a-zA-Z_]\w*(?:\s+[a-zA-Z_]\w*){0,2})\s*[:=]\s*(.*)$')
COMMENT_RE = re.compile(r'^(\s*[#;])\s*(.*)$')
BLANK_RE = re.compile(r'^\s*$')


class SmbConfig:
    def __init__(self, path=None):
        self.path = path
        self.lines = []

    def load(self, path=None):
        if path:
            self.path = path
        if not self.path:
            raise ValueError("No config path specified")
        with open(self.path) as f:
            content = f.read()
        self.lines = content.splitlines(keepends=False)

    def save(self, dry_run=False):
        if dry_run:
            print(f"[dry-run] Would write to {self.path}:")
            for line in self.lines:
                print(line)
            return
        self._backup()
        content = '\n'.join(self.lines) + '\n'
        with open(self.path, 'w') as f:
            f.write(content)

    def _backup(self):
        if not os.path.exists(self.path):
            return
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        bak = f'{self.path}.bak.{ts}'
        shutil.copy2(self.path, bak)

    # --- Section queries ---

    def sections(self):
        """Return list of (name, enabled, line_idx) for all sections including [global]."""
        result = []
        for i, line in enumerate(self.lines):
            m = SECTION_RE.match(line)
            if m:
                name = m.group(1)
                enabled = not line.lstrip().startswith((';', '#'))
                result.append((name, enabled, i))
        return result

    def _find_section_bounds(self, name):
        """Return (header_idx, end_idx) for a section, or raise KeyError."""
        all_secs = self.sections()
        for sec_name, enabled, idx in all_secs:
            if sec_name == name:
                # find the next section header after this one
                end = len(self.lines)
                for _, _, nxt in all_secs:
                    if nxt > idx:
                        end = nxt
                        break
                return idx, end
        raise KeyError(f"Section [{name}] not found")

    def section_params(self, name):
        """Return ordered list of (key, value, line_idx, enabled) for a section."""
        start, end = self._find_section_bounds(name)
        params = []
        for i in range(start + 1, end):
            line = self.lines[i]
            m = PARAM_RE.match(line)
            if m:
                key = m.group(2).strip()
                value = m.group(3).strip()
                enabled = not m.group(1).lstrip().startswith((';', '#'))
                params.append((key, value, i, enabled))
        return params

    def get_param(self, section, key):
        key_lower = key.lower()
        for k, v, _, _ in self.section_params(section):
            if k.lower() == key_lower:
                return v
        raise KeyError(f"Parameter '{key}' not found in [{section}]")

    def _find_param_idx(self, section, key):
        key_lower = key.lower()
        for k, _, idx, _ in self.section_params(section):
            if k.lower() == key_lower:
                return idx
        return None

    # --- Section modifications ---

    def add_section(self, name):
        for sname, _, _ in self.sections():
            if sname == name:
                raise ValueError(f"Section [{name}] already exists")
        # Add blank line before new section if last line isn't blank
        if self.lines and self.lines[-1].strip():
            self.lines.append('')
        self.lines.append(f'[{name}]')

    def remove_section(self, name):
        start, end = self._find_section_bounds(name)
        # Remove trailing blank lines too
        while end < len(self.lines) and not self.lines[end].strip():
            end += 1
        del self.lines[start:end]
        # Clean up leading blank lines left behind
        while start > 0 and start <= len(self.lines) and not self.lines[start - 1].strip():
            del self.lines[start - 1]
            start -= 1

    def is_enabled(self, section):
        start, _ = self._find_section_bounds(section)
        line = self.lines[start]
        return not line.lstrip().startswith((';', '#'))

    def enable_section(self, name):
        start, end = self._find_section_bounds(name)
        self._toggle_section(start, end, enable=True)

    def disable_section(self, name):
        start, end = self._find_section_bounds(name)
        self._toggle_section(start, end, enable=False)

    def _toggle_section(self, start, end, enable):
        for i in range(start, end):
            line = self.lines[i]
            stripped = line.lstrip()
            if enable:
                # Remove leading ; or # from section headers and params
                if SECTION_RE.match(line) or PARAM_RE.match(line):
                    if stripped.startswith(';'):
                        self.lines[i] = line.replace(';', '', 1)
                    elif stripped.startswith('#'):
                        self.lines[i] = line.replace('#', '', 1)
            else:
                # Add ; before section headers and params
                if SECTION_RE.match(line):
                    self.lines[i] = ';' + line
                elif PARAM_RE.match(line):
                    m = PARAM_RE.match(line)
                    if m and not m.group(1).lstrip().startswith((';', '#')):
                        ws = m.group(1)
                        rest = line[len(ws):]
                        self.lines[i] = ws + ';' + rest

    # --- Parameter modifications ---

    def set_param(self, section, key, value):
        start, end = self._find_section_bounds(section)
        idx = self._find_param_idx(section, key)

        if idx is not None:
            # Update existing param, preserving indentation
            line = self.lines[idx]
            m = PARAM_RE.match(line)
            prefix = m.group(1)
            sep = '=' if '=' in line else ':'
            rest = line[m.end():]
            self.lines[idx] = f'{prefix}{key} {sep} {value}{rest}'
        else:
            # Add new param at end of section
            indent = self._section_indent(start, end)
            self.lines.insert(end, f'{indent}{key} = {value}')

    def remove_param(self, section, key):
        idx = self._find_param_idx(section, key)
        if idx is None:
            raise KeyError(f"Parameter '{key}' not found in [{section}]")
        del self.lines[idx]

    def _section_indent(self, start, end):
        """Determine the indentation used by existing params in this section."""
        for i in range(start + 1, end):
            m = PARAM_RE.match(self.lines[i])
            if m:
                indent = m.group(1)
                # Return the non-comment-prefix part of the indentation
                stripped = indent.lstrip()
                if stripped.startswith((';', '#')):
                    return indent.replace(stripped[0], '', 1)
                return indent
        return '   '  # default: 3 spaces
