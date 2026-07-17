#!/usr/bin/env python3
"""探测真实注册表中的右键菜单项目。

用 winreg 从真实注册表提取并打印所有右键菜单项目及其信息，
验证哪些能提取出来。探测目标见模块级 TARGETS。

运行：python scripts/probe_menus.py
"""
from __future__ import annotations

import os
import sys
import winreg

HKCR = winreg.HKEY_CLASSES_ROOT
HKCU = winreg.HKEY_CURRENT_USER
# 64 位视图，避免 32/64 位重定向漏看键
KEY_READ_64 = winreg.KEY_READ | winreg.KEY_WOW64_64KEY

# (标签, 静态命令根, Shell 扩展根)
TARGETS: list[tuple[str, str, str]] = [
    ("文件（所有文件 *）", r"*\shell", r"*\shellex\ContextMenuHandlers"),
    ("文件夹", r"Directory\shell", r"Directory\shellex\ContextMenuHandlers"),
    ("桌面/背景", r"Directory\Background\shell",
     r"Directory\Background\shellex\ContextMenuHandlers"),
    ("驱动器", r"Drive\shell", r"Drive\shellex\ContextMenuHandlers"),
    ("所有文件系统对象", r"AllFilesystemObjects\shell",
     r"AllFilesystemObjects\shellex\ContextMenuHandlers"),
]


# ── 底层读取工具 ──────────────────────────────────────────────
def open_key(root, path: str, access: int = KEY_READ_64):
    """打开键，不存在或被拒返回 None。"""
    try:
        return winreg.OpenKey(root, path, 0, access)
    except FileNotFoundError:
        return None
    except PermissionError:
        return None
    except OSError:
        return None


def enum_subkeys(key) -> list[str]:
    """枚举所有子键名。"""
    names: list[str] = []
    i = 0
    while True:
        try:
            names.append(winreg.EnumKey(key, i))
            i += 1
        except OSError:
            break
    return names


def query_value(key, name: str | None = None):
    """查询单个值，不存在返回 None。name=None 查默认值。"""
    try:
        val, _typ = winreg.QueryValueEx(key, name)
        return val
    except FileNotFoundError:
        return None
    except OSError:
        return None


def has_value(key, name: str | None = None) -> bool:
    """判断某个值是否存在。"""
    try:
        winreg.QueryValueEx(key, name)
        return True
    except OSError:
        return False


def resolve_scope(rel_path: str) -> str:
    r"""判定作用域：HKCU\Software\Classes\<rel> 存在则 USER，否则 SYSTEM。"""
    cu = open_key(HKCU, r"Software\Classes\\" + rel_path)
    if cu is not None:
        winreg.CloseKey(cu)
        return "USER(可编辑)"
    return "SYSTEM(只读)"


# ── 静态命令解析 ──────────────────────────────────────────────
def parse_static_entry(root, base: str, name: str, depth: int = 0) -> dict:
    r"""解析 shell\<name> 一个静态命令项（含级联递归）。"""
    entry_path = base + "\\" + name
    key = open_key(root, entry_path)
    info: dict = {
        "name": name,
        "path": "HKCR\\" + entry_path,
        "scope": resolve_scope(entry_path),
        "default": None,
        "muiverb": None,
        "icon": None,
        "position": None,
        "extended": False,
        "subcommands": None,
        "legacy_disabled": False,
        "command": None,
        "children": [],
        "has_shell_subkey": False,
    }
    if key is None:
        info["error"] = "无法打开键"
        return info

    info["default"] = query_value(key)  # 默认值
    info["muiverb"] = query_value(key, "MUIVerb")
    info["icon"] = query_value(key, "Icon")
    info["position"] = query_value(key, "Position")
    info["extended"] = has_value(key, "Extended")
    info["subcommands"] = query_value(key, "SubCommands")
    info["legacy_disabled"] = has_value(key, "LegacyDisable")

    # command 子键
    cmd_key = open_key(root, entry_path + "\\command")
    if cmd_key is not None:
        info["command"] = query_value(cmd_key)
        winreg.CloseKey(cmd_key)

    # 级联：检查是否有 shell 子键
    shell_sub = open_key(root, entry_path + "\\shell")
    if shell_sub is not None:
        info["has_shell_subkey"] = True
        for child_name in enum_subkeys(shell_sub):
            child = parse_static_entry(root, entry_path + "\\shell", child_name,
                                       depth + 1)
            info["children"].append(child)
        winreg.CloseKey(shell_sub)

    winreg.CloseKey(key)
    return info


def print_static_entry(info: dict, indent: int = 0) -> None:
    pad = "  " * indent
    disp = info.get("muiverb") or info.get("default") or info["name"]
    kind = "CASCADE" if info.get("has_shell_subkey") or info.get("subcommands") \
        else "COMMAND"
    if info.get("legacy_disabled"):
        kind += "(已禁用)"
    print(f"{pad}- [{kind}] {disp}  [{info['scope']}]")
    print(f"{pad}    键名: {info['name']}")
    print(f"{pad}    路径: {info['path']}")
    if info.get("default"):
        print(f"{pad}    默认值: {info['default']}")
    if info.get("muiverb"):
        print(f"{pad}    MUIVerb: {info['muiverb']}")
    if info.get("icon"):
        print(f"{pad}    Icon: {info['icon']}")
    if info.get("position"):
        print(f"{pad}    Position: {info['position']}")
    if info.get("extended"):
        print(f"{pad}    Extended: 是 (Shift+右键)")
    if info.get("subcommands"):
        print(f"{pad}    SubCommands: {info['subcommands']}")
    if info.get("command"):
        print(f"{pad}    command: {info['command']}")
    for child in info.get("children", []):
        print_static_entry(child, indent + 1)


