"""刷新/重启资源管理器。

- notify_shell：ctypes 调 SHChangeNotify 通知关联变化（刷新图标/菜单）。
- restart_explorer：taskkill 后重新启动 explorer.exe（兜底）。
"""
from __future__ import annotations

import ctypes
import subprocess

# Shell 变化通知常量
SHCNE_ASSOCCHANGED = 0x08000000
SHCNF_IDLIST = 0x0000


def notify_shell() -> None:
    """通知 Shell 文件关联已改变，使资源管理器刷新图标与右键菜单。"""
    try:
        ctypes.windll.shell32.SHChangeNotify(
            SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
    except OSError:
        # 非Windows 或调用失败时静默忽略
        pass


def restart_explorer() -> None:
    """强制结束并重启资源管理器进程（兜底刷新手段）。"""
    subprocess.run(
        ["taskkill", "/f", "/im", "explorer.exe"],
        capture_output=True,
    )
    # 重新启动 explorer.exe（作为新进程，不阻塞）
    subprocess.Popen(["explorer.exe"])
