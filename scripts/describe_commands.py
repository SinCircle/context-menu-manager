#!/usr/bin/env python3
"""遍历所有右键菜单场景，对每条命令调用 command_info.parse_command 生成描述表。

运行：
    python scripts/describe_commands.py
"""
from __future__ import annotations

import sys
import os

# 确保能 import 项目包（从仓库根目录运行或脚本目录运行均可）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from context_menu_manager import command_info, registry
from context_menu_manager.model import EntryKind, TargetContext


def _iter_all_entries():
    """遍历所有 enum_targets + list_file_types，yield (target_label, entry)。"""
    for tgt in registry.enum_targets():
        try:
            entries = registry.list_entries(tgt)
        except Exception as exc:
            print(f"[describe] 列举 {tgt.label} 失败: {exc}", file=sys.stderr)
            continue
        for e in entries:
            yield tgt.label, e
    # 文件类型
    try:
        for ext in registry.list_file_types():
            try:
                entries = registry.list_entries(TargetContext.FILETYPE, ext)
            except Exception as exc:
                print(f"[describe] 列举 FILETYPE {ext} 失败: {exc}",
                      file=sys.stderr)
                continue
            for e in entries:
                yield f"文件类型 {ext}", e
    except Exception as exc:
        print(f"[describe] list_file_types 失败: {exc}", file=sys.stderr)


def main() -> None:
    print("右键菜单命令描述表")
    print("=" * 100)
    # 表头
    cols = ("目标", "类型", "显示名", "命令", "描述")
    widths = (24, 8, 30, 60, 30)
    header = "  ".join(c.ljust(w) for c, w in zip(cols, widths))
    print(header)
    print("-" * len(header))

    total = 0
    described = 0
    for tgt_label, e in _iter_all_entries():
        total += 1
        kind = {
            EntryKind.COMMAND: "CMD",
            EntryKind.SHELLEX: "SHX",
            EntryKind.CASCADE: "CAS",
        }.get(e.kind, "?")
        cmd = (e.command or "") or "(无)"
        # 截断
        cmd_show = cmd if len(cmd) <= widths[3] else cmd[: widths[3] - 3] + "..."
        name_show = e.display_name or e.name
        if len(name_show) > widths[2]:
            name_show = name_show[: widths[2] - 3] + "..."
        tgt_show = tgt_label
        if len(tgt_show) > widths[0]:
            tgt_show = tgt_show[: widths[0] - 3] + "..."

        info = command_info.parse_command(e.command)
        if info is not None:
            described += 1
            desc = info.description
        else:
            desc = "" if e.command else "—"
        if len(desc) > widths[4]:
            desc = desc[: widths[4] - 3] + "..."

        print(f"{tgt_show.ljust(widths[0])}  "
              f"{kind.ljust(widths[1])}  "
              f"{name_show.ljust(widths[2])}  "
              f"{cmd_show.ljust(widths[3])}  "
              f"{desc.ljust(widths[4])}")

    print("-" * len(header))
    print(f"共 {total} 条；其中 {described} 条已生成描述，"
          f"{total - described} 条无命令或无法解析。")


if __name__ == "__main__":
    main()
