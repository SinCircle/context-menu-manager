"""命令行占位符说明与校验。

Windows Shell 静态命令中常用的占位符：
  %1 / %V / %w / %L —— 由 Shell 在执行时替换为选中对象的路径。
"""
from __future__ import annotations

# 占位符 -> 说明（供 UI 帮助展示）
PLACEHOLDERS: dict[str, str] = {
    "%1": "文件路径",
    "%V": "文件/文件夹路径",
    "%w": "工作目录",
    "%L": "长路径名",
}


def describe() -> list[tuple[str, str]]:
    """返回 [("占位符", "说明"), ...]，供 UI 帮助展示。"""
    return list(PLACEHOLDERS.items())


def validate_command(command: str) -> list[str]:
    """校验命令字符串，返回警告列表（空表表示 OK）。

    检查项：
      - 命令非空；
      - 双引号配对；
      - 是否包含路径占位符（不含则作为静态命令，给出提示）。
    """
    warnings: list[str] = []
    if not command or not command.strip():
        warnings.append("命令不能为空")
        return warnings

    if command.count('"') % 2 != 0:
        warnings.append('命令中双引号未配对，可能导致解析错误')

    has_placeholder = any(p in command for p in PLACEHOLDERS)
    if not has_placeholder:
        warnings.append(
            "命令未包含路径占位符（%1/%V/%w/%L），将作为静态命令运行"
            "（不对所选文件操作）")

    return warnings
