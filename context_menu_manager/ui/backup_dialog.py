"""备份管理对话框。

列出 list_backups()，每条带"还原"/"删除"；
"立即备份"按钮调 backup_all(enum_targets())；
还原调 restore_from(reg_file)。操作后刷新列表。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from .. import registry


class BackupDialog:
    """备份管理 Toplevel。"""

    def __init__(self, parent: tk.Misc, backup_mod) -> None:
        self._mod = backup_mod
        self._id_to_backup: dict[str, object] = {}

        self.top = tk.Toplevel(parent)
        self.top.title("备份管理")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.geometry("720x440")

        self._build_ui()
        self._refresh()

    # ── UI ───────────────────────────────────────────────────
    def _build_ui(self) -> None:
        top = ttk.Frame(self.top, padding=8)
        top.pack(fill="x")
        ttk.Button(top, text="立即备份", command=self._backup_now).pack(side="left")
        ttk.Button(top, text="刷新列表", command=self._refresh).pack(side="left", padx=4)
        ttk.Label(
            top, text="还原会覆盖当前注册表相关分支，请先关闭其他注册表编辑器",
            foreground="#888",
        ).pack(side="left", padx=8)

        body = ttk.Frame(self.top)
        body.pack(fill="both", expand=True, padx=8, pady=4)
        cols = ("name", "created_at", "targets", "path")
        self.tree = ttk.Treeview(
            body, columns=cols, show="headings", selectmode="browse"
        )
        self.tree.heading("name", text="名称")
        self.tree.heading("created_at", text="创建时间")
        self.tree.heading("targets", text="目标")
        self.tree.heading("path", text="路径")
        self.tree.column("name", width=160)
        self.tree.column("created_at", width=160)
        self.tree.column("targets", width=180)
        self.tree.column("path", width=240)
        vsb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._restore())

        acts = ttk.Frame(self.top, padding=8)
        acts.pack(fill="x", side="bottom")
        ttk.Button(acts, text="还原", command=self._restore).pack(side="left")
        ttk.Button(acts, text="删除", command=self._delete).pack(side="left", padx=4)
        ttk.Button(acts, text="关闭", command=self.top.destroy).pack(side="right")

    # ── 列表 ─────────────────────────────────────────────────
    def _refresh(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._id_to_backup.clear()
        try:
            backups = self._mod.list_backups()
        except Exception as exc:
            messagebox.showerror("读取备份失败", str(exc), parent=self.top)
            return
        for b in backups:
            targets = ", ".join(getattr(b, "targets", []) or [])
            iid = self.tree.insert(
                "", "end",
                values=(b.name, b.created_at, targets, str(b.path)),
            )
            self._id_to_backup[iid] = b

    def _selected_backup(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择一项", parent=self.top)
            return None
        b = self._id_to_backup.get(sel[0])
        if b is None:
            messagebox.showinfo("提示", "请先选择一项", parent=self.top)
        return b

    # ── 操作 ─────────────────────────────────────────────────
    def _backup_now(self) -> None:
        try:
            targets = registry.enum_targets()
            path = self._mod.backup_all(targets)
            messagebox.showinfo("备份完成", f"已备份至：\n{path}", parent=self.top)
        except Exception as exc:
            messagebox.showerror("备份失败", str(exc), parent=self.top)
        self._refresh()

    def _restore(self) -> None:
        b = self._selected_backup()
        if b is None:
            return
        if not messagebox.askyesno(
            "确认还原",
            f"确定还原备份「{b.name}」吗？\n将覆盖当前注册表相关分支。",
            parent=self.top,
        ):
            return
        try:
            self._mod.restore_from(b.path)
            messagebox.showinfo("还原完成", "已还原，建议刷新资源管理器", parent=self.top)
        except Exception as exc:
            messagebox.showerror("还原失败", str(exc), parent=self.top)

    def _delete(self) -> None:
        b = self._selected_backup()
        if b is None:
            return
        if not messagebox.askyesno(
            "确认删除", f"确定删除备份「{b.name}」吗？", parent=self.top
        ):
            return
        try:
            self._mod.delete_backup(b.name)
        except Exception as exc:
            messagebox.showerror("删除失败", str(exc), parent=self.top)
        self._refresh()
