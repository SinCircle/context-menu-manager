"""应用推断与分组。

从 MenuEntry 推断所属应用（基于 command_info.parse_command + 图标 exe 名 +
CLSID 对应的已知扩展名），按应用分组；可选相似度合并（同应用+同动作、跨
target 的相似项合并为 MergedItem）。
"""
from __future__ import annotations

import os
import re
from collections import OrderedDict
from dataclasses import dataclass, field

from . import command_info
from .command_info import KNOWN_APPS
from .model import EntryKind, MenuEntry


# 已知 Shell 扩展 CLSID -> 应用名（常见系统扩展）
_KNOWN_CLSID_APPS: dict[str, str] = {
    # 这些是 Windows 常见的 Shell 扩展 CLSID，仅作示例；未知 CLSID 归"系统扩展"
    "{00000000-0000-0000-0000-000000000000}": "系统扩展",
}


@dataclass
class MergedItem:
    representative: MenuEntry       # 代表项（用于显示）
    members: list[MenuEntry]        # 被合并的全部成员
    targets: list[str]              # 涉及的目标场景标签（去重）


@dataclass
class AppGroup:
    key: str                                        # 分组键
    app_name: str                                   # 显示名
    entries: list[MenuEntry] = field(default_factory=list)   # merge=False 时的成员
    merged: list[MergedItem] = field(default_factory=list)   # merge=True 时的合并项


def _exe_name_from_icon(icon: str | None) -> str | None:
    """从 icon 路径提取 exe 文件名（小写）。

    icon 形如 "C:\\Path\\app.exe" / "app.exe,0" / "app.exe,-1"。
    """
    if not icon:
        return None
    # 去掉逗号索引
    path_part = icon.split(",")[0].strip()
    if not path_part:
        return None
    # 去掉 @ 资源前缀（如 "@shell32.dll,-42"）
    if path_part.startswith("@"):
        path_part = path_part[1:].split(",")[0].strip()
    base = os.path.basename(path_part)
    if not base:
        return None
    return base.lower()


def infer_app(entry: MenuEntry) -> str | None:
    """推断菜单项所属应用名，未知返回 None。

    综合判定：
    1. command_info.parse_command(entry.command).app_name
    2. icon 路径中的 exe 名 -> KNOWN_APPS
    3. SHELLEX 的 clsid -> 已知 CLSID 表（系统扩展）
    """
    # 1. 从 command 推断
    if entry.command:
        info = command_info.parse_command(entry.command)
        if info and info.app_name:
            return info.app_name
        # 即使无 app_name，也用 exe_name 再查一次（兜底，理论上 parse_command 已查过）
        if info and info.exe_name:
            app = KNOWN_APPS.get(info.exe_name)
            if app:
                return app

    # 2. 从 icon 推断
    icon_exe = _exe_name_from_icon(entry.icon)
    if icon_exe:
        app = KNOWN_APPS.get(icon_exe)
        if app:
            return app

    # 3. SHELLEX 的 clsid
    if entry.kind is EntryKind.SHELLEX and entry.clsid:
        return _KNOWN_CLSID_APPS.get(entry.clsid)

    return None


# 分组键策略：
# - 有 app -> app_name
# - SHELLEX 无 app -> "系统扩展"
# - 其它无 app -> "其他"
def _group_key(entry: MenuEntry, app_name: str | None) -> str:
    if app_name:
        return app_name
    if entry.kind is EntryKind.SHELLEX:
        return "系统扩展"
    return "其他"


def _normalize_command(command: str | None) -> str:
    """规范化命令用于相似度合并：小写、去引号、去占位符、去多余空白。"""
    if not command:
        return ""
    s = command.strip().lower()
    # 去引号
    s = s.replace('"', "").replace("'", "")
    # 去环境变量占位符（展开后路径不同的视为相同--这里不展开，仅去 %var%）
    s = re.sub(r"%[^%]+%", "%", s)
    # 去 Shell 占位符 %1 %V %w %L 等
    s = re.sub(r"%[0-9a-zA-Z]", "%", s)
    # 折叠空白
    s = " ".join(s.split())
    return s


def _merge_key(entry: MenuEntry, app_name: str | None) -> tuple[str, str]:
    """相似度合并键：(规范化命令, 动作)。同应用内同键者合并。"""
    action = "打开"
    if entry.command:
        info = command_info.parse_command(entry.command)
        if info:
            action = info.action
    return (_normalize_command(entry.command), action)


def group_by_app(
    entries: list[MenuEntry], merge_similar: bool = False
) -> list[AppGroup]:
    """按应用分组。

    merge_similar=False：每个 AppGroup.entries 为该应用的全部项。
    merge_similar=True：同应用+同动作+同规范化命令的相似项合并为
    AppGroup.merged 中的 MergedItem（跨 target 的相似项也合并）。

    返回分组按成员数降序；同数量按 app_name 字典序。
    """
    # 第一遍：计算 app_name 与 group_key
    groups: "OrderedDict[str, AppGroup]" = OrderedDict()
    meta: dict[str, list[tuple[MenuEntry, str | None]]] = {}
    for e in entries:
        app = infer_app(e)
        gk = _group_key(e, app)
        if gk not in groups:
            groups[gk] = AppGroup(key=gk, app_name=app or gk)
            meta[gk] = []
        groups[gk].entries.append(e)
        meta[gk].append((e, app))

    if merge_similar:
        for gk, group in groups.items():
            # 按 merge_key 聚合
            buckets: "OrderedDict[tuple[str, str], list[MenuEntry]]" \
                = OrderedDict()
            for e, _app in meta[gk]:
                mk = _merge_key(e, _app)
                buckets.setdefault(mk, []).append(e)
            merged_list: list[MergedItem] = []
            for _mk, members in buckets.items():
                # 仅 1 个成员也作为 MergedItem（保持结构一致），
                # 但 targets 仅 1 项 -- 这样 UI 可统一渲染
                targets: list[str] = []
                seen_t: set[str] = set()
                for m in members:
                    tlabel = m.target.label
                    if tlabel not in seen_t:
                        seen_t.add(tlabel)
                        targets.append(tlabel)
                merged_list.append(MergedItem(
                    representative=members[0],
                    members=members,
                    targets=targets,
                ))
            # 按成员数降序
            merged_list.sort(key=lambda mi: (-len(mi.members),
                                             mi.representative.display_name))
            group.merged = merged_list

    # 排序：总成员数（entries 始终含全部成员）降序，同数量按 app_name 字典序
    result = list(groups.values())
    result.sort(key=lambda g: (-len(g.entries), g.app_name))
    return result
