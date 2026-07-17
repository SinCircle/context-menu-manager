"""详情面板 - 主窗口右侧，展示并编辑选中项全部字段。

只读字段：目标场景 / 作用域 / 类型 / 文件类型扩展 / 注册表路径 /
         键名 / CLSID / 位置 / Extended / 屏蔽状态。
可编辑字段（当 elevation.can_edit(entry)=True 时启用）：
         显示名 / 命令 / 图标 / Position / Extended。
命令旁显示 command_info.parse_command 解析出的描述（如"用 VSCode 打开"），
command_info 为 stub 或解析失败时不显示描述（显示"-"）。
命令校验用 placeholders.validate_command()。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

from .. import elevation
from ..model import EntryKind, MenuEntry, Scope

# Position 可选值
POSITIONS: list[str] = ["（无）", "Top", "Bottom"]


class DetailPanel(ttk.Frame):
    """右侧详情/编辑面板。"""

    def __init__(
        self,
        master: tk.Misc,
        placeholders=None,
        command_info=None,
        on_save: Optional[Callable[[MenuEntry], None]] = None,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(master, *args, **kwargs)
        self._placeholders = placeholders
        self._command_info = command_info
        self._on_save = on_save
        self._entry: Optional[MenuEntry] = None
        self._build_ui()
        self._clear()

    # ── UI 构建 ───────────────────────────────────────────────
    def _build_ui(self) -> None:
        # 标题
        self._title_var = tk.StringVar(value="（未选中）")
        title = ttk.Label(
            self, textvariable=self._title_var,
            font=("Microsoft YaHei", 12, "bold"),
        )
        title.pack(anchor="w", padx=10, pady=(10, 4))

        # 表单容器
        form = ttk.Frame(self)
        form.pack(fill="both", expand=True, padx=10, pady=4)

        self._readonly_vars: dict[str, tk.StringVar] = {}
        self._editable_vars: dict[str, tk.StringVar] = {}
        self._editable_widgets: dict[str, tk.Widget] = {}
        self._extended_var = tk.BooleanVar(value=False)

        readonly_fields: list[tuple[str, str]] = [
            ("target", "目标场景"),
            ("scope", "作用域"),
            ("kind", "类型"),
            ("file_type_ext", "文件类型扩展"),
            ("key_path", "注册表路径"),
            ("name", "键名"),
            ("clsid", "CLSID"),
            ("position", "位置"),
            ("extended", "Extended"),
            ("blocked", "屏蔽状态"),
        ]
        row = 0
        for key, label in readonly_fields:
            ttk.Label(form, text=label + "：").grid(
                row=row, column=0, sticky="ne", padx=(0, 6), pady=2
            )
            var = tk.StringVar(value="-")
            ttk.Label(
                form, textvariable=var, wraplength=420, justify="left"
            ).grid(row=row, column=1, sticky="w", pady=2)
            self._readonly_vars[key] = var
            row += 1

        ttk.Separator(form, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=6
        )
        row += 1

        # 可编辑字段：显示名
        ttk.Label(form, text="显示名：").grid(
            row=row, column=0, sticky="ne", padx=(0, 6), pady=2
        )
        var = tk.StringVar()
        entry = ttk.Entry(form, textvariable=var, width=60)
        entry.grid(row=row, column=1, sticky="we", pady=2)
        self._editable_vars["display_name"] = var
        self._editable_widgets["display_name"] = entry
        row += 1

        # 可编辑字段：命令
        ttk.Label(form, text="命令：").grid(
            row=row, column=0, sticky="ne", padx=(0, 6), pady=2
        )
        var = tk.StringVar()
        entry = ttk.Entry(form, textvariable=var, width=60)
        entry.grid(row=row, column=1, sticky="we", pady=2)
        self._editable_vars["command"] = var
        self._editable_widgets["command"] = entry
        row += 1

        # 命令描述（只读，由 command_info.parse_command 解析）
        ttk.Label(form, text="命令描述：").grid(
            row=row, column=0, sticky="ne", padx=(0, 6), pady=2
        )
        self._cmd_desc_var = tk.StringVar(value="-")
        ttk.Label(
            form, textvariable=self._cmd_desc_var,
            wraplength=420, justify="left", foreground="#555",
        ).grid(row=row, column=1, sticky="w", pady=2)
        row += 1

        # 可编辑字段：图标
        ttk.Label(form, text="图标：").grid(
            row=row, column=0, sticky="ne", padx=(0, 6), pady=2
        )
        var = tk.StringVar()
        entry = ttk.Entry(form, textvariable=var, width=60)
        entry.grid(row=row, column=1, sticky="we", pady=2)
        self._editable_vars["icon"] = var
        self._editable_widgets["icon"] = entry
        row += 1

        # Position（可编辑 Combobox）
        ttk.Label(form, text="Position：").grid(
            row=row, column=0, sticky="e", padx=(0, 6), pady=2
        )
        pos_var = tk.StringVar(value=POSITIONS[0])
        pos_combo = ttk.Combobox(
            form, textvariable=pos_var, state="readonly",
            values=POSITIONS, width=12,
        )
        pos_combo.grid(row=row, column=1, sticky="w", pady=2)
        self._editable_vars["position"] = pos_var
        self._editable_widgets["position"] = pos_combo
        row += 1

        # Extended（可编辑 Checkbutton）
        ttk.Label(form, text="Extended：").grid(
            row=row, column=0, sticky="e", padx=(0, 6), pady=2
        )
        ext_chk = ttk.Checkbutton(
            form, text="仅 Shift+右键显示", variable=self._extended_var
        )
        ext_chk.grid(row=row, column=1, sticky="w", pady=2)
        self._editable_widgets["extended"] = ext_chk
        row += 1

        # 校验标签
        self._validate_var = tk.StringVar(value="")
        self._validate_label = ttk.Label(
            form, textvariable=self._validate_var,
            foreground="#c00", wraplength=440, justify="left",
        )
        self._validate_label.grid(row=row, column=1, sticky="w", pady=2)
        row += 1

        # 监听命令变化 -> 实时校验
        self._editable_vars["command"].trace_add("write", self._on_command_change)

        form.columnconfigure(1, weight=1)

        # 底部操作
        actions = ttk.Frame(self)
        actions.pack(side="bottom", fill="x", padx=10, pady=8)
        self._save_btn = ttk.Button(
            actions, text="保存修改", command=self._on_save_click
        )
        self._save_btn.pack(side="right")
        self._placeholder_btn = ttk.Button(
            actions, text="占位符帮助", command=self._show_placeholders
        )
        self._placeholder_btn.pack(side="right", padx=4)

    # ── 状态 ─────────────────────────────────────────────────
    def _clear(self) -> None:
        self._entry = None
        self._title_var.set("（未选中）")
        for v in self._readonly_vars.values():
            v.set("-")
        for v in self._editable_vars.values():
            v.set(POSITIONS[0] if v is self._editable_vars.get("position") else "")
        self._cmd_desc_var.set("-")
        self._extended_var.set(False)
        self._set_editable(False)
        self._validate_var.set("")

    def _set_editable(self, editable: bool) -> None:
        state = "normal" if editable else "disabled"
        for w in self._editable_widgets.values():
            try:
                w.config(state=state)
            except tk.TclError:
                pass
        self._save_btn.config(state=state)

    # ── 显示 ─────────────────────────────────────────────────
    def show_entry(self, entry: Optional[MenuEntry]) -> None:
        if entry is None:
            self._clear()
            return
        self._entry = entry
        # 标题：屏蔽项加标记
        title = f"{entry.display_name}  ({entry.kind.label})"
        if entry.blocked:
            title = f"[屏蔽] {title}"
        self._title_var.set(title)
        self._readonly_vars["target"].set(entry.target.label)
        self._readonly_vars["scope"].set(entry.scope.label)
        self._readonly_vars["kind"].set(entry.kind.label)
        self._readonly_vars["file_type_ext"].set(entry.file_type_ext or "-")
        self._readonly_vars["key_path"].set(entry.key_path or "-")
        self._readonly_vars["name"].set(entry.name or "-")
        self._readonly_vars["clsid"].set(entry.clsid or "-")
        self._readonly_vars["position"].set(entry.position or "-")
        self._readonly_vars["extended"].set("是" if entry.extended else "否")
        self._readonly_vars["blocked"].set(
            "已屏蔽" if entry.blocked else "正常")

        self._editable_vars["display_name"].set(entry.display_name or "")
        self._editable_vars["command"].set(entry.command or "")
        self._editable_vars["icon"].set(entry.icon or "")
        self._editable_vars["position"].set(
            entry.position if entry.position in ("Top", "Bottom") else POSITIONS[0]
        )
        self._extended_var.set(bool(entry.extended))

        # 命令描述（由 command_info 解析）
        self._update_command_description(entry.command)

        # 可编辑性：用 elevation.can_edit 统一判定
        self._set_editable(elevation.can_edit(entry))
        self._validate_command(self._editable_vars["command"].get())

    def _update_command_description(self, command: str | None) -> None:
        """调 command_info.parse_command 获取描述；stub 或失败时显示"-"。"""
        if self._command_info is None:
            self._cmd_desc_var.set("-")
            return
        try:
            info = self._command_info.parse_command(command)
        except Exception:
            info = None
        if info is not None and getattr(info, "description", None):
            self._cmd_desc_var.set(info.description)
        else:
            self._cmd_desc_var.set("-")

    # ── 校验 ─────────────────────────────────────────────────
    def _on_command_change(self, *args) -> None:
        self._validate_command(self._editable_vars["command"].get())

    def _validate_command(self, command: str) -> None:
        if not self._entry or not elevation.can_edit(self._entry):
            self._validate_var.set("")
            return
        if self._placeholders is None:
            self._validate_var.set("")
            return
        try:
            warnings = self._placeholders.validate_command(command)
        except Exception:
            self._validate_var.set("")
            return
        if warnings:
            self._validate_var.set("⚠ " + "；".join(warnings))
            self._validate_label.config(foreground="#c00")
        else:
            self._validate_var.set("✓ 命令格式 OK")
            self._validate_label.config(foreground="#060")

    # ── 占位符帮助 ───────────────────────────────────────────
    def _show_placeholders(self) -> None:
        if self._placeholders is None:
            messagebox.showinfo("占位符帮助", "占位符模块未就绪", parent=self)
            return
        try:
            items = self._placeholders.describe()
        except Exception as exc:
            messagebox.showerror("错误", str(exc), parent=self)
            return
        text = "\n".join(f"{k}：{v}" for k, v in items) or "（无）"
        messagebox.showinfo("占位符帮助", text, parent=self)

    # ── 保存 ─────────────────────────────────────────────────
    def _on_save_click(self) -> None:
        if self._entry is None or not elevation.can_edit(self._entry):
            return
        e = self._entry
        pos_val = self._editable_vars["position"].get()
        position = None if pos_val == POSITIONS[0] else pos_val
        updated = MenuEntry(
            target=e.target,
            scope=e.scope,
            kind=e.kind,
            key_path=e.key_path,
            name=e.name,
            display_name=self._editable_vars["display_name"].get(),
            file_type_ext=e.file_type_ext,
            command=self._editable_vars["command"].get() or None,
            icon=self._editable_vars["icon"].get() or None,
            position=position,
            extended=self._extended_var.get(),
            clsid=e.clsid,
            children=list(e.children),
            blocked=e.blocked,
        )
        if self._on_save is not None:
            self._on_save(updated)
