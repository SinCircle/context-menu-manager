r"""注册表读写层 - 纯 winreg 实现。

读取统一用 HKCR（合并视图）；可编辑性由 resolve_scope 判定
（HKCU\Software\Classes\<相对路径> 存在则为 USER，否则 SYSTEM 只读）。

写入按 scope 路由：
- ``Scope.USER`` -> 写 ``HKCU\Software\Classes\...``（无需管理员）。
- ``Scope.SYSTEM`` -> 写 ``HKLM\SOFTWARE\Classes\...``（需管理员；未提权抛
  ``PermissionDeniedError``）。用 ``elevation.is_admin()`` 判定。

屏蔽/启用：
- COMMAND/CASCADE：在对应 verb 键设/删 ``LegacyDisable`` 值（空字符串）。
  按 scope 路由 HKCU/HKLM。
- SHELLEX：把 ``entry.clsid`` 作为值名写入/删除 ``Shell Extensions\Blocked``
  键（HKLM 与 HKCU 两处都写/都删，值数据为空串）。

新场景读取：NEW（ShellNew）/ SENDTO（发送到）/ OPENWITH（打开方式）/ WINX
（CommandStore\shell）。单键出错跳过并在 stderr 记录，不整体崩溃。

key_path 约定：以 "HKCR\<相对路径>" 形式存储（与 stub 一致）；WINX 等不在
Classes 树下的用 "HKLM\..." 形式；SENDTO 用文件路径。
Shell 扩展（SHELLEX）只读，不可创建/编辑/删除其 CLSID。
"""
from __future__ import annotations

import os
import re
import sys
import winreg

from . import elevation
from .model import EntryKind, MenuEntry, Scope, TargetContext

# ── 注册表常量 ────────────────────────────────────────────────
HKCR = winreg.HKEY_CLASSES_ROOT
HKCU = winreg.HKEY_CURRENT_USER
HKLM = winreg.HKEY_LOCAL_MACHINE
KEY_READ_64 = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
KEY_WRITE_64 = (winreg.KEY_SET_VALUE | winreg.KEY_CREATE_SUB_KEY
                | winreg.KEY_WOW64_64KEY)

# target -> 静态命令根（相对 HKCR）
_TARGET_SHELL_PATH: dict[TargetContext, str] = {
    TargetContext.FILES: r"*\shell",
    TargetContext.DIRECTORY: r"Directory\shell",
    TargetContext.DIRECTORY_BACKGROUND: r"Directory\Background\shell",
    TargetContext.DRIVE: r"Drive\shell",
    TargetContext.ALLFILESYSTEMOBJECTS: r"AllFilesystemObjects\shell",
}

# Shell Extensions\Blocked 路径（HKLM + HKCU 两处都写）
_HKLM_BLOCKED = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Shell Extensions\Blocked"
_HKCU_BLOCKED = r"Software\Microsoft\Windows\CurrentVersion\Shell Extensions\Blocked"

# WinX 命令存储：CommandStore\shell 下的命令项
_WINX_STORE = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\CommandStore\shell"

# ShellNew 生效值名（任一存在即视为有效 ShellNew 项）
_SHELLNEW_EFFECT_VALUES = ("NullFile", "Data", "FileName", "Directory",
                           "Command")

# SendTo 目录
_SENDTO_DIR = os.path.join(os.environ.get("APPDATA", ""),
                           "Microsoft", "Windows", "SendTo")

