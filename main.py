"""右键上下文菜单管理器 - 入口。

用法：
    python main.py             # 启动图形界面（非 selftest 时自动提权）
    python main.py --selftest  # 烟雾测试：构造主窗口、遍历五种分类、销毁退出

设计参考：docs/superpowers/specs/2026-07-17-context-menu-manager-design.md
"""
from __future__ import annotations

import argparse
import sys
import tkinter as tk

# 主题：clam 在各平台一致；vista 在 Windows 上更原生
_THEME = "clam"


def _apply_theme(root: tk.Tk) -> None:
    style = tk.ttk.Style(root)
    try:
        if _THEME in style.theme_names():
            style.theme_use(_THEME)
    except tk.TclError:
        pass


def selftest() -> int:
    """烟雾测试：基于真实注册表完整构建界面、遍历五种分类视图、销毁退出。

    不进入 mainloop；构造 -> update -> destroy。不提权（保持可无头测试）。
    """
    try:
        from context_menu_manager.ui.main_window import MainWindow
    except Exception as exc:  # noqa: BLE001
        print(f"[selftest] 导入主窗口失败：{exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

    root = tk.Tk()
    root.title("右键管理器 - 自检")
    root.geometry("1100x700")
    _apply_theme(root)
    try:
        win = MainWindow(root)
        win.pack(fill="both", expand=True)
        # 强制刷新事件队列，让 after(50, refresh) 跑完
        root.update()
        # 兜底：若 after 尚未触发，同步再刷一次
        win.refresh()
        root.update()

        # 遍历五种分类视图，验证都能正确渲染（每个模式至少有一个节点）
        for mode in ("target", "scope", "kind", "flat", "app"):
            win.set_classification(mode)
            root.update_idletasks()
            root.update()
            n_nodes = _count_tree_nodes(win.tree_view)
            print(f"[selftest] 分类 {mode}: {n_nodes} 个节点")
            if n_nodes == 0:
                print(f"[selftest] ERROR: 分类 {mode} 渲染为空", file=sys.stderr)
                return 3

        # 切回默认视图并选中第一个叶子节点验证详情面板
        win.set_classification("target")
        root.update()
        _select_first_leaf(win.tree_view)
        root.update()

        # 立即验证选中（在后续搜索过滤重建树之前）
        sel = win.tree_view.get_selected()
        if sel is None:
            print("[selftest] ERROR: 选中失败", file=sys.stderr)
            return 3
        print(f"[selftest] 选中：{sel.display_name} ({sel.kind.label})")
        # 详情面板应已展示该 entry
        if win.detail_panel._entry is None:  # noqa: SLF001
            print("[selftest] ERROR: 详情面板未展示选中项", file=sys.stderr)
            return 3

        # 测试搜索过滤（会重建树并清空选择）
        win.tree_view.set_search_filter("VSCode")
        root.update()
        win.tree_view.set_search_filter("")
        root.update()

        # 测试显示选项切换（隐藏已屏蔽/隐藏系统）
        win.tree_view.set_hide_blocked(True)
        root.update()
        win.tree_view.set_hide_blocked(False)
        root.update()
        win.tree_view.set_hide_system(True)
        root.update()
        win.tree_view.set_hide_system(False)
        root.update()

        # 测试按应用分类 + 合并相似项
        win.set_classification("app")
        win.tree_view.set_merge_similar(True)
        root.update()
        win.tree_view.set_merge_similar(False)
        root.update()

        # 验证 backend 模块降级提示生效
        status = win._status_var.get()  # noqa: SLF001
        print(f"[selftest] 状态栏：{status}")
    except Exception:
        import traceback
        traceback.print_exc()
        try:
            root.destroy()
        except Exception:
            pass
        return 2

    root.destroy()
    print("[selftest] OK")
    return 0


def _count_tree_nodes(tree_view) -> int:
    """统计树中所有节点数（含分组根与叶子）。"""
    try:
        tree = tree_view.tree
    except AttributeError:
        return 0
    count = 0
    def walk(node: str) -> None:
        nonlocal count
        count += 1
        for child in tree.get_children(node):
            walk(child)
    for root_id in tree.get_children():
        walk(root_id)
    return count


def _select_first_leaf(tree_view) -> None:
    """选中第一个有 MenuEntry 映射的节点（叶子或可选中项）。"""
    try:
        tree = tree_view.tree
    except AttributeError:
        return
    # 深度优先找第一个登记在 _id_to_entry 的节点
    def walk(node: str) -> bool:
        if node in tree_view._id_to_entry:  # noqa: SLF001
            tree.selection_set(node)
            tree.focus(node)
            tree.see(node)
            return True
        for child in tree.get_children(node):
            if walk(child):
                return True
        return False

    for root_id in tree.get_children():
        if walk(root_id):
            return


def main() -> int:
    parser = argparse.ArgumentParser(description="右键上下文菜单管理器")
    parser.add_argument(
        "--selftest", action="store_true",
        help="运行烟雾测试后退出（不开窗长驻）",
    )
    args = parser.parse_args()

    # --selftest 模式不提权（保持可无头测试）
    if args.selftest:
        return selftest()

    # 自动提权：非 selftest 模式下，若未提权则请求 UAC 重启自身
    from context_menu_manager import elevation
    if not elevation.is_admin():
        if elevation.request_elevation():
            # UAC 已通过，提权进程已启动；退出当前非提权进程
            # request_elevation 已透传 sys.argv（含可能的参数）
            sys.exit(0)
        # 用户拒绝 UAC 或提权失败 -> 以非提权模式继续运行
        # 状态栏会在 MainWindow 中显示"用户模式（仅用户级可编辑）"

    from context_menu_manager.ui.main_window import MainWindow
    root = tk.Tk()
    root.title("右键上下文菜单管理器")
    root.geometry("1100x700")
    _apply_theme(root)
    win = MainWindow(root)
    win.pack(fill="both", expand=True)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
