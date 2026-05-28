# smb-tui

基于终端的 Samba（`smb.conf`）配置与用户管理工具。

提供两种使用方式：

- **`smb-tui`** — 交互式 TUI（基于 [Textual](https://github.com/Textualize/textual)）
- **`smb`** — 非交互式 CLI，适合脚本调用

两种工具均直接编辑 `smb.conf`，同时保留注释、缩进和原始格式。每次写入前自动创建带时间戳的备份。

---

## 环境要求

- Python 3.10+
- Samba（`smbpasswd`、`pdbedit`、`testparm`）
- [Textual](https://github.com/Textualize/textual)（仅 TUI 需要）

```
pip install textual
```

---

## TUI — `smb_tui.py`

```
python smb_tui.py [--config /path/to/smb.conf] [--dry-run]
```

### 快捷键

**主界面（共享列表）**

| 按键 | 操作 |
|------|------|
| `Enter` | 查看共享详情 |
| `a` | 添加共享 |
| `E` | 编辑共享 |
| `e` | 启用共享 |
| `d` | 禁用共享 |
| `Ctrl+D` | 删除共享 |
| `u` | 管理用户 |
| `v` | 验证配置（`testparm`） |
| `b` | 备份配置 |
| `r` | 从磁盘重新加载配置 |
| `Ctrl+S` / `s` | 保存 |
| `Ctrl+Q` | 退出 |

**共享详情界面**

| 按键 | 操作 |
|------|------|
| `a` | 添加参数 |
| `e` | 编辑参数 |
| `Ctrl+D` | 删除参数 |
| `t` | 切换启用/禁用 |
| `Esc` | 返回 |

**用户列表界面**

| 按键 | 操作 |
|------|------|
| `a` | 添加用户 |
| `Ctrl+D` | 删除用户 |
| `e` | 启用用户 |
| `d` | 禁用用户 |
| `p` | 修改密码 |
| `Esc` | 返回 |

若配置文件需要 root 权限，TUI 会在会话开始时提示输入 sudo 密码并缓存，后续操作无需重复输入。

---

## CLI — `smb_cli.py`

```
python smb_cli.py [--config /path/to/smb.conf] [--dry-run] COMMAND
```

### 共享管理

```bash
# 列出所有共享
smb list

# 查看共享的所有参数
smb show <名称>

# 添加共享
smb add <名称> <路径> [--comment 描述] [--guest-ok yes|no]
        [--read-only yes|no] [--browseable yes|no]
        [--create-mask 掩码] [--directory-mask 掩码]
        [--valid-users user1,user2] [--write-list user1,user2]

# 删除共享
smb remove <名称> [--force]

# 设置 / 删除参数
smb set <名称> <键> <值>
smb unset <名称> <键>

# 启用 / 禁用共享
smb enable <名称>
smb disable <名称> [--force]

# 验证配置语法
smb validate

# 创建带时间戳的备份
smb backup
```

### 用户管理

```bash
smb user list [--verbose]
smb user add <用户名> [--password 密码]
smb user remove <用户名> [--force]
smb user enable <用户名>
smb user disable <用户名> [--force]
smb user passwd <用户名> [--password 密码]
```

---

## 独立二进制文件

[Releases](../../releases) 页面提供通过 PyInstaller 打包的 Linux 独立可执行文件，无需安装 Python。

自行构建：

```bash
pip install pyinstaller textual
pyinstaller smb-tui.spec
# 输出：dist/smb-tui
```

---

## 配置编辑原理

`smb_config.py` 将 `smb.conf` 以原始行的形式读入内存，通过行索引追踪各节和参数。编辑操作直接作用于行列表，因此注释、空行和缩进均原样保留。禁用的节和参数以行首 `;` 前缀表示，启用/禁用操作只是切换该前缀，不会删除任何行。

---

## 许可证

MIT — 详见 [LICENSE](LICENSE)。
