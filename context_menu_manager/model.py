"""数据模型 - 前后端共享契约。

本文件是 UI 层与注册表层的唯一共享数据结构。
任何一方如需修改字段，必须先与另一方协商（通过主控），
以保证并行开发不冲突。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TargetContext(Enum):
    """右键菜单出现的目标场景。"""

    FILES = "files"                          # 所有文件 (*)
    DIRECTORY = "directory"                  # 文件夹
    DIRECTORY_BACKGROUND = "directory_background"  # 桌面/文件夹空白处
    DRIVE = "drive"                          # 驱动器
    ALLFILESYSTEMOBJECTS = "allfilesystemobjects"
    FILETYPE = "filetype"                    # 配合 file_type_ext，如 ".txt"
    NEW = "new"                              # 新建菜单 (ShellNew)
    SENDTO = "sendto"                        # 发送到
    OPENWITH = "openwith"                    # 打开方式
    WINX = "winx"                            # WinX 菜单（Win+X）

    @property
    def label(self) -> str:
        return {
            TargetContext.FILES: "文件（所有文件 *）",
            TargetContext.DIRECTORY: "文件夹",
            TargetContext.DIRECTORY_BACKGROUND: "桌面与文件夹背景",
            TargetContext.DRIVE: "驱动器",
            TargetContext.ALLFILESYSTEMOBJECTS: "所有文件系统对象",
            TargetContext.FILETYPE: "文件类型",
            TargetContext.NEW: "新建",
            TargetContext.SENDTO: "发送到",
            TargetContext.OPENWITH: "打开方式",
            TargetContext.WINX: "WinX 菜单",
        }[self]


class Scope(Enum):
    """作用域。提权后 SYSTEM 也可编辑（见 elevation.can_edit）。"""

    USER = "user"      # HKCU\Software\Classes
    SYSTEM = "system"  # HKLM/HKCR，需管理员

    @property
    def label(self) -> str:
        return {
            Scope.USER: "用户级（可编辑）",
            Scope.SYSTEM: "系统级",
        }[self]


class EntryKind(Enum):
    """菜单项类型。"""

    COMMAND = "command"    # 静态命令 shell\<名>\command
    SHELLEX = "shellex"    # Shell 扩展 shellex\ContextMenuHandlers（CLSID）
    CASCADE = "cascade"    # 级联子菜单（含子命令）

    @property
    def label(self) -> str:
        return {
            EntryKind.COMMAND: "自定义命令",
            EntryKind.SHELLEX: "Shell 扩展",
            EntryKind.CASCADE: "级联子菜单",
        }[self]


@dataclass
class MenuEntry:
    """一条右键菜单项。

    children 体现级联父子从属关系；target/scope 体现归属场景与作用域。
    """

    target: TargetContext
    scope: Scope
    kind: EntryKind
    key_path: str                # 完整注册表路径
    name: str                    # 键名（注册表标识）
    display_name: str            # MUIVerb 或默认值
    file_type_ext: str | None = None    # 仅 FILETYPE
    command: str | None = None          # command 默认值
    icon: str | None = None
    position: str | None = None         # "Top" / "Bottom" / None
    extended: bool = False              # 仅 Shift+右键显示
    clsid: str | None = None            # SHELLEX 用
    children: list["MenuEntry"] = field(default_factory=list)
    blocked: bool = False               # 已禁用（存在 LegacyDisable 或在 Blocked 键中）

    @property
    def editable(self) -> bool:
        """类型上是否可编辑（非 Shell 扩展）。

        作用域与提权判定见 ``elevation.can_edit``；UI 启用/禁用编辑按钮
        应使用 ``elevation.can_edit(entry)`` 而非本属性。
        """
        return self.kind is not EntryKind.SHELLEX

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target.value,
            "scope": self.scope.value,
            "kind": self.kind.value,
            "key_path": self.key_path,
            "name": self.name,
            "display_name": self.display_name,
            "file_type_ext": self.file_type_ext,
            "command": self.command,
            "icon": self.icon,
            "position": self.position,
            "extended": self.extended,
            "clsid": self.clsid,
            "children": [c.to_dict() for c in self.children],
            "blocked": self.blocked,
        }
