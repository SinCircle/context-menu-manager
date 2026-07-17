r"""注册表读写层 - 纯 winreg 实现。

读取统一用 HKCR（合并视图）；可编辑性由 resolve_scope 判定
（HKCU\Software\Classes\<相对路径> 存在则为 USER，否则 SYSTEM 只读）。
新建/编辑/删除一律写 HKCU\Software\Classes\...，无需管理员。

key_path 约定：以 "HKCR\<相对路径>" 形式存储（与 stub 一致）。
Shell 扩展（SHELLEX）只读，不可创建/编辑/删除其 CLSID。
"""
from __future__ import annotations

import re
import sys
import winreg

from .model import EntryKind, MenuEntry, Scope, TargetContext

# ── 注册表常量 ────────────────────────────────────────────────
HKCR = winreg.HKEY_CLASSES_ROOT
HKCU = winreg.HKEY_CURRENT_USER
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
    """
    for prefix in ("HKCR\\", "HKCU\\Software\\Classes\\",
                   "HKLM\\Software\\Classes\\"):
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
    r"""返回 target 对应的 shell 相对路径（如 *\shell / Directory\shell）。"""
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


# (前缀, target) —— 注意 Background 必须在 Directory 之前匹配
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
    """从相对路径推断 (target, file_type_ext)。"""
    for prefix, tgt in _PREFIX_MAP:
        if rel == prefix or rel.startswith(prefix + "\\"):
            return tgt, None
    # 否则视为 FILETYPE：首段是 ProgID，反查 ext
    progid = rel.split("\\", 1)[0]
    return TargetContext.FILETYPE, _ext_for_progid(progid)


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

    return MenuEntry(
        target=target, scope=scope, kind=EntryKind.SHELLEX, key_path=key_path,
        name=name, display_name=name.strip(), file_type_ext=file_type_ext,
        command=None, icon=None, position=None, extended=False,
        clsid=clsid, children=[], blocked=False,
    )


def list_entries(
    target: TargetContext, file_type_ext: str | None = None
) -> list[MenuEntry]:
    r"""列出某目标场景下的所有右键菜单项（含级联子项的 children）。

    target 为 FILETYPE 时必须传 file_type_ext（如 ".txt"）。
    返回的 MenuEntry.scope 已通过 resolve_scope 判定。
    单键出错跳过并在 stderr 记录，不整体崩溃。
    """
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
    """按完整注册表路径读取单个菜单项。"""
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
    """
    rel = _normalize_rel(key_path)
    cu = _open_key(HKCU, "Software\\Classes\\" + rel)
    if cu is not None:
        winreg.CloseKey(cu)
        return Scope.USER
    return Scope.SYSTEM


# ── 写入接口（仅 HKCU，无需管理员）──────────────────────────────
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


def _write_entry_tree(entry: MenuEntry, base_rel: str) -> None:
    r"""在 HKCU\Software\Classes\<base_rel>\<entry.name> 下写入整棵树。"""
    rel = base_rel + "\\" + entry.name
    hkcu_rel = "Software\\Classes\\" + rel
    try:
        key = winreg.CreateKeyEx(HKCU, hkcu_rel, 0, KEY_WRITE_64)
    except PermissionError as exc:
        raise PermissionDeniedError(str(exc))
    except OSError as exc:
        raise RegistryError(str(exc))
    try:
        _write_fields(key, entry)
    finally:
        winreg.CloseKey(key)

    if entry.kind is EntryKind.COMMAND and entry.command is not None:
        cmd_rel = hkcu_rel + "\\command"
        try:
            ckey = winreg.CreateKeyEx(HKCU, cmd_rel, 0, KEY_WRITE_64)
            _set_value(ckey, "", entry.command, winreg.REG_EXPAND_SZ)
            winreg.CloseKey(ckey)
        except PermissionError as exc:
            raise PermissionDeniedError(str(exc))
        except OSError as exc:
            raise RegistryError(str(exc))
    elif entry.kind is EntryKind.CASCADE:
        shell_rel = rel + "\\shell"
        try:
            hk = winreg.CreateKeyEx(
                HKCU, "Software\\Classes\\" + shell_rel, 0, KEY_WRITE_64)
            winreg.CloseKey(hk)
        except OSError:
            pass
        for child in entry.children:
            _write_entry_tree(child, shell_rel)


def create_entry(entry: MenuEntry) -> None:
    r"""新建菜单项。entry.scope 应为 USER；仅写 HKCU\Software\Classes\...。"""
    if entry.kind is EntryKind.SHELLEX:
        raise RegistryError("不支持创建 Shell 扩展（CLSID，只读）")
    base_rel = _shell_rel_path(entry.target, entry.file_type_ext)
    _write_entry_tree(entry, base_rel)


def update_entry(entry: MenuEntry) -> None:
    """更新已有菜单项的字段（仅 HKCU）。

    覆盖写显示名/Icon/Position/Extended 与 command；级联项会递归写入 children，
    但不会删除 children 列表中未出现的旧子项（如需删除请单独调 delete_entry）。
    """
    if entry.kind is EntryKind.SHELLEX:
        raise RegistryError("不能编辑 Shell 扩展（只读）")
    rel = _normalize_rel(entry.key_path)
    hkcu_rel = "Software\\Classes\\" + rel
    try:
        key = winreg.CreateKeyEx(HKCU, hkcu_rel, 0, KEY_WRITE_64)
    except PermissionError as exc:
        raise PermissionDeniedError(str(exc))
    except OSError as exc:
        raise RegistryError(str(exc))
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
    cmd_hkcu = "Software\\Classes\\" + cmd_rel
    if entry.kind is EntryKind.COMMAND:
        if entry.command is not None:
            try:
                ckey = winreg.CreateKeyEx(HKCU, cmd_hkcu, 0, KEY_WRITE_64)
                _set_value(ckey, "", entry.command, winreg.REG_EXPAND_SZ)
                winreg.CloseKey(ckey)
            except PermissionError as exc:
                raise PermissionDeniedError(str(exc))
            except OSError as exc:
                raise RegistryError(str(exc))
        else:
            _delete_key_tree(HKCU, cmd_hkcu)
    elif entry.kind is EntryKind.CASCADE:
        shell_rel = rel + "\\shell"
        try:
            hk = winreg.CreateKeyEx(
                HKCU, "Software\\Classes\\" + shell_rel, 0, KEY_WRITE_64)
            winreg.CloseKey(hk)
        except OSError:
            pass
        for child in entry.children:
            _write_entry_tree(child, shell_rel)


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
    """删除菜单项（含其 command/shell 子键树）。仅删 HKCU 中的副本。"""
    rel = _normalize_rel(key_path)
    hkcu_rel = "Software\\Classes\\" + rel
    # 确认 HKCU 中存在，否则视为不存在
    chk = _open_key(HKCU, hkcu_rel, KEY_READ_64)
    if chk is None:
        raise KeyNotFoundError(key_path)
    winreg.CloseKey(chk)
    _delete_key_tree(HKCU, hkcu_rel)