# ── Shell 扩展解析 ────────────────────────────────────────────
def parse_shellex(root, base: str, name: str) -> dict:
    r"""解析 shellex\ContextMenuHandlers\<name>。"""
    entry_path = base + "\\" + name
    key = open_key(root, entry_path)
    info: dict = {
        "name": name,
        "path": "HKCR\\" + entry_path,
        "scope": resolve_scope(entry_path),
        "clsid": None,
    }
    if key is not None:
        info["clsid"] = query_value(key)  # 默认值通常是 CLSID
        winreg.CloseKey(key)
    return info


# ── 文件类型遍历 ─────────────────────────────────────────────
def probe_filetypes() -> None:
    """遍历 HKCR 下 . 开头的键，取 ProgID 再查 shell。"""
    print("\n" + "=" * 70)
    print("文件类型（HKCR\\.<ext> -> ProgID -> shell）")
    print("=" * 70)
    root = open_key(HKCR, "")
    if root is None:
        print("  无法打开 HKCR 根")
        return
    count = 0
    found = 0
    for sub in enum_subkeys(root):
        if not sub.startswith("."):
            continue
        count += 1
        ext_key = open_key(HKCR, sub)
        if ext_key is None:
            continue
        progid = query_value(ext_key)  # 默认值 = ProgID
        winreg.CloseKey(ext_key)
        if not progid:
            continue
        shell_key = open_key(HKCR, progid + "\\shell")
        if shell_key is None:
            continue
        verbs = enum_subkeys(shell_key)
        winreg.CloseKey(shell_key)
        if not verbs:
            continue
        found += 1
        print(f"\n  {sub} -> ProgID={progid}  ({len(verbs)} 个动词)")
        for v in verbs:
            child = parse_static_entry(HKCR, progid + "\\shell", v)
            print_static_entry(child, indent=2)
        if found >= 30:
            print(f"\n  ... (已展示 {found} 个有 shell 的文件类型，"
                  f"共扫描 {count} 个扩展名，停止)")
            break
    winreg.CloseKey(root)
    print(f"\n  扫描了 {count} 个扩展名，其中 {found} 个有自定义 shell 动词")


# ── 主流程 ───────────────────────────────────────────────────
def probe_target(label: str, shell_path: str, shellex_path: str) -> None:
    print("\n" + "=" * 70)
    print(f"场景：{label}")
    print(f"  静态命令: HKCR\\{shell_path}")
    print(f"  Shell 扩展: HKCR\\{shellex_path}")
    print("=" * 70)

    # 静态命令
    shell_key = open_key(HKCR, shell_path)
    if shell_key is None:
        print("  [静态命令] 无此键或无法访问")
    else:
        names = enum_subkeys(shell_key)
        print(f"  [静态命令] {len(names)} 个子键")
        for n in names:
            try:
                info = parse_static_entry(HKCR, shell_path, n)
                print_static_entry(info, indent=1)
            except Exception as e:  # 单键出错不崩
                print(f"  - [错误] {n}: {e}", file=sys.stderr)
        winreg.CloseKey(shell_key)

    # Shell 扩展
    shellex_key = open_key(HKCR, shellex_path)
    if shellex_key is None:
        print("  [Shell 扩展] 无此键或无法访问")
    else:
        names = enum_subkeys(shellex_key)
        print(f"  [Shell 扩展] {len(names)} 个子键")
        for n in names:
            info = parse_shellex(HKCR, shellex_path, n)
            clsid = info["clsid"] or "(无默认值)"
            print(f"  - [SHELLEX] {info['name']}  CLSID={clsid}  [{info['scope']}]")
            print(f"      路径: {info['path']}")
        winreg.CloseKey(shellex_key)


def main() -> None:
    print("右键菜单注册表探测")
    print(f"Python {sys.version}")
    print(f"os={os.name}")

    # 检查 HKCU\Software\Classes 是否可写（探测可编辑性）
    cu_test = open_key(HKCU, r"Software\Classes", KEY_READ_64)
    print(f"HKCU\\Software\\Classes 可读: {cu_test is not None}")
    if cu_test is not None:
        winreg.CloseKey(cu_test)

    for label, shell_path, shellex_path in TARGETS:
        try:
            probe_target(label, shell_path, shellex_path)
        except Exception as e:
            print(f"  [场景错误] {label}: {e}", file=sys.stderr)

    try:
        probe_filetypes()
    except Exception as e:
        print(f"  [文件类型错误] {e}", file=sys.stderr)

    print("\n探测完成。")


if __name__ == "__main__":
    main()
