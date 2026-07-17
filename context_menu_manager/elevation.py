"""提权与权限判定（实体实现，前后端共用）。"""
from __future__ import annotations

import ctypes
import os
import sys

from .model import EntryKind, MenuEntry, Scope


def is_admin() -> bool:
    """当前进程是否以管理员身份运行。"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def can_edit(entry: MenuEntry) -> bool:
    """是否可编辑：非 Shell 扩展，且（用户级 或 已提权）。"""
    return entry.kind is not EntryKind.SHELLEX and (
        entry.scope is Scope.USER or is_admin()
    )


def can_delete(entry: MenuEntry) -> bool:
    """是否可删除：同 can_edit。"""
    return can_edit(entry)


def can_block(entry: MenuEntry) -> bool:
    """是否可屏蔽：用户级或已提权（Shell 扩展也可屏蔽）。"""
    return entry.scope is Scope.USER or is_admin()


def _windowless_python() -> str:
    """返回无控制台窗口的 Python 可执行文件路径。

    优先同目录的 pythonw.exe；不存在则回退 sys.executable。
    用于提权重启时避免弹出额外的黑色控制台窗口。
    """
    candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return candidate if os.path.exists(candidate) else sys.executable


def request_elevation() -> bool:
    """以管理员身份重启自身（触发 UAC）。

    返回值：
    - 已是管理员 -> False（无需提权）
    - 成功触发提权重启 -> True（调用方应随后 ``sys.exit``）
    - 用户拒绝 UAC 或失败 -> False

    用 pythonw.exe 重启以避免额外的控制台黑窗口；脚本路径转为绝对路径、
    工作目录设为脚本所在目录，避免提权后默认落在 System32 找不到脚本。
    """
    if is_admin():
        return False
    argv = list(sys.argv)
    if argv:
        argv[0] = os.path.abspath(argv[0])
    params = " ".join(f'"{a}"' for a in argv)
    work_dir = os.path.dirname(argv[0]) if argv else os.getcwd()
    try:
        # SW_SHOWNORMAL = 1
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", _windowless_python(), params, work_dir, 1
        )
    except Exception:
        return False
    # ShellExecuteW 返回值 > 32 表示成功
    return int(rc) > 32
