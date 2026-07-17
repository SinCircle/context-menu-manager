"""多分类树视图 - 主窗口左侧核心组件。

四种分类模式（由工具栏下拉切换）：
  * "target" 按目标位置（默认）：根节点=场景（文件/文件夹/背景/驱动器/
    文件类型展开各扩展名），下挂菜单项；级联子菜单用 children 递归
    展开为 父 -> 子。最能体现从属关系。
  * "scope"  按作用域：分"用户级（可编辑）"/"系统级（只读）"两棵子树。
  * "kind"   按项目类型：自定义命令 / Shell 扩展 / 级联子菜单。
  * "flat"   扁平列表：全部条目（含递归子项）按字母排序，搜索框实时过滤。

节点显示：图标占位 + 显示名 + 徽章（用户/系统/只读）+ 命令摘要（截断）。
对外方法：refresh() / get_selected() / set_classification(mode) /
         set_entries(entries) / set_search_filter(text)。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from ..model import EntryKind, MenuEntry, Scope, TargetContext


# 节点图标占位（Unicode 符号，避免依赖图标文件）
KIND_ICON: dict[EntryKind, str] = {
    EntryKind.COMMAND: "⚙",   # ⚙
    EntryKind.SHELLEX: "\U0001F50C",  # 🔌
    EntryKind.CASCADE: "\U0001F4C2",  # 📂
}

BADGE_USER = "用户"
BADGE_SYSTEM = "系统"
BADGE_READONLY = "只读"

# 分类下拉的 (key, 中文标签) 对，供主窗口复用
CLASSIFICATIONS: list[tuple[str, str]] = [
    ("target", "按目标位置"),
    ("scope", "按作用域"),
    ("kind", "按项目类型"),
    ("flat", "扁平列表"),
]

# 目标场景的稳定展示顺序
_TARGET_ORDER: list[TargetContext] = [
    TargetContext.FILES,
    TargetContext.DIRECTORY,
    TargetContext.DIRECTORY_BACKGROUND,
    TargetContext.DRIVE,
    TargetContext.ALLFILESYSTEMOBJECTS,
    TargetContext.FILETYPE,
]


class TreeView(ttk.Frame):
    """左侧多分类树视图。"""

    def __init__(
        self,
        master: tk.Misc,
        on_select: Optional[Callable[[Optional[MenuEntry]], None]] = None,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(master, *args, **kwargs)
        self._on_select = on_select
        self._entries: list[MenuEntry] = []
        self._mode: str = "target"
        self._filter: str = ""
        # tree item id -> MenuEntry（仅叶子/可选中节点登记）
        self._id_to_entry: dict[str, MenuEntry] = {}
        self._build_ui()

    # ── UI 构建 ───────────────────────────────────────────────
    def _build_ui(self) -> None:
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            container,
            columns=("badge", "summary"),
            show="tree headings",
            selectmode="browse",
        )
        self.tree.heading("#0", text="项目")
        self.tree.heading("badge", text="作用域")
        self.tree.heading("summary", text="命令摘要")
        self.tree.column("#0", width=280, anchor="w")
        self.tree.column("badge", width=80, anchor="center")
        self.tree.column("summary", width=220, anchor="w")

        vsb = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        # 鼠标滚轮
        self.tree.bind("<MouseWheel>", lambda e: self.tree.yview_scroll(
            int(-1 * (e.delta / 120)), "units"
        ))

    # ── 公开接口 ─────────────────────────────────────────────
    def set_entries(self, entries: list[MenuEntry]) -> None:
        """替换全部数据并按当前模式重建。"""
        self._entries = list(entries)
        self._rebuild()

    def set_classification(self, mode: str) -> None:
        """切换分类模式并重建树。"""
        if mode not in {k for k, _ in CLASSIFICATIONS}:
            return
        self._mode = mode
        self._rebuild()

    def set_search_filter(self, text: str) -> None:
        """更新搜索过滤并重建（空串=不过滤）。"""
        self._filter = (text or "").strip()
        self._rebuild()

    def get_selected(self) -> Optional[MenuEntry]:
        """返回当前选中节点对应的 MenuEntry，未选中或仅选中分组节点返回 None。"""
        sel = self.tree.selection()
        if not sel:
            return None
        return self._id_to_entry.get(sel[0])

    def refresh(self) -> None:
        """用相同数据重建（外部数据未变时调用）。"""
        self._rebuild()

    @property
    def mode(self) -> str:
        return self._mode

    # ── 重建分发 ─────────────────────────────────────────────
    def _rebuild(self) -> None:
        # 清空
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._id_to_entry.clear()
        if self._mode == "target":
            self._build_by_target()
        elif self._mode == "scope":
            self._build_by_scope()
        elif self._mode == "kind":
            self._build_by_kind()
        else:
            self._build_flat()

    # 1. 按目标位置 ─────────────────────────────────────────────
    def _build_by_target(self) -> None:
        # 按 target 分组
        by_target: dict[TargetContext, list[MenuEntry]] = {}
        for entry in self._entries:
            by_target.setdefault(entry.target, []).append(entry)

        for t in _TARGET_ORDER:
            if t is TargetContext.FILETYPE:
                continue
            entries = by_target.get(t, [])
            if not entries:
                continue
            root_id = self.tree.insert(
                "", "end",
                text=f"\U0001F4C1 {t.label}",  # 📁
                values=("", ""),
                open=True,
            )
            for entry in entries:
                if self._entry_or_descendant_matches(entry):
                    self._insert_entry(root_id, entry)

        # FILETYPE 展开各扩展名
        ft_entries = by_target.get(TargetContext.FILETYPE, [])
        for ext, group in _group_by_ext(ft_entries):
            root_id = self.tree.insert(
                "", "end",
                text=f"\U0001F4C4 文件类型 {ext}",  # 📄
                values=("", ""),
                open=True,
            )
            for entry in group:
                if self._entry_or_descendant_matches(entry):
                    self._insert_entry(root_id, entry)

    # 2. 按作用域 ───────────────────────────────────────────────
    def _build_by_scope(self) -> None:
        user_root = self.tree.insert(
            "", "end",
            text=f"\U0001F464 {Scope.USER.label}",  # 👤
            values=("", ""), open=True,
        )
        sys_root = self.tree.insert(
            "", "end",
            text=f"\U0001F512 {Scope.SYSTEM.label}",  # 🔒
            values=("", ""), open=True,
        )
        for entry in self._entries:
            if not self._entry_or_descendant_matches(entry):
                continue
            parent = user_root if entry.scope is Scope.USER else sys_root
            self._insert_entry(parent, entry)

    # 3. 按项目类型 ─────────────────────────────────────────────
    def _build_by_kind(self) -> None:
        for k in (EntryKind.COMMAND, EntryKind.CASCADE, EntryKind.SHELLEX):
            root_id = self.tree.insert(
                "", "end",
                text=f"{KIND_ICON.get(k, '•')} {k.label}",
                values=("", ""), open=True,
            )
            for entry in self._entries:
                if entry.kind is not k:
                    continue
                if self._entry_or_descendant_matches(entry):
                    self._insert_entry(root_id, entry)

    # 4. 扁平列表 ───────────────────────────────────────────────
    def _build_flat(self) -> None:
        # 扁平视图：所有条目（含级联子项递归展平）作为顶层节点，
        # 不再嵌套 children，避免同一子项既出现在父节点下又出现在顶层。
        flat = list(_flatten_entries(self._entries))
        flat.sort(key=lambda e: (e.display_name or e.name or "").lower())
        for entry in flat:
            if self._matches_leaf(entry):
                self._insert_entry("", entry, recurse=False)

    # ── 节点插入（递归 children）─────────────────────────────
    def _insert_entry(self, parent_id: str, entry: MenuEntry,
                      recurse: bool = True) -> str:
        label = self._format_label(entry)
        summary = _truncate(entry.command or "", 50)
        badge = self._format_badge(entry)
        node_id = self.tree.insert(
            parent_id, "end",
            text=label, values=(badge, summary),
            open=True,
        )
        self._id_to_entry[node_id] = entry
        if not recurse:
            return node_id
        for child in entry.children:
            # 过滤子项：在非 flat 模式下，仅展开匹配的子树
            if self._entry_or_descendant_matches(child):
                self._insert_entry(node_id, child)
        return node_id

    def _format_label(self, entry: MenuEntry) -> str:
        icon = KIND_ICON.get(entry.kind, "•")
        name = entry.display_name or entry.name or "(未命名)"
        if entry.blocked:
            name = f"[屏蔽] {name}"
        if entry.kind is EntryKind.CASCADE:
            name = f"{name} ▸"  # ▸
        return f"{icon} {name}"

    def _format_badge(self, entry: MenuEntry) -> str:
        if entry.scope is Scope.USER:
            return BADGE_USER
        if not entry.editable:
            return f"{BADGE_SYSTEM}/{BADGE_READONLY}"
        return BADGE_SYSTEM

    # ── 过滤 ─────────────────────────────────────────────────
    def _matches_leaf(self, entry: MenuEntry) -> bool:
        """叶子匹配：按 显示名/命令/key_path/CLSID 实时过滤。"""
        if not self._filter:
            return True
        q = self._filter.lower()
        haystacks = [
            entry.display_name or "",
            entry.command or "",
            entry.key_path or "",
            entry.name or "",
            entry.clsid or "",
        ]
        return any(q in h.lower() for h in haystacks)

    def _entry_or_descendant_matches(self, entry: MenuEntry) -> bool:
        """非 flat 模式下：自身或任一后代命中过滤则保留该分支。"""
        if self._matches_leaf(entry):
            return True
        for child in entry.children:
            if self._entry_or_descendant_matches(child):
                return True
        return False

    def _on_tree_select(self, event: Optional[tk.Event] = None) -> None:
        if self._on_select is None:
            return
        self._on_select(self.get_selected())


# ── 模块级辅助 ─────────────────────────────────────────────
def _truncate(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"  # …


def _group_by_ext(entries: list[MenuEntry]):
    """按 file_type_ext 分组并按扩展名排序返回 (ext, list)。"""
    groups: dict[str, list[MenuEntry]] = {}
    for e in entries:
        ext = e.file_type_ext or "(无)"
        groups.setdefault(ext, []).append(e)
    for ext in sorted(groups.keys()):
        yield ext, groups[ext]


def _flatten_entries(entries: list[MenuEntry]):
    """递归展平，含父子全部节点（用于扁平视图）。"""
    for e in entries:
        yield e
        if e.children:
            yield from _flatten_entries(e.children)
