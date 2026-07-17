"""新增/编辑菜单项对话框。

字段：目标场景（含文件类型）、显示名、命令、图标路径、
      Position(Top/Bottom/无)、Extended 勾选、是否级联（含子命令列表增删）。
保存调用方根据 result 调 registry.create_entry / update_entry。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from .. import registry
from ..model import EntryKind, MenuEntry, Scope, TargetContext

# 目标场景下拉项：(枚举, 中文标签)
TARGET_LABELS: list[tuple[TargetContext, str]] = [
    (TargetContext.FILES, TargetContext.FILES.label),
    (TargetContext.DIRECTORY, TargetContext.DIRECTORY.label),
    (TargetContext.DIRECTORY_BACKGROUND, TargetContext.DIRECTORY_BACKGROUND.label),
    (TargetContext.DRIVE, TargetContext.DRIVE.label),
    (TargetContext.ALLFILESYSTEMOBJECTS, TargetContext.ALLFILESYSTEMOBJECTS.label),
    (TargetContext.FILETYPE, TargetContext.FILETYPE.label),
]

POSITIONS: list[str] = ["（无）", "Top", "Bottom"]


class EditDialog:
    """新增/编辑对话框。

    用法：
        dlg = EditDialog(parent, entry=None_or_existing, placeholders=...)
        parent.wait_window(dlg.top)
        if dlg.result is not None:
            registry.create_entry(dlg.result) / update_entry(dlg.result)
    """

    def __init__(
        self,
        parent: tk.Misc,
        entry: Optional[MenuEntry] = None,
        placeholders=None,
    ) -> None:
        self.result: Optional[MenuEntry] = None
        self._placeholders = placeholders
        self._entry = entry
        # 子命令列表：(display_name, command)
        self._children: list[tuple[str, str]] = []

        self.top = tk.Toplevel(parent)
        self.top.title("编辑菜单项" if entry else "新建菜单项")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self._build_ui()
        if entry is not None:
            self._load(entry)
        # 居中弹窗
        self.top.update_idletasks()
        w, h = 560, 520
        self.top.geometry(f"{w}x{h}+{(parent.winfo_screenwidth() - w) // 2}+"
                          f"{(parent.winfo_screenheight() - h) // 3}")

    # ── UI 构建 ───────────────────────────────────────────────
    def _build_ui(self) -> None:
        form = ttk.Frame(self.top, padding=12)
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)

        row = 0
        # 目标场景
        ttk.Label(form, text="目标场景：").grid(
            row=row, column=0, sticky="e", padx=(0, 6), pady=3
        )
        self._target_var = tk.StringVar(value=TARGET_LABELS[0][1])
        target_combo = ttk.Combobox(
            form, textvariable=self._target_var, state="readonly",
            values=[lbl for _, lbl in TARGET_LABELS], width=26,
        )
        target_combo.grid(row=row, column=1, sticky="w", pady=3)
        target_combo.bind("<<ComboboxSelected>>", self._on_target_change)
        row += 1

        # 文件类型扩展
        ttk.Label(form, text="文件类型扩展：").grid(
            row=row, column=0, sticky="e", padx=(0, 6), pady=3
        )
        self._ext_var = tk.StringVar()
        self._ext_combo = ttk.Combobox(form, textvariable=self._ext_var, width=26)
        try:
            self._ext_combo["values"] = registry.list_file_types()
        except Exception:
            pass
        self._ext_combo.grid(row=row, column=1, sticky="w", pady=3)
        self._ext_combo.config(state="disabled")
        row += 1

        # 显示名
        ttk.Label(form, text="显示名：").grid(
            row=row, column=0, sticky="e", padx=(0, 6), pady=3
        )
        self._name_var = tk.StringVar()
        ttk.Entry(form, textvariable=self._name_var, width=44).grid(
            row=row, column=1, sticky="we", pady=3
        )
        row += 1

        # 命令
        ttk.Label(form, text="命令：").grid(
            row=row, column=0, sticky="ne", padx=(0, 6), pady=3
        )
        self._cmd_var = tk.StringVar()
        ttk.Entry(form, textvariable=self._cmd_var, width=44).grid(
            row=row, column=1, sticky="we", pady=3
        )
        row += 1

        # 占位符帮助按钮
        ttk.Button(form, text="占位符帮助", command=self._show_placeholders).grid(
            row=row, column=1, sticky="w", pady=3
        )
        row += 1

        # 图标
        ttk.Label(form, text="图标路径：").grid(
            row=row, column=0, sticky="e", padx=(0, 6), pady=3
        )
        self._icon_var = tk.StringVar()
        ttk.Entry(form, textvariable=self._icon_var, width=44).grid(
            row=row, column=1, sticky="we", pady=3
        )
        row += 1

        # Position
        ttk.Label(form, text="Position：").grid(
            row=row, column=0, sticky="e", padx=(0, 6), pady=3
        )
        self._pos_var = tk.StringVar(value=POSITIONS[0])
        ttk.Combobox(
            form, textvariable=self._pos_var, state="readonly",
            values=POSITIONS, width=12,
        ).grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        # Extended
        ttk.Label(form, text="Extended：").grid(
            row=row, column=0, sticky="e", padx=(0, 6), pady=3
        )
        self._ext_chk_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            form, text="仅 Shift+右键显示", variable=self._ext_chk_var
        ).grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        # 级联
        ttk.Label(form, text="级联子菜单：").grid(
            row=row, column=0, sticky="ne", padx=(0, 6), pady=3
        )
        cascade_frame = ttk.Frame(form)
        cascade_frame.grid(row=row, column=1, sticky="nsew", pady=3)
        form.rowconfigure(row, weight=1)
        self._cascade_chk_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            cascade_frame, text="作为级联父项（含子命令）",
            variable=self._cascade_chk_var,
        ).pack(anchor="w")

        children_frame = ttk.Frame(cascade_frame)
        children_frame.pack(fill="both", expand=True, pady=(4, 0))
        self._children_list = tk.Listbox(children_frame, height=5, width=44)
        self._children_list.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(
            children_frame, orient="vertical", command=self._children_list.yview
        )
        sb.pack(side="left", fill="y")
        self._children_list.config(yscrollcommand=sb.set)
        btns = ttk.Frame(children_frame)
        btns.pack(side="left", padx=4)
        ttk.Button(btns, text="添加", command=self._add_child).pack(fill="x", pady=1)
        ttk.Button(btns, text="编辑", command=self._edit_child).pack(fill="x", pady=1)
        ttk.Button(btns, text="删除", command=self._del_child).pack(fill="x", pady=1)
        row += 1

        # 底部按钮
        actions = ttk.Frame(self.top)
        actions.pack(fill="x", padx=12, pady=(4, 12))
        ttk.Button(actions, text="取消", command=self._on_cancel).pack(side="right")
        ttk.Button(actions, text="确定", command=self._on_ok).pack(side="right", padx=4)

    # ── 事件 ─────────────────────────────────────────────────
    def _on_target_change(self, *args) -> None:
        is_ft = self._target_var.get() == TargetContext.FILETYPE.label
        self._ext_combo.config(state="normal" if is_ft else "disabled")

    def _refresh_children_list(self) -> None:
        self._children_list.delete(0, "end")
        for name, cmd in self._children:
            self._children_list.insert("end", f"{name}  ->  {cmd}")

    def _add_child(self) -> None:
        name, cmd = _ChildDialog.ask(self.top)
        if name is not None:
            self._children.append((name, cmd))
            self._refresh_children_list()

    def _edit_child(self) -> None:
        sel = self._children_list.curselection()
        if not sel:
            messagebox.showinfo("提示", "请先选择一个子命令", parent=self.top)
            return
        idx = sel[0]
        name, cmd = self._children[idx]
        new_name, new_cmd = _ChildDialog.ask(self.top, name, cmd)
        if new_name is not None:
            self._children[idx] = (new_name, new_cmd)
            self._refresh_children_list()

    def _del_child(self) -> None:
        sel = self._children_list.curselection()
        if not sel:
            messagebox.showinfo("提示", "请先选择一个子命令", parent=self.top)
            return
        idx = sel[0]
        del self._children[idx]
        self._refresh_children_list()

    def _show_placeholders(self) -> None:
        if self._placeholders is None:
            messagebox.showinfo("占位符帮助", "占位符模块未就绪", parent=self.top)
            return
        try:
            items = self._placeholders.describe()
        except Exception as exc:
            messagebox.showerror("错误", str(exc), parent=self.top)
            return
        text = "\n".join(f"{k}：{v}" for k, v in items) or "（无）"
        messagebox.showinfo("占位符帮助", text, parent=self.top)

    # ── 载入 ─────────────────────────────────────────────────
    def _load(self, entry: MenuEntry) -> None:
        for t, lbl in TARGET_LABELS:
            if t is entry.target:
                self._target_var.set(lbl)
                break
        if entry.target is TargetContext.FILETYPE:
            self._ext_combo.config(state="normal")
            self._ext_var.set(entry.file_type_ext or "")
        self._name_var.set(entry.display_name or "")
        self._cmd_var.set(entry.command or "")
        self._icon_var.set(entry.icon or "")
        self._pos_var.set(
            entry.position if entry.position in ("Top", "Bottom") else POSITIONS[0]
        )
        self._ext_chk_var.set(bool(entry.extended))
        if entry.kind is EntryKind.CASCADE and entry.children:
            self._cascade_chk_var.set(True)
            self._children = [
                (c.display_name or c.name, c.command or "")
                for c in entry.children
            ]
            self._refresh_children_list()

    # ── 提交 ─────────────────────────────────────────────────
    def _on_cancel(self) -> None:
        self.result = None
        self.top.destroy()

    def _on_ok(self) -> None:
        name = self._name_var.get().strip()
        if not name:
            messagebox.showwarning("校验失败", "显示名不能为空", parent=self.top)
            return

        target = None
        for t, lbl in TARGET_LABELS:
            if lbl == self._target_var.get():
                target = t
                break
        if target is None:
            messagebox.showwarning("校验失败", "请选择目标场景", parent=self.top)
            return

        file_type_ext: Optional[str] = None
        if target is TargetContext.FILETYPE:
            ext = self._ext_var.get().strip()
            if not ext:
                messagebox.showwarning(
                    "校验失败", "请填写文件类型扩展名（如 .txt）", parent=self.top
                )
                return
            file_type_ext = ext if ext.startswith(".") else "." + ext

        pos_val = self._pos_var.get()
        position = None if pos_val == POSITIONS[0] else pos_val

        is_cascade = self._cascade_chk_var.get()
        if is_cascade and not self._children:
            if not messagebox.askyesno(
                "确认",
                "已勾选级联但子命令列表为空，仍按级联保存？",
                parent=self.top,
            ):
                return

        # 构造 children MenuEntry
        children: list[MenuEntry] = []
        if is_cascade:
            for cname, ccmd in self._children:
                children.append(MenuEntry(
                    target=target,
                    scope=Scope.USER,
                    kind=EntryKind.COMMAND,
                    key_path="",
                    name=cname,
                    display_name=cname,
                    command=ccmd or None,
                    file_type_ext=file_type_ext,
                ))

        base = _target_base(target, file_type_ext)
        key_path = base + "\\" + name

        entry = MenuEntry(
            target=target,
            scope=Scope.USER,
            kind=EntryKind.CASCADE if is_cascade else EntryKind.COMMAND,
            key_path=key_path,
            name=name,
            display_name=name,
            file_type_ext=file_type_ext,
            command=self._cmd_var.get() or None,
            icon=self._icon_var.get() or None,
            position=position,
            extended=self._ext_chk_var.get(),
            clsid=None,
            children=children,
            blocked=False,
        )
        self.result = entry
        self.top.destroy()


# ── 模块级辅助 ─────────────────────────────────────────────
def _target_base(target: TargetContext, file_type_ext: Optional[str]) -> str:
    """根据 target 推断 shell 键根（用于构造 key_path 显示）。"""
    return {
        TargetContext.FILES: r"HKCR\*\shell",
        TargetContext.DIRECTORY: r"HKCR\Directory\shell",
        TargetContext.DIRECTORY_BACKGROUND: r"HKCR\Directory\Background\shell",
        TargetContext.DRIVE: r"HKCR\Drive\shell",
        TargetContext.ALLFILESYSTEMOBJECTS: r"HKCR\AllFilesystemObjects\shell",
        TargetContext.FILETYPE: rf"HKCR\{file_type_ext}\shell",
    }[target]


class _ChildDialog:
    """子命令编辑小对话框。"""

    @staticmethod
    def ask(
        parent: tk.Misc, name: str = "", cmd: str = ""
    ) -> tuple[Optional[str], Optional[str]]:
        dlg = _ChildDialog(parent, name, cmd)
        parent.wait_window(dlg.top)
        return dlg.result

    def __init__(self, parent: tk.Misc, name: str, cmd: str) -> None:
        self.result: tuple[Optional[str], Optional[str]] = (None, None)
        self.top = tk.Toplevel(parent)
        self.top.title("子命令")
        self.top.transient(parent)
        self.top.grab_set()

        form = ttk.Frame(self.top, padding=10)
        form.pack(fill="both", expand=True)
        ttk.Label(form, text="显示名：").grid(row=0, column=0, padx=4, pady=4, sticky="e")
        self._n = tk.StringVar(value=name)
        ttk.Entry(form, textvariable=self._n, width=32).grid(row=0, column=1, padx=4, pady=4)
        ttk.Label(form, text="命令：").grid(row=1, column=0, padx=4, pady=4, sticky="e")
        self._c = tk.StringVar(value=cmd)
        ttk.Entry(form, textvariable=self._c, width=32).grid(row=1, column=1, padx=4, pady=4)

        acts = ttk.Frame(self.top)
        acts.pack(fill="x", padx=10, pady=8)
        ttk.Button(acts, text="取消", command=self._cancel).pack(side="right")
        ttk.Button(acts, text="确定", command=self._ok).pack(side="right", padx=4)

    def _cancel(self) -> None:
        self.result = (None, None)
        self.top.destroy()

    def _ok(self) -> None:
        n = self._n.get().strip()
        c = self._c.get().strip()
        if not n:
            messagebox.showwarning("校验失败", "显示名不能为空", parent=self.top)
            return
        self.result = (n, c)
        self.top.destroy()