_CLSID_RE = re.compile(r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
                        r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$")


# ── 异常类型（UI 层据此做友好提示）──────────────────────────────
class RegistryError(Exception):
    """注册表操作基础异常。"""


class KeyNotFoundError(RegistryError):
    """键不存在。"""


class PermissionDeniedError(RegistryError):
    """访问被拒（多为系统键）。"""


class ParseError(RegistryError):
    """解析注册表值失败。"""


# ── 底层读取工具 ──────────────────────────────────────────────
def _open_key(root, path: str, access: int = KEY_READ_64):
    """打开键；不存在或被拒返回 None（不抛异常）。"""
    try:
        return winreg.OpenKey(root, path, 0, access)
    except FileNotFoundError:
        return None
    except PermissionError:
        return None
    except OSError:
        return None


def _enum_subkeys(key) -> list[str]:
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


def _enum_values(key) -> list[tuple[str, object, int]]:
    """枚举所有值：(name, data, type)。"""
    out: list[tuple[str, object, int]] = []
    i = 0
    while True:
        try:
            out.append(winreg.EnumValue(key, i))
            i += 1
        except OSError:
            break
    return out


def _query_value(key, name: str | None = None):
    """查询单个值；不存在返回 None。name=None 查默认值。"""
    try:
        val, _typ = winreg.QueryValueEx(key, name)
        return val
    except FileNotFoundError:
        return None
    except OSError:
        return None


def _has_value(key, name: str | None = None) -> bool:
    """判断某个值是否存在。"""
    try:
        winreg.QueryValueEx(key, name)
        return True
    except OSError:
        return False


def _looks_like_clsid(s) -> bool:
    return bool(s) and _CLSID_RE.match(s.strip()) is not None


# ── 路径工具 ──────────────────────────────────────────────────
def _normalize_rel(key_path: str) -> str:
    r"""把 key_path 转为相对 HKCR\Software\Classes 的路径。

    支持 "HKCR\..." / "HKCU\Software\Classes\..." / "HKLM\Software\Classes\..."。
    其他形式（如 "HKLM\SOFTWARE\Microsoft\..." 或文件路径）原样返回。
    """
    for prefix in ("HKCR\\", "HKCU\\Software\\Classes\\",
                   "HKLM\\Software\\Classes\\", "HKLM\\SOFTWARE\\Classes\\"):
        if key_path.startswith(prefix):
            return key_path[len(prefix):]
    return key_path


def _get_progid(ext: str | None) -> str | None:
    r"""返回扩展名对应的 ProgID（HKCR\<ext> 默认值）。"""
    if not ext:
        return None
    if not ext.startswith("."):
        ext = "." + ext
    key = _open_key(HKCR, ext)
    if key is None:
        return None
    progid = _query_value(key)
    winreg.CloseKey(key)
    return progid or None


def _shell_rel_path(target: TargetContext,
                    file_type_ext: str | None) -> str:
    r"""返回 target 对应的 shell 相对路径（如 *\shell / Directory\shell）。

    新场景（NEW/SENDTO/OPENWITH/WINX）不走此函数，由各自读取器处理。
    """
    if target is TargetContext.FILETYPE:
        if not file_type_ext:
            raise ValueError("FILETYPE 目标需要 file_type_ext")
        progid = _get_progid(file_type_ext)
        if not progid:
            raise KeyNotFoundError(
                f"无法解析 {file_type_ext} 的 ProgID")
        return progid + r"\shell"
    base = _TARGET_SHELL_PATH.get(target)
    if base is None:
        raise ValueError(f"不支持的目标: {target}")
    return base


def _shellex_rel_path(target: TargetContext,
                      file_type_ext: str | None) -> str:
    r"""返回 target 对应的 shellex\ContextMenuHandlers 相对路径。"""
    if target is TargetContext.FILETYPE:
        if not file_type_ext:
            raise ValueError("FILETYPE 目标需要 file_type_ext")
        progid = _get_progid(file_type_ext)
        if not progid:
            raise KeyNotFoundError(
                f"无法解析 {file_type_ext} 的 ProgID")
        return progid + r"\shellex\ContextMenuHandlers"
    base = _TARGET_SHELL_PATH.get(target)
    if base is None:
        raise ValueError(f"不支持的目标: {target}")
    return base.replace(r"\shell", r"\shellex\ContextMenuHandlers", 1)


# (前缀, target) -- 注意 Background 必须在 Directory 之前匹配
_PREFIX_MAP: list[tuple[str, TargetContext]] = [
    (r"Directory\Background\shell", TargetContext.DIRECTORY_BACKGROUND),
    (r"Directory\Background\shellex", TargetContext.DIRECTORY_BACKGROUND),
    (r"Directory\shell", TargetContext.DIRECTORY),
    (r"Directory\shellex", TargetContext.DIRECTORY),
    (r"*\shell", TargetContext.FILES),
    (r"*\shellex", TargetContext.FILES),
    (r"Drive\shell", TargetContext.DRIVE),
    (r"Drive\shellex", TargetContext.DRIVE),
    (r"AllFilesystemObjects\shell", TargetContext.ALLFILESYSTEMOBJECTS),
    (r"AllFilesystemObjects\shellex", TargetContext.ALLFILESYSTEMOBJECTS),
]


def _ext_for_progid(progid: str) -> str | None:
    """反向查找：哪个 .ext 的默认值（ProgID）等于 progid。"""
    root = _open_key(HKCR, "")
    if root is None:
        return None
    try:
        for sub in _enum_subkeys(root):
            if not sub.startswith("."):
                continue
            ek = _open_key(HKCR, sub)
            if ek is None:
                continue
            val = _query_value(ek)
            winreg.CloseKey(ek)
            if val and val.lower() == progid.lower():
                return sub
    finally:
        winreg.CloseKey(root)
    return None


def _target_from_rel(rel: str) -> tuple[TargetContext, str | None]:
    """从相对路径推断 (target, file_type_ext)。

    对新场景路径（CommandStore 等）不做精确反推，默认归 FILETYPE；
    新场景主要由 list_entries 直接读取，不依赖 get_entry 反推。
    """
    for prefix, tgt in _PREFIX_MAP:
        if rel == prefix or rel.startswith(prefix + "\\"):
            return tgt, None
    # CommandStore\shell\<name> -> WINX
    if rel.lower().startswith(_WINX_STORE.lower()):
        return TargetContext.WINX, None
    # .<ext>\ShellNew -> NEW
    if "\\ShellNew" in rel and rel.split("\\", 1)[0].startswith("."):
        return TargetContext.NEW, None
    # 否则视为 FILETYPE：首段是 ProgID，反查 ext
    progid = rel.split("\\", 1)[0]
    return TargetContext.FILETYPE, _ext_for_progid(progid)


# ── Shell Extensions\Blocked 检测 ─────────────────────────────
def _blocked_key_paths() -> list[tuple[int, str]]:
    r"""返回 [(root, path), ...] 用于 Shell Extensions\Blocked（HKLM + HKCU）。"""
    return [(HKLM, _HKLM_BLOCKED), (HKCU, _HKCU_BLOCKED)]


def _is_clsid_blocked(clsid: str | None) -> bool:
    r"""检测 CLSID 是否在 Shell Extensions\Blocked 键中（HKLM 或 HKCU）。"""
    if not clsid:
        return False
    for root, path in _blocked_key_paths():
        k = _open_key(root, path)
        if k is None:
            continue
        try:
            if _has_value(k, clsid):
                return True
        finally:
            winreg.CloseKey(k)
    return False


# ── 读取接口 ──────────────────────────────────────────────────
def _read_static_entry(target: TargetContext, file_type_ext: str | None,
                       base_rel: str, name: str) -> MenuEntry:
    r"""解析 shell\<name> 一个静态命令项（含级联递归）。"""
    entry_rel = base_rel + "\\" + name
    key_path = "HKCR\\" + entry_rel
    scope = resolve_scope(entry_rel)
    key = _open_key(HKCR, entry_rel)
    if key is None:
        raise KeyNotFoundError(key_path)

    default = _query_value(key)
    muiverb = _query_value(key, "MUIVerb")
    icon = _query_value(key, "Icon")
    position = _query_value(key, "Position")
    extended = _has_value(key, "Extended")
    subcommands = _query_value(key, "SubCommands")
    blocked = _has_value(key, "LegacyDisable")
    winreg.CloseKey(key)

    display_name = muiverb or default or name

    # command 子键
    command = None
    cmd_key = _open_key(HKCR, entry_rel + "\\command")
    if cmd_key is not None:
        command = _query_value(cmd_key)
        winreg.CloseKey(cmd_key)

    # 级联子项
    children: list[MenuEntry] = []
    has_shell_sub = False
    shell_sub = _open_key(HKCR, entry_rel + "\\shell")
    if shell_sub is not None:
        child_names = _enum_subkeys(shell_sub)
        if child_names:
            has_shell_sub = True
            for cn in child_names:
                try:
                    children.append(_read_static_entry(
                        target, file_type_ext, entry_rel + "\\shell", cn))
                except Exception as exc:  # 单个子项出错跳过
                    print(f"[registry] 跳过 {entry_rel}\\shell\\{cn}: {exc}",
                          file=sys.stderr)
        winreg.CloseKey(shell_sub)

    is_cascade = has_shell_sub or bool(subcommands)
    kind = EntryKind.CASCADE if is_cascade else EntryKind.COMMAND

    return MenuEntry(
        target=target, scope=scope, kind=kind, key_path=key_path,
        name=name, display_name=display_name, file_type_ext=file_type_ext,
        command=command, icon=icon, position=position, extended=extended,
        clsid=None, children=children, blocked=blocked,
    )


def _read_shellex_entry(target: TargetContext, file_type_ext: str | None,
                        base_rel: str, name: str) -> MenuEntry:
    r"""解析 shellex\ContextMenuHandlers\<name>。"""
    entry_rel = base_rel + "\\" + name
    key_path = "HKCR\\" + entry_rel
    scope = resolve_scope(entry_rel)
    key = _open_key(HKCR, entry_rel)
    default = None
    if key is not None:
        default = _query_value(key)
        winreg.CloseKey(key)

    # CLSID：默认值是 GUID 则取默认值，否则键名是 GUID 取键名，否则取默认值
    if _looks_like_clsid(default):
        clsid = default
    elif _looks_like_clsid(name):
        clsid = name
    else:
        clsid = default

    blocked = _is_clsid_blocked(clsid)

    return MenuEntry(
        target=target, scope=scope, kind=EntryKind.SHELLEX, key_path=key_path,
        name=name, display_name=name.strip(), file_type_ext=file_type_ext,
        command=None, icon=None, position=None, extended=False,
        clsid=clsid, children=[], blocked=blocked,
    )


# ── 新场景读取器 ─────────────────────────────────────────────
def _read_shellnew_entries() -> list[MenuEntry]:
    r"""读取"新建"菜单：HKCR 下 .<ext> 含 ShellNew 子键者。

    参考 reference/.../Controls/ShellNewItem.cs：
    - 显示名优先级：ShellNew\MenuText -> ProgID\FriendlyTypeName -> ProgID 默认值 -> ext
    - 图标优先级：ShellNew\IconPath -> ProgID\DefaultIcon 默认值
    - 命令：ShellNew\Command
    - 有效条件：ShellNew 子键含 NullFile/Data/FileName/Directory/Command 之一
    """
    entries: list[MenuEntry] = []
    root = _open_key(HKCR, "")
    if root is None:
        return entries
    try:
        for ext in _enum_subkeys(root):
            if not ext.startswith("."):
                continue
            try:
                ext_key = _open_key(HKCR, ext)
                if ext_key is None:
                    continue
                progid = _query_value(ext_key)
                winreg.CloseKey(ext_key)
                sn_rel = ext + "\\ShellNew"
                sn_key = _open_key(HKCR, sn_rel)
                if sn_key is None:
                    continue
                # 必须含有效值
                has_effect = any(
                    _has_value(sn_key, vn) for vn in _SHELLNEW_EFFECT_VALUES)
                if not has_effect:
                    winreg.CloseKey(sn_key)
                    continue
                menu_text = _query_value(sn_key, "MenuText")
                icon_path = _query_value(sn_key, "IconPath")
                command = _query_value(sn_key, "Command")
                winreg.CloseKey(sn_key)

                # 解析显示名
                display_name = None
                if menu_text:
                    # @资源字符串不展开（需 SHLoadIndirectString，超范围）
                    display_name = menu_text if menu_text.startswith("@") \
                        else menu_text
                if not display_name and progid:
                    pk = _open_key(HKCR, progid)
                    if pk is not None:
                        ftn = _query_value(pk, "FriendlyTypeName")
                        if ftn:
                            display_name = ftn if ftn.startswith("@") else ftn
                        if not display_name:
                            display_name = _query_value(pk)
                        winreg.CloseKey(pk)
                if not display_name:
                    display_name = ext

                # 解析图标
                icon = icon_path
                if not icon and progid:
                    di = _open_key(HKCR, progid + "\\DefaultIcon")
                    if di is not None:
                        icon = _query_value(di)
                        winreg.CloseKey(di)

                key_path = "HKCR\\" + sn_rel
                entries.append(MenuEntry(
                    target=TargetContext.NEW, scope=resolve_scope(sn_rel),
                    kind=EntryKind.COMMAND, key_path=key_path,
                    name=ext, display_name=display_name,
                    file_type_ext=ext, command=command, icon=icon,
                    position=None, extended=False, clsid=None, children=[],
                    blocked=False,
                ))
            except Exception as exc:
                print(f"[registry] 跳过 NEW {ext}: {exc}", file=sys.stderr)
    finally:
        winreg.CloseKey(root)
    return entries


def _read_sendto_entries() -> list[MenuEntry]:
    r"""读取"发送到"菜单：%APPDATA%\Microsoft\Windows\SendTo 下的文件/快捷方式。

    作用域固定为 USER（用户目录）。.lnk 的图标/目标解析超范围，icon 留空。
    """
    entries: list[MenuEntry] = []
    if not os.path.isdir(_SENDTO_DIR):
        return entries
    try:
        for fname in os.listdir(_SENDTO_DIR):
            try:
                if fname.lower() == "desktop.ini":
                    continue
                fpath = os.path.join(_SENDTO_DIR, fname)
                if not os.path.isfile(fpath):
                    continue
                # 显示名：去扩展名（.lnk / .desklink 等都去掉）
                base = os.path.splitext(fname)[0]
                if not base:
                    base = fname
                entries.append(MenuEntry(
                    target=TargetContext.SENDTO, scope=Scope.USER,
                    kind=EntryKind.COMMAND, key_path=fpath,
                    name=fname, display_name=base,
                    file_type_ext=None, command=fpath, icon=None,
                    position=None, extended=False, clsid=None, children=[],
                    blocked=False,
                ))
            except Exception as exc:
                print(f"[registry] 跳过 SENDTO {fname}: {exc}",
                      file=sys.stderr)
    except Exception as exc:
        print(f"[registry] SENDTO 读取失败: {exc}", file=sys.stderr)
    return entries


def _read_openwith_entries() -> list[MenuEntry]:
    r"""读取"打开方式"推荐：遍历有 OpenWithList 或 OpenWithProgids 的 .<ext>。

    - OpenWithProgids：每个值名是一个 ProgID，查 HKCR\<ProgID>\shell\open\command。
    - OpenWithList：每个子键名是 app exe 名，查 HKCR\Applications\<app>\shell\open\command。
    每个 (ext, app/progid) 对作为一个 MenuEntry。
    """
    entries: list[MenuEntry] = []
    root = _open_key(HKCR, "")
    if root is None:
        return entries
    try:
        for ext in _enum_subkeys(root):
            if not ext.startswith("."):
                continue
            try:
                ext_key = _open_key(HKCR, ext)
                if ext_key is None:
                    continue
                # OpenWithProgids：值名是 ProgID
                owpi = _open_key(ext_key, "OpenWithProgids")
                if owpi is not None:
                    for vname, _vdata, _vtype in _enum_values(owpi):
                        try:
                            command = _resolve_open_command(vname)
                            if not command:
                                continue
                            display_name = _progid_display_name(vname) or vname
                            entries.append(MenuEntry(
                                target=TargetContext.OPENWITH,
                                scope=resolve_scope(ext),
                                kind=EntryKind.COMMAND,
                                key_path=f"HKCR\\{ext}\\OpenWithProgids\\{vname}",
                                name=f"{ext}\\{vname}",
                                display_name=display_name,
                                file_type_ext=ext, command=command, icon=None,
                                position=None, extended=False, clsid=None,
                                children=[], blocked=False,
                            ))
                        except Exception as exc:
                            print(f"[registry] 跳过 OPENWITH {ext}\\{vname}: "
                                  f"{exc}", file=sys.stderr)
                    winreg.CloseKey(owpi)
                # OpenWithList：子键名是 app exe 名
                owl = _open_key(ext_key, "OpenWithList")
                if owl is not None:
                    for app in _enum_subkeys(owl):
                        try:
                            command = _resolve_open_command(app,
                                                            via_applications=True)
                            if not command:
                                continue
                            entries.append(MenuEntry(
                                target=TargetContext.OPENWITH,
                                scope=resolve_scope(ext),
                                kind=EntryKind.COMMAND,
                                key_path=f"HKCR\\{ext}\\OpenWithList\\{app}",
                                name=f"{ext}\\{app}",
                                display_name=app,
                                file_type_ext=ext, command=command, icon=None,
                                position=None, extended=False, clsid=None,
                                children=[], blocked=False,
                            ))
                        except Exception as exc:
                            print(f"[registry] 跳过 OPENWITH {ext}\\{app}: "
                                  f"{exc}", file=sys.stderr)
                    winreg.CloseKey(owl)
                winreg.CloseKey(ext_key)
            except Exception as exc:
                print(f"[registry] 跳过 OPENWITH {ext}: {exc}",
                      file=sys.stderr)
    finally:
        winreg.CloseKey(root)
    return entries


def _resolve_open_command(progid_or_app: str,
                          via_applications: bool = False) -> str | None:
    r"""解析 ProgID 或 Applications\<app> 的 shell\open\command 默认值。"""
    if via_applications:
        rel = f"Applications\\{progid_or_app}\\shell\\open\\command"
    else:
        rel = f"{progid_or_app}\\shell\\open\\command"
    k = _open_key(HKCR, rel)
    if k is None:
        return None
    try:
        return _query_value(k)
    finally:
        winreg.CloseKey(k)


def _progid_display_name(progid: str) -> str | None:
    """ProgID 的友好名：FriendlyTypeName -> 默认值。@ 资源字符串原样返回。"""
    k = _open_key(HKCR, progid)
    if k is None:
        return None
    try:
        ftn = _query_value(k, "FriendlyTypeName")
        if ftn:
            return ftn
        return _query_value(k)
    finally:
        winreg.CloseKey(k)


def _read_winx_entries() -> list[MenuEntry]:
    r"""读取 WinX 命令存储：HKLM\...\CommandStore\shell 下的命令项。

    参考 reference/.../Controls/WinXItem.cs；注：Windows 真正的 Win+X 菜单
    实际由 %LOCALAPPDATA%\Microsoft\Windows\WinX 下的 .lnk 文件构成，但本工具
    按设计文档从 CommandStore\shell 读取（这些是 Explorer 注册的命令项，
    被 WinX 及其它级联菜单引用）。每项 scope=SYSTEM 只读。
    """
    entries: list[MenuEntry] = []
    store = _open_key(HKLM, _WINX_STORE)
    if store is None:
        return entries
    try:
        for name in _enum_subkeys(store):
            try:
                entry_rel = _WINX_STORE + "\\" + name
                k = _open_key(HKLM, entry_rel)
                if k is None:
                    continue
                muiverb = _query_value(k, "MUIVerb")
                icon = _query_value(k, "Icon")
                subcommands = _query_value(k, "SubCommands")
                winreg.CloseKey(k)

                command = None
                cmd_key = _open_key(HKLM, entry_rel + "\\command")
                if cmd_key is not None:
                    command = _query_value(cmd_key)
                    winreg.CloseKey(cmd_key)

                display_name = muiverb or name
                kind = EntryKind.CASCADE if subcommands else EntryKind.COMMAND
                key_path = "HKLM\\" + entry_rel
                entries.append(MenuEntry(
                    target=TargetContext.WINX, scope=Scope.SYSTEM, kind=kind,
                    key_path=key_path, name=name, display_name=display_name,
                    file_type_ext=None, command=command, icon=icon,
                    position=None, extended=False, clsid=None, children=[],
                    blocked=False,
                ))
            except Exception as exc:
                print(f"[registry] 跳过 WINX {name}: {exc}", file=sys.stderr)
    finally:
        winreg.CloseKey(store)
    return entries


# ── 读取主入口 ───────────────────────────────────────────────
def list_entries(
    target: TargetContext, file_type_ext: str | None = None
) -> list[MenuEntry]:
    r"""列出某目标场景下的所有右键菜单项（含级联子项的 children）。

    target 为 FILETYPE 时必须传 file_type_ext（如 ".txt"）。
    返回的 MenuEntry.scope 已通过 resolve_scope 判定。
    单键出错跳过并在 stderr 记录，不整体崩溃。
    """
    # 新场景读取器
    if target is TargetContext.NEW:
        return _read_shellnew_entries()
    if target is TargetContext.SENDTO:
        return _read_sendto_entries()
    if target is TargetContext.OPENWITH:
        return _read_openwith_entries()
    if target is TargetContext.WINX:
        return _read_winx_entries()

    entries: list[MenuEntry] = []
    shell_rel = _shell_rel_path(target, file_type_ext)
    shellex_rel = _shellex_rel_path(target, file_type_ext)

    # 静态命令
    sk = _open_key(HKCR, shell_rel)
    if sk is not None:
        for name in _enum_subkeys(sk):
            try:
                entries.append(_read_static_entry(
                    target, file_type_ext, shell_rel, name))
            except Exception as exc:
                print(f"[registry] 跳过 {shell_rel}\\{name}: {exc}",
                      file=sys.stderr)
        winreg.CloseKey(sk)

    # Shell 扩展
    sxk = _open_key(HKCR, shellex_rel)
    if sxk is not None:
        for name in _enum_subkeys(sxk):
            try:
                entries.append(_read_shellex_entry(
                    target, file_type_ext, shellex_rel, name))
            except Exception as exc:
                print(f"[registry] 跳过 {shellex_rel}\\{name}: {exc}",
                      file=sys.stderr)
        winreg.CloseKey(sxk)

    return entries


def get_entry(key_path: str) -> MenuEntry:
    r"""按完整注册表路径读取单个菜单项。

    仅支持静态命令与 Shell 扩展（HKCR\*\shell\<name> 等）；新场景
    （NEW/SENDTO/OPENWITH/WINX）请用 list_entries 读取。
    """
    rel = _normalize_rel(key_path)
    target, file_type_ext = _target_from_rel(rel)

    if r"\shellex\ContextMenuHandlers" in rel:
        base_rel, name = rel.rsplit("\\", 1)
        return _read_shellex_entry(target, file_type_ext, base_rel, name)
    base_rel, name = rel.rsplit("\\", 1)
    return _read_static_entry(target, file_type_ext, base_rel, name)


def enum_targets() -> list[TargetContext]:
    """返回本工具支持的所有目标场景（不含 FILETYPE，其按需配合 ext）。"""
    return [
        TargetContext.FILES,
        TargetContext.DIRECTORY,
        TargetContext.DIRECTORY_BACKGROUND,
        TargetContext.DRIVE,
        TargetContext.ALLFILESYSTEMOBJECTS,
        TargetContext.NEW,
        TargetContext.SENDTO,
        TargetContext.OPENWITH,
        TargetContext.WINX,
    ]


def list_file_types() -> list[str]:
    """扫描 HKCR 下有自定义 shell 动词的文件扩展名（如 [".txt", ".py"]）。"""
    result: list[str] = []
    root = _open_key(HKCR, "")
    if root is None:
        return result
    try:
        for sub in _enum_subkeys(root):
            if not sub.startswith("."):
                continue
            ek = _open_key(HKCR, sub)
            if ek is None:
                continue
            progid = _query_value(ek)
            winreg.CloseKey(ek)
            if not progid:
                continue
            sk = _open_key(HKCR, progid + r"\shell")
            if sk is None:
                continue
            verbs = _enum_subkeys(sk)
            winreg.CloseKey(sk)
            if verbs:
                result.append(sub)
    finally:
        winreg.CloseKey(root)
    return sorted(result)


def resolve_scope(key_path: str) -> Scope:
    r"""判定一条目是用户级（可编辑）还是系统级（只读）。

    检查 HKCU\Software\Classes\<相对路径> 是否存在：存在则 USER，否则 SYSTEM。
    对不在 Classes 树下的路径（如 CommandStore、文件路径）默认 SYSTEM。
    """
    rel = _normalize_rel(key_path)
    cu = _open_key(HKCU, "Software\\Classes\\" + rel)
    if cu is not None:
        winreg.CloseKey(cu)
        return Scope.USER
    return Scope.SYSTEM


# ── 写入接口（按 scope 路由 HKCU/HKLM）─────────────────────────
def _classes_root_for_scope(scope: Scope) -> tuple[int, str]:
    r"""返回 (root, prefix) 用于写入 Classes 树。

    USER -> (HKCU, "Software\\Classes\\")；SYSTEM -> (HKLM, "SOFTWARE\\Classes\\")，
    SYSTEM 需管理员，未提权抛 PermissionDeniedError。
    """
    if scope is Scope.USER:
        return HKCU, "Software\\Classes\\"
    if not elevation.is_admin():
        raise PermissionDeniedError("系统级写入需要管理员权限")
    return HKLM, "SOFTWARE\\Classes\\"


def _set_value(key, name: str | None, value: str, reg_type: int) -> None:
    winreg.SetValueEx(key, name, 0, reg_type, value)


def _delete_value_safe(key, name: str | None) -> None:
    try:
        winreg.DeleteValue(key, name)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _write_display(key, display_name: str | None) -> None:
    """写显示名：@ 开头写 MUIVerb，否则写默认值；并清除另一种。"""
    if display_name and display_name.startswith("@"):
        _set_value(key, "MUIVerb", display_name, winreg.REG_SZ)
        _delete_value_safe(key, "")
    elif display_name:
        _set_value(key, "", display_name, winreg.REG_SZ)
        _delete_value_safe(key, "MUIVerb")
    else:
        _delete_value_safe(key, "")
        _delete_value_safe(key, "MUIVerb")


def _write_fields(key, entry: MenuEntry) -> None:
    """写入显示名/Icon/Position/Extended。"""
    _write_display(key, entry.display_name)
    if entry.icon:
        _set_value(key, "Icon", entry.icon, winreg.REG_EXPAND_SZ)
    if entry.position:
        _set_value(key, "Position", entry.position, winreg.REG_SZ)
    if entry.extended:
        _set_value(key, "Extended", "", winreg.REG_SZ)


def _create_key(root: int, full_path: str):
    """创建/打开键；统一错误转 PermissionDeniedError / RegistryError。"""
    try:
        return winreg.CreateKeyEx(root, full_path, 0, KEY_WRITE_64)
    except PermissionError as exc:
        raise PermissionDeniedError(str(exc))
    except OSError as exc:
        raise RegistryError(str(exc))


def _write_entry_tree(entry: MenuEntry, base_rel: str) -> None:
    r"""在 <root>\<prefix><base_rel>\<entry.name> 下写入整棵树。

    root/prefix 由 entry.scope 路由：USER -> HKCU；SYSTEM -> HKLM（需提权）。
    """
    root, prefix = _classes_root_for_scope(entry.scope)
    rel = base_rel + "\\" + entry.name
    full = prefix + rel
    key = _create_key(root, full)
    try:
        _write_fields(key, entry)
    finally:
        winreg.CloseKey(key)

    if entry.kind is EntryKind.COMMAND and entry.command is not None:
        cmd_full = full + "\\command"
        ckey = _create_key(root, cmd_full)
        try:
            _set_value(ckey, "", entry.command, winreg.REG_EXPAND_SZ)
        finally:
            winreg.CloseKey(ckey)
    elif entry.kind is EntryKind.CASCADE:
        shell_full = full + "\\shell"
        try:
            hk = winreg.CreateKeyEx(root, shell_full, 0, KEY_WRITE_64)
            winreg.CloseKey(hk)
        except OSError:
            pass
        for child in entry.children:
            _write_entry_tree(child, rel + "\\shell")


def create_entry(entry: MenuEntry) -> None:
    r"""新建菜单项。

    按 ``entry.scope`` 路由：USER 写 ``HKCU\Software\Classes\...``；
    SYSTEM 写 ``HKLM\SOFTWARE\Classes\...``（需管理员，未提权抛
    ``PermissionDeniedError``）。不支持创建 Shell 扩展（CLSID，只读）。
    """
    if entry.kind is EntryKind.SHELLEX:
        raise RegistryError("不支持创建 Shell 扩展（CLSID，只读）")
    base_rel = _shell_rel_path(entry.target, entry.file_type_ext)
    _write_entry_tree(entry, base_rel)


def update_entry(entry: MenuEntry) -> None:
    """更新已有菜单项的字段（按 scope 路由 HKCU/HKLM）。

    覆盖写显示名/Icon/Position/Extended 与 command；级联项会递归写入 children，
    但不会删除 children 列表中未出现的旧子项（如需删除请单独调 delete_entry）。
    SYSTEM 写入需管理员，未提权抛 PermissionDeniedError。
    """
    if entry.kind is EntryKind.SHELLEX:
        raise RegistryError("不能编辑 Shell 扩展（只读）")
    root, prefix = _classes_root_for_scope(entry.scope)
    rel = _normalize_rel(entry.key_path)
    full = prefix + rel
    key = _create_key(root, full)
    try:
        # 先清旧的可选值，再重写
        for vname in ("MUIVerb", "Icon", "Position", "Extended",
                      "LegacyDisable"):
            _delete_value_safe(key, vname)
        _write_fields(key, entry)
    finally:
        winreg.CloseKey(key)

    # command 子键
    cmd_rel = rel + "\\command"
    cmd_full = prefix + cmd_rel
    if entry.kind is EntryKind.COMMAND:
        if entry.command is not None:
            ckey = _create_key(root, cmd_full)
            try:
                _set_value(ckey, "", entry.command, winreg.REG_EXPAND_SZ)
            finally:
                winreg.CloseKey(ckey)
        else:
            _delete_key_tree(root, cmd_full)
    elif entry.kind is EntryKind.CASCADE:
        shell_full = full + "\\shell"
        try:
            hk = winreg.CreateKeyEx(root, shell_full, 0, KEY_WRITE_64)
            winreg.CloseKey(hk)
        except OSError:
            pass
        for child in entry.children:
            _write_entry_tree(child, rel + "\\shell")


def _delete_key_tree(root, path: str) -> None:
    """递归删除键及其所有子键。不存在则静默返回。"""
    key = _open_key(root, path, KEY_READ_64)
    if key is None:
        return
    subkeys = _enum_subkeys(key)
    winreg.CloseKey(key)
    for sk in subkeys:
        _delete_key_tree(root, path + "\\" + sk)
    try:
        winreg.DeleteKey(root, path)
    except FileNotFoundError:
        pass
    except PermissionError as exc:
        raise PermissionDeniedError(str(exc))
    except OSError as exc:
        raise RegistryError(str(exc))


def delete_entry(key_path: str) -> None:
    """删除菜单项（含其 command/shell 子键树）。

    自动检测作用域：先查 HKCU，再查 HKLM。HKLM 删除需管理员，
    未提权抛 PermissionDeniedError。两处都无则抛 KeyNotFoundError。
    """
    rel = _normalize_rel(key_path)
    cu_rel = "Software\\Classes\\" + rel
    if _open_key(HKCU, cu_rel, KEY_READ_64) is not None:
        _delete_key_tree(HKCU, cu_rel)
        return
    lm_rel = "SOFTWARE\\Classes\\" + rel
    if _open_key(HKLM, lm_rel, KEY_READ_64) is not None:
        if not elevation.is_admin():
            raise PermissionDeniedError("删除系统级条目需要管理员权限")
        _delete_key_tree(HKLM, lm_rel)
        return
    raise KeyNotFoundError(key_path)


# ── 屏蔽/启用（系统键值法，非删除）─────────────────────────────
# 接口契约：
# - COMMAND/CASCADE：在对应 verb 键设/删 LegacyDisable 值（空字符串）。按 scope 路由。
# - SHELLEX：把 entry.clsid 作为值名写入/删除 Shell Extensions\Blocked 键；
#   HKLM 与 HKCU 两处都写/都删（值数据为空串）。
def block_entry(entry: MenuEntry) -> None:
    """屏蔽菜单项。

    - COMMAND/CASCADE：在 verb 键设 ``LegacyDisable``（空字符串），按 scope
      路由 HKCU/HKLM；SYSTEM 需管理员。
    - SHELLEX：将 ``entry.clsid`` 作为值名写入 HKLM 与 HKCU 的
      ``Shell Extensions\\Blocked`` 键（值数据为空串）。SYSTEM 需管理员；
      USER 在无管理员时尽力写 HKCU（HKLM 失败静默跳过）。
    """
    if entry.kind is EntryKind.SHELLEX:
        clsid = entry.clsid
        if not clsid:
            raise RegistryError("Shell 扩展缺少 CLSID，无法屏蔽")
        if entry.scope is Scope.SYSTEM and not elevation.is_admin():
            raise PermissionDeniedError("屏蔽系统级 Shell 扩展需要管理员权限")
        for root, path in _blocked_key_paths():
            try:
                k = winreg.CreateKeyEx(root, path, 0, KEY_WRITE_64)
            except PermissionError:
                # HKLM 在无管理员时不可写：USER 范围下静默跳过
                if root is HKLM and entry.scope is Scope.USER:
                    continue
                raise PermissionDeniedError(f"无法写入 {path}")
            except OSError as exc:
                if root is HKLM and entry.scope is Scope.USER:
                    continue
                raise RegistryError(str(exc))
            try:
                _set_value(k, clsid, "", winreg.REG_SZ)
            finally:
                winreg.CloseKey(k)
        return

    # COMMAND/CASCADE：在 verb 键设 LegacyDisable
    root, prefix = _classes_root_for_scope(entry.scope)
    rel = _normalize_rel(entry.key_path)
    full = prefix + rel
    key = _create_key(root, full)
    try:
        _set_value(key, "LegacyDisable", "", winreg.REG_SZ)
    finally:
        winreg.CloseKey(key)


def unblock_entry(entry: MenuEntry) -> None:
    """解除屏蔽。

    - COMMAND/CASCADE：删除 verb 键的 ``LegacyDisable`` 值，按 scope 路由。
    - SHELLEX：从 HKLM 与 HKCU 的 ``Shell Extensions\\Blocked`` 键删除 clsid
      值名。SYSTEM 需管理员；USER 无管理员时仅删 HKCU。
    """
    if entry.kind is EntryKind.SHELLEX:
        clsid = entry.clsid
        if not clsid:
            raise RegistryError("Shell 扩展缺少 CLSID")
        if entry.scope is Scope.SYSTEM and not elevation.is_admin():
            raise PermissionDeniedError("解屏蔽系统级 Shell 扩展需要管理员权限")
        for root, path in _blocked_key_paths():
            k = _open_key(root, path, KEY_WRITE_64)
            if k is None:
                continue
            try:
                _delete_value_safe(k, clsid)
            finally:
                winreg.CloseKey(k)
        return

    # COMMAND/CASCADE：删除 LegacyDisable
    root, prefix = _classes_root_for_scope(entry.scope)
    rel = _normalize_rel(entry.key_path)
    full = prefix + rel
    k = _open_key(root, full, KEY_WRITE_64)
    if k is None:
        return  # 键不存在，无可解除
    try:
        _delete_value_safe(k, "LegacyDisable")
    finally:
        winreg.CloseKey(k)
