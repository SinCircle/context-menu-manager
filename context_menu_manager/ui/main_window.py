"""主窗口：顶部工具栏 + 左侧树视图 + 右侧详情面板 + 底部状态栏。

布局：
  ┌──────────────────────────────────────────────────────────┐
  │ 工具栏：[分类方式][搜索框] 新建 编辑 删除 屏蔽 定位 定位 备份 刷新 刷新│
  │ 选项栏：[合并相似项] [隐藏已屏蔽项] [隐藏系统项]          │
  ├──────────────────────┬───────────────────────────────────┤
  │  TreeView（五分类）  │  DetailPanel（详情/编辑）         │
  │                      │                                   │
  ├──────────────────────┴───────────────────────────────────┤
  │ 状态栏（管理员/用户模式 + 加载状态 + 后端降级提示）        │
  └──────────────────────────────────────────────────────────┘

后端模块（placeholders/backup/explorer/command_info/app_info）用 guarded import
保护，未就绪时禁用相关按钮并在状态栏提示。
权限判定统一用 elevation.can_edit / can_delete / can_block。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from .. import elevation, registry
from ..model import EntryKind, MenuEntry, TargetContext
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
        self._command_info = _try_import("command_info")
        self._app_info = _try_import("app_info")
        # 提权状态（启动时快照）
        self._is_admin = elevation.is_admin()

        self._classify_mode: str = "target"
        self._build_ui()
        # 首次加载（STUB 同步很快；真实后端读 HKCR 通常亚秒级）
        self.after(50, self.refresh)
        self._update_backend_status()

    # ── UI 构建 ───────────────────────────────────────────────
    def _build_ui(self) -> None:
        # 顶部工具栏（主操作）
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

        # 主操作按钮
        for text, cmd in [
            ("新建", self.on_new),
            ("编辑", self.on_edit),
            ("删除", self.on_delete),
            ("屏蔽", self.on_block_toggle),
            ("定位到注册表", self.on_locate_reg),
            ("定位到文件", self.on_locate_file),
            ("备份管理", self.on_backup),
            ("刷新", self.refresh),
            ("刷新资源管理器", self.on_refresh_explorer),
        ]:
            btn = ttk.Button(toolbar, text=text, command=cmd)
            btn.pack(side="left", padx=2)
            if text == "屏蔽":
                self._block_btn = btn
        # 初始无选中 -> 屏蔽按钮禁用
        self._block_btn.config(state="disabled")

        # 选项栏（显示选项 + 合并相似项）
        options = ttk.Frame(self, padding=(8, 0, 8, 4))
        options.pack(side="top", fill="x")

        self._merge_var = tk.BooleanVar(value=False)
        self._merge_chk = ttk.Checkbutton(
            options, text="合并相似项",
            variable=self._merge_var,
            command=self._on_merge_changed,
        )
        self._merge_chk.pack(side="left")
        # 仅 app 模式下启用
        self._merge_chk.config(state="disabled")

        self._hide_blocked_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            options, text="隐藏已屏蔽项",
            variable=self._hide_blocked_var,
            command=self._on_hide_blocked_changed,
        ).pack(side="left", padx=(16, 0))

        self._hide_system_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            options, text="隐藏系统项",
            variable=self._hide_system_var,
            command=self._on_hide_system_changed,
        ).pack(side="left", padx=(16, 0))

        # 中间 PanedWindow：左树 + 右详情
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(side="top", fill="both", expand=True, padx=8, pady=4)

        self.tree_view = TreeView(
            paned, on_select=self._on_tree_select,
            app_info=self._app_info,
            command_info=self._command_info,
        )
        paned.add(self.tree_view, weight=2)

        self.detail_panel = DetailPanel(
            paned,
            placeholders=self._placeholders,
            command_info=self._command_info,
            on_save=self._on_detail_save,
        )
        paned.add(self.detail_panel, weight=3)

        # 底部状态栏
        self._status_var = tk.StringVar(value=self._initial_status())
        status = ttk.Label(
            self, textvariable=self._status_var,
            relief="sunken", anchor="w", padding=(6, 2),
        )
        status.pack(side="bottom", fill="x")

    # ── 状态栏 ───────────────────────────────────────────────
    def _initial_status(self) -> str:
        base = "管理员模式" if self._is_admin else "用户模式（仅用户级可编辑）"
        return base

    def _mode_label(self) -> str:
        return "管理员模式" if self._is_admin else "用户模式（仅用户级可编辑）"

    def _backend_missing(self) -> list[str]:
        missing: list[str] = []
        if self._placeholders is None:
            missing.append("placeholders")
        if self._backup is None:
            missing.append("backup")
        if self._explorer is None:
            missing.append("explorer")
        if self._command_info is None:
            missing.append("command_info")
        if self._app_info is None:
            missing.append("app_info")
        return missing

    def set_status(self, text: str) -> None:
        self._status_var.set(text)

    def _update_backend_status(self) -> None:
        missing = self._backend_missing()
        if missing:
            self.set_status(
                f"{self._mode_label()} | 后端模块未就绪："
                f"{', '.join(missing)}（相关功能已禁用）"
            )
        else:
            self.set_status(self._mode_label())

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
        # 重置屏蔽按钮
        self._block_btn.config(text="屏蔽", state="disabled")

        # 状态栏：加载状态 + 提权模式 + 后端降级提示
        status = f"已加载 {len(entries)} 条 | {self._mode_label()}"
        missing = self._backend_missing()
        if missing:
            status += f" | 后端未就绪：{', '.join(missing)}"
        self.set_status(status)

    def _on_load_error(self, exc: Exception) -> None:
        self.set_status(f"{self._mode_label()} | 加载失败：{exc}")
        messagebox.showerror("加载失败", str(exc), parent=self)

    # ── 分类与搜索 ───────────────────────────────────────────
    def _on_class_changed(self, event: Optional[tk.Event] = None) -> None:
        label = self._class_var.get()
        for key, lbl in CLASSIFICATIONS:
            if lbl == label:
                self._classify_mode = key
                self.tree_view.set_classification(key)
                self._update_merge_state()
                return

    def set_classification(self, mode: str) -> None:
        """供外部（如 selftest）调用切换分类。"""
        for key, lbl in CLASSIFICATIONS:
            if key == mode:
                self._class_var.set(lbl)
                self._classify_mode = mode
                self.tree_view.set_classification(mode)
                self._update_merge_state()
                return

    def _update_merge_state(self) -> None:
        """合并相似项复选框仅在 app 模式下启用。"""
        if self._classify_mode == "app":
            self._merge_chk.config(state="normal")
        else:
            self._merge_chk.config(state="disabled")

    def _on_search_changed(self, *args) -> None:
        self.tree_view.set_search_filter(self._search_var.get())

    def _on_merge_changed(self) -> None:
        self.tree_view.set_merge_similar(self._merge_var.get())

    def _on_hide_blocked_changed(self) -> None:
        self.tree_view.set_hide_blocked(self._hide_blocked_var.get())

    def _on_hide_system_changed(self) -> None:
        self.tree_view.set_hide_system(self._hide_system_var.get())

    # ── 树选择 ───────────────────────────────────────────────
    def _on_tree_select(self, entry: Optional[MenuEntry]) -> None:
        self.detail_panel.show_entry(entry)
        if entry is None:
            self.set_status(f"{self._mode_label()} | 未选中")
            self._block_btn.config(text="屏蔽", state="disabled")
        else:
            scope_tag = "可编辑" if elevation.can_edit(entry) else "只读"
            block_tag = "（已屏蔽）" if entry.blocked else ""
            self.set_status(
                f"{self._mode_label()} | 已选中："
                f"{entry.display_name}（{scope_tag}）{block_tag}"
            )
            # 屏蔽按钮：文本与启用状态
            if entry.blocked:
                self._block_btn.config(text="启用")
            else:
                self._block_btn.config(text="屏蔽")
            self._block_btn.config(
                state="normal" if elevation.can_block(entry) else "disabled"
            )

    # ── 操作：新建 ───────────────────────────────────────────
    def on_new(self) -> None:
        dlg = EditDialog(self.winfo_toplevel(), entry=None,
                         placeholders=self._placeholders)
        self.winfo_toplevel().wait_window(dlg.top)
        if dlg.result is None:
            return
        try:
            registry.create_entry(dlg.result)
            self.set_status(f"{self._mode_label()} | 已新建：{dlg.result.display_name}")
            self.refresh()
            self._maybe_notify_shell()
        except registry.RegistryError as exc:
            messagebox.showerror("新建失败", str(exc), parent=self)
            self.set_status(f"{self._mode_label()} | 新建失败：{exc}")
        except Exception as exc:
            messagebox.showerror("新建失败", str(exc), parent=self)
            self.set_status(f"{self._mode_label()} | 新建失败：{exc}")

    # ── 操作：编辑 ───────────────────────────────────────────
    def on_edit(self) -> None:
        entry = self.tree_view.get_selected()
        if entry is None:
            messagebox.showinfo("提示", "请先选择一项", parent=self)
            return
        if not elevation.can_edit(entry):
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
            self.set_status(f"{self._mode_label()} | 已更新：{dlg.result.display_name}")
            self.refresh()
            self._maybe_notify_shell()
        except registry.RegistryError as exc:
            messagebox.showerror("更新失败", str(exc), parent=self)
            self.set_status(f"{self._mode_label()} | 更新失败：{exc}")
        except Exception as exc:
            messagebox.showerror("更新失败", str(exc), parent=self)
            self.set_status(f"{self._mode_label()} | 更新失败：{exc}")

    # ── 操作：删除 ───────────────────────────────────────────
    def on_delete(self) -> None:
        entry = self.tree_view.get_selected()
        if entry is None:
            messagebox.showinfo("提示", "请先选择一项", parent=self)
            return
        if not elevation.can_delete(entry):
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
            self.set_status(f"{self._mode_label()} | 已删除：{entry.display_name}")
            self.refresh()
            self._maybe_notify_shell()
        except registry.RegistryError as exc:
            messagebox.showerror("删除失败", str(exc), parent=self)
            self.set_status(f"{self._mode_label()} | 删除失败：{exc}")
        except Exception as exc:
            messagebox.showerror("删除失败", str(exc), parent=self)
            self.set_status(f"{self._mode_label()} | 删除失败：{exc}")

    # ── 操作：屏蔽/启用 ──────────────────────────────────────
    def on_block_toggle(self) -> None:
        entry = self.tree_view.get_selected()
        if entry is None:
            messagebox.showinfo("提示", "请先选择一项", parent=self)
            return
        if not elevation.can_block(entry):
            messagebox.showinfo(
                "不可操作", "该项无法屏蔽（系统级且未提权）", parent=self
            )
            return
        try:
            if entry.blocked:
                registry.unblock_entry(entry)
                action = "已启用"
            else:
                registry.block_entry(entry)
                action = "已屏蔽"
            self.set_status(
                f"{self._mode_label()} | {action}：{entry.display_name}"
            )
            self.refresh()
            self._maybe_notify_shell()
            # Shell 扩展的屏蔽/启用需重启资源管理器才生效（Blocked 列表仅重启时重读）
            if entry.kind is EntryKind.SHELLEX and self._explorer is not None:
                if messagebox.askyesno(
                    "需要重启资源管理器",
                    "Shell 扩展的屏蔽/启用需要重启资源管理器才能生效。\n"
                    "是否立即重启？（已打开的文件夹窗口会关闭）",
                    parent=self,
                ):
                    try:
                        self._explorer.restart_explorer()
                    except Exception as exc:
                        messagebox.showerror("重启失败", str(exc), parent=self)
        except registry.RegistryError as exc:
            messagebox.showerror("操作失败", str(exc), parent=self)
            self.set_status(f"{self._mode_label()} | 操作失败：{exc}")
        except Exception as exc:
            messagebox.showerror("操作失败", str(exc), parent=self)
            self.set_status(f"{self._mode_label()} | 操作失败：{exc}")

    # ── 操作：定位到注册表 ───────────────────────────────────
    def on_locate_reg(self) -> None:
        entry = self.tree_view.get_selected()
        if entry is None:
            messagebox.showinfo("提示", "请先选择一项", parent=self)
            return
        func = getattr(self._explorer, "open_in_regedit", None) \
            if self._explorer is not None else None
        if func is None:
            messagebox.showinfo(
                "后端未就绪",
                "explorer 模块未提供 open_in_regedit 功能",
                parent=self,
            )
            self.set_status(f"{self._mode_label()} | 定位功能未就绪")
            return
        try:
            func(entry.key_path)
            self.set_status(
                f"{self._mode_label()} | 已打开注册表：{entry.key_path}"
            )
        except Exception as exc:
            messagebox.showerror("定位失败", str(exc), parent=self)
            self.set_status(f"{self._mode_label()} | 定位失败：{exc}")

    # ── 操作：定位到文件 ─────────────────────────────────────
    def on_locate_file(self) -> None:
        entry = self.tree_view.get_selected()
        if entry is None:
            messagebox.showinfo("提示", "请先选择一项", parent=self)
            return
        func = getattr(self._explorer, "open_in_explorer", None) \
            if self._explorer is not None else None
        if func is None:
            messagebox.showinfo(
                "后端未就绪",
                "explorer 模块未提供 open_in_explorer 功能",
                parent=self,
            )
            self.set_status(f"{self._mode_label()} | 定位功能未就绪")
            return
        if self._command_info is None:
            messagebox.showinfo(
                "后端未就绪",
                "command_info 模块未就绪，无法解析命令",
                parent=self,
            )
            self.set_status(f"{self._mode_label()} | command_info 未就绪")
            return
        try:
            info = self._command_info.parse_command(entry.command)
        except Exception:
            info = None
        exe_path = getattr(info, "exe_path", None) if info is not None else None
        if not exe_path:
            messagebox.showinfo(
                "无法定位", "未能从命令中解析可执行文件路径", parent=self
            )
            self.set_status(f"{self._mode_label()} | 未能解析可执行文件路径")
            return
        try:
            func(exe_path)
            self.set_status(
                f"{self._mode_label()} | 已定位文件：{exe_path}"
            )
        except Exception as exc:
            messagebox.showerror("定位失败", str(exc), parent=self)
            self.set_status(f"{self._mode_label()} | 定位失败：{exc}")

    # ── 操作：备份管理 ───────────────────────────────────────
    def on_backup(self) -> None:
        if self._backup is None:
            messagebox.showinfo(
                "后端未就绪", "backup 模块未就绪，备份功能已禁用", parent=self
            )
            self.set_status(f"{self._mode_label()} | backup 模块未就绪")
            return
        dlg = BackupDialog(self.winfo_toplevel(), backup_mod=self._backup)
        self.winfo_toplevel().wait_window(dlg.top)

    # ── 操作：刷新资源管理器 ─────────────────────────────────
    def on_refresh_explorer(self) -> None:
        if self._explorer is None:
            messagebox.showinfo(
                "后端未就绪", "explorer 模块未就绪，刷新功能已禁用", parent=self
            )
            self.set_status(f"{self._mode_label()} | explorer 模块未就绪")
            return
        try:
            self._explorer.notify_shell()
            self.set_status(f"{self._mode_label()} | 已通知资源管理器刷新关联")
        except Exception as exc:
            messagebox.showerror("刷新失败", str(exc), parent=self)
            self.set_status(f"{self._mode_label()} | 刷新失败：{exc}")

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
            self.set_status(f"{self._mode_label()} | 已保存：{entry.display_name}")
            self.refresh()
            self._maybe_notify_shell()
        except registry.RegistryError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            self.set_status(f"{self._mode_label()} | 保存失败：{exc}")
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            self.set_status(f"{self._mode_label()} | 保存失败：{exc}")
