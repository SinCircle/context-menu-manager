"""主窗口：顶部工具栏 + 左侧树视图 + 右侧详情面板 + 底部状态栏。

布局：
  ┌──────────────────────────────────────────────────────────┐
  │ 工具栏：[分类方式][搜索框] 新建 编辑 删除 备份管理 刷新 刷新 │
  ├──────────────────────┬───────────────────────────────────┤
  │  TreeView（多分类）  │  DetailPanel（详情/编辑）         │
  │                      │                                   │
  ├──────────────────────┴───────────────────────────────────┤
  │ 状态栏                                                    │
  └──────────────────────────────────────────────────────────┘

后端模块（placeholders/backup/explorer）用 guarded import 保护，
未就绪时禁用相关按钮并在状态栏提示。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from .. import registry
from ..model import MenuEntry, TargetContext
from .tree_view import CLASSIFICATIONS, TreeView
from .detail_panel import DetailPanel
from .edit_dialog import EditDialog
from .backup_dialog import BackupDialog


def _try_import(module_name: str):
    """guarded import：后端模块未就绪时返回 None。"""
    try:
        import importlib
        return importlib.import_module(f"context_menu_manager.{module_name}")
    except Exception:
        return None


class MainWindow(ttk.Frame):
    """主窗口组件（pack 进 tk.Tk 或 Toplevel）。"""

    def __init__(self, master: tk.Misc, *args, **kwargs) -> None:
        super().__init__(master, *args, **kwargs)
        # 后端模块：guarded import
        self._explorer = _try_import("explorer")
        self._backup = _try_import("backup")
        self._placeholders = _try_import("placeholders")

        self._classify_mode: str = "target"
        self._build_ui()
        # 首次加载（STUB 同步很快；真实后端读 HKCR 通常亚秒级）
        self.after(50, self.refresh)
        self._update_backend_status()

    # ── UI 构建 ───────────────────────────────────────────────
    def _build_ui(self) -> None:
        # 顶部工具栏
        toolbar = ttk.Frame(self, padding=(8, 6))
        toolbar.pack(side="top", fill="x")

        ttk.Label(toolbar, text="分类方式：").pack(side="left")
        self._class_var = tk.StringVar(value=CLASSIFICATIONS[0][1])
        class_combo = ttk.Combobox(
            toolbar, textvariable=self._class_var, state="readonly",
            values=[lbl for _, lbl in CLASSIFICATIONS], width=14,
        )
        class_combo.pack(side="left", padx=(4, 16))
        class_combo.bind("<<ComboboxSelected>>", self._on_class_changed)

        ttk.Label(toolbar, text="搜索：").pack(side="left")
        self._search_var = tk.StringVar()
        search_entry = ttk.Entry(toolbar, textvariable=self._search_var, width=24)
        search_entry.pack(side="left", padx=(4, 16))
        self._search_var.trace_add("write", self._on_search_changed)

        for text, cmd in [
            ("新建", self.on_new),
            ("编辑", self.on_edit),
            ("删除", self.on_delete),
            ("备份管理", self.on_backup),
            ("刷新", self.refresh),
            ("刷新资源管理器", self.on_refresh_explorer),
        ]:
            ttk.Button(toolbar, text=text, command=cmd).pack(side="left", padx=2)

        # 中间 PanedWindow：左树 + 右详情
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(side="top", fill="both", expand=True, padx=8, pady=4)

        self.tree_view = TreeView(paned, on_select=self._on_tree_select)
        paned.add(self.tree_view, weight=2)

        self.detail_panel = DetailPanel(
            paned,
            placeholders=self._placeholders,
            on_save=self._on_detail_save,
        )
        paned.add(self.detail_panel, weight=3)

        # 底部状态栏
        self._status_var = tk.StringVar(value="就绪")
        status = ttk.Label(
            self, textvariable=self._status_var,
            relief="sunken", anchor="w", padding=(6, 2),
        )
        status.pack(side="bottom", fill="x")

    # ── 状态栏 ───────────────────────────────────────────────
    def set_status(self, text: str) -> None:
        self._status_var.set(text)

    def _update_backend_status(self) -> None:
        missing: list[str] = []
        if self._placeholders is None:
            missing.append("placeholders")
        if self._backup is None:
            missing.append("backup")
        if self._explorer is None:
            missing.append("explorer")
        if missing:
            self.set_status(f"后端模块未就绪：{', '.join(missing)}（相关功能已禁用）")

    # ── 数据加载（同步；STUB 即时）────────────────────────────
    def refresh(self) -> None:
        """重新拉取 registry 数据并重建树。"""
        self.set_status("正在加载...")
        try:
            entries: list[MenuEntry] = []
            for target in registry.enum_targets():
                entries.extend(registry.list_entries(target))
            for ext in registry.list_file_types():
                entries.extend(registry.list_entries(TargetContext.FILETYPE, ext))
        except registry.RegistryError as exc:
            self._on_load_error(exc)
            return
        except Exception as exc:
            self._on_load_error(exc)
            return

        self.tree_view.set_entries(entries)
        self.tree_view.set_classification(self._classify_mode)
        # 清空详情面板（选择已失效）
        self.detail_panel.show_entry(None)
        self.set_status(f"已加载 {len(entries)} 条")
        if self._placeholders is None or self._backup is None or self._explorer is None:
            missing: list[str] = []
            if self._placeholders is None:
                missing.append("placeholders")
            if self._backup is None:
                missing.append("backup")
            if self._explorer is None:
                missing.append("explorer")
            self.set_status(
                f"已加载 {len(entries)} 条 | 后端未就绪：{', '.join(missing)}"
            )

    def _on_load_error(self, exc: Exception) -> None:
        self.set_status(f"加载失败：{exc}")
        messagebox.showerror("加载失败", str(exc), parent=self)

    # ── 分类与搜索 ───────────────────────────────────────────
    def _on_class_changed(self, event: Optional[tk.Event] = None) -> None:
        label = self._class_var.get()
        for key, lbl in CLASSIFICATIONS:
            if lbl == label:
                self._classify_mode = key
                self.tree_view.set_classification(key)
                return

    def set_classification(self, mode: str) -> None:
        """供外部（如 selftest）调用切换分类。"""
        for key, lbl in CLASSIFICATIONS:
            if key == mode:
                self._class_var.set(lbl)
                self._classify_mode = mode
                self.tree_view.set_classification(mode)
                return

    def _on_search_changed(self, *args) -> None:
        self.tree_view.set_search_filter(self._search_var.get())

    # ── 树选择 ───────────────────────────────────────────────
    def _on_tree_select(self, entry: Optional[MenuEntry]) -> None:
        self.detail_panel.show_entry(entry)
        if entry is None:
            self.set_status("未选中")
        else:
            scope_tag = "用户" if entry.editable else "只读"
            self.set_status(f"已选中：{entry.display_name}（{scope_tag}）")

    # ── 操作：新建 ───────────────────────────────────────────
    def on_new(self) -> None:
        dlg = EditDialog(self.winfo_toplevel(), entry=None,
                         placeholders=self._placeholders)
        self.winfo_toplevel().wait_window(dlg.top)
        if dlg.result is None:
            return
        try:
            registry.create_entry(dlg.result)
            self.set_status(f"已新建：{dlg.result.display_name}")
            self.refresh()
            self._maybe_notify_shell()
        except registry.RegistryError as exc:
            messagebox.showerror("新建失败", str(exc), parent=self)
            self.set_status(f"新建失败：{exc}")
        except Exception as exc:
            messagebox.showerror("新建失败", str(exc), parent=self)
            self.set_status(f"新建失败：{exc}")

    # ── 操作：编辑 ───────────────────────────────────────────
    def on_edit(self) -> None:
        entry = self.tree_view.get_selected()
        if entry is None:
            messagebox.showinfo("提示", "请先选择一项", parent=self)
            return
        if not entry.editable:
            messagebox.showinfo(
                "不可编辑", "该项为系统/只读，不可编辑", parent=self
            )
            return
        dlg = EditDialog(self.winfo_toplevel(), entry=entry,
                         placeholders=self._placeholders)
        self.winfo_toplevel().wait_window(dlg.top)
        if dlg.result is None:
            return
        try:
            registry.update_entry(dlg.result)
            self.set_status(f"已更新：{dlg.result.display_name}")
            self.refresh()
            self._maybe_notify_shell()
        except registry.RegistryError as exc:
            messagebox.showerror("更新失败", str(exc), parent=self)
            self.set_status(f"更新失败：{exc}")
        except Exception as exc:
            messagebox.showerror("更新失败", str(exc), parent=self)
            self.set_status(f"更新失败：{exc}")

    # ── 操作：删除 ───────────────────────────────────────────
    def on_delete(self) -> None:
        entry = self.tree_view.get_selected()
        if entry is None:
            messagebox.showinfo("提示", "请先选择一项", parent=self)
            return
        if not entry.editable:
            messagebox.showinfo(
                "不可删除", "该项为系统/只读，不可删除", parent=self
            )
            return
        if not messagebox.askyesno(
            "确认删除",
            f"确定要删除「{entry.display_name}」吗？\n"
            f"键：{entry.key_path}\n（建议先备份受影响分支）",
            parent=self,
        ):
            return
        try:
            registry.delete_entry(entry.key_path)
            self.set_status(f"已删除：{entry.display_name}")
            self.refresh()
            self._maybe_notify_shell()
        except registry.RegistryError as exc:
            messagebox.showerror("删除失败", str(exc), parent=self)
            self.set_status(f"删除失败：{exc}")
        except Exception as exc:
            messagebox.showerror("删除失败", str(exc), parent=self)
            self.set_status(f"删除失败：{exc}")

    # ── 操作：备份管理 ───────────────────────────────────────
    def on_backup(self) -> None:
        if self._backup is None:
            messagebox.showinfo(
                "后端未就绪", "backup 模块未就绪，备份功能已禁用", parent=self
            )
            self.set_status("backup 模块未就绪")
            return
        dlg = BackupDialog(self.winfo_toplevel(), backup_mod=self._backup)
        self.winfo_toplevel().wait_window(dlg.top)

    # ── 操作：刷新资源管理器 ─────────────────────────────────
    def on_refresh_explorer(self) -> None:
        if self._explorer is None:
            messagebox.showinfo(
                "后端未就绪", "explorer 模块未就绪，刷新功能已禁用", parent=self
            )
            self.set_status("explorer 模块未就绪")
            return
        try:
            self._explorer.notify_shell()
            self.set_status("已通知资源管理器刷新关联")
        except Exception as exc:
            messagebox.showerror("刷新失败", str(exc), parent=self)
            self.set_status(f"刷新失败：{exc}")

    def _maybe_notify_shell(self) -> None:
        if self._explorer is None:
            return
        try:
            self._explorer.notify_shell()
        except Exception:
            pass  # 静默失败：写操作已成功，刷新失败不阻塞流程

    # ── 详情面板保存 ─────────────────────────────────────────
    def _on_detail_save(self, entry: MenuEntry) -> None:
        try:
            registry.update_entry(entry)
            self.set_status(f"已保存：{entry.display_name}")
            self.refresh()
            self._maybe_notify_shell()
        except registry.RegistryError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            self.set_status(f"保存失败：{exc}")
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            self.set_status(f"保存失败：{exc}")
