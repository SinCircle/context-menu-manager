"""刷新/重启资源管理器与导航。

- notify_shell：ctypes 调 SHChangeNotify 通知关联变化（刷新图标/菜单）。
- restart_explorer：taskkill 后重新启动 explorer.exe（兜底）。
- open_in_regedit：打开 regedit 并定位到指定注册表路径。
- open_in_explorer：资源管理器打开并选中指定文件/文件夹。
"""
from __future__ import annotations

import ctypes
import subprocess
import winreg

# Shell 变化通知常量
SHCNE_ASSOCCHANGED = 0x08000000
SHCNF_IDLIST = 0x0000

# regedit 的"上次定位"键
_REGEDIT_LASTKEY = r"Software\Microsoft\Windows\CurrentVersion\Applets\Regedit"


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


def open_in_regedit(key_path: str) -> None:
    r"""打开注册表编辑器并定位到 key_path。

    实现：写 ``HKCU\Software\Microsoft\Windows\CurrentVersion\Applets\Regedit``
    的 ``LastKey`` 值为 key_path，然后启动 ``regedit /m``（/m 避免上次会话
    提示）。key_path 应为 ``计算机\HKEY_...\<sub>`` 或 ``HKEY_...\<sub>`` 形式；
    本函数会规范化前缀。
    """
    normalized = _normalize_reg_path(key_path)
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, _REGEDIT_LASTKEY, 0,
            winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY,
        ) as k:
            winreg.SetValueEx(k, "LastKey", 0, winreg.REG_SZ, normalized)
    except OSError:
        # 写入失败时仍尝试直接启动 regedit
        pass
    try:
        subprocess.Popen(["regedit.exe", "/m"])
    except OSError:
        pass


def open_in_explorer(path: str) -> None:
    r"""资源管理器打开并选中 path（``explorer /select,"path"``）。

    path 应为文件/文件夹的绝对路径。
    """
    # explorer /select,"C:\Path\To\File"
    # 用 /select, 形式；路径用引号包裹
    arg = f'/select,"{path}"'
    try:
        subprocess.Popen(["explorer.exe", arg])
    except OSError:
        pass


def _normalize_reg_path(key_path: str) -> str:
    r"""规范化注册表路径为 regedit 期望的 ``计算机\HKEY_...\<sub>`` 形式。

    regedit 的 LastKey 形如：
    ``计算机\HKEY_CURRENT_USER\Software\Classes\...``
    本函数接受 ``HKCR\...`` / ``HKCU\...`` / ``HKLM\...`` / ``HKEY_...`` 等
    前缀并规范化为带 ``计算机\`` 前缀的完整形式。
    """
    _ALIAS = {
        "HKCR": "HKEY_CLASSES_ROOT",
        "HKCU": "HKEY_CURRENT_USER",
        "HKLM": "HKEY_LOCAL_MACHINE",
        "HKU": "HKEY_USERS",
        "HKCC": "HKEY_CURRENT_CONFIG",
    }
    s = key_path.strip()
    # 已是 计算机前缀
    if s.startswith("计算机\\"):
        return s
    # 已是 HKEY_ 前缀
    for full in ("HKEY_CLASSES_ROOT", "HKEY_CURRENT_USER",
                 "HKEY_LOCAL_MACHINE", "HKEY_USERS", "HKEY_CURRENT_CONFIG"):
        if s.startswith(full + "\\") or s == full:
            return "计算机\\" + s
    # HKxx 简写
    head = s.split("\\", 1)[0]
    rest = s[len(head) + 1:] if "\\" in s else ""
    full = _ALIAS.get(head.upper())
    if full:
        return "计算机\\" + full + (("\\" + rest) if rest else "")
    # 无法识别，原样加前缀
    return "计算机\\" + s
