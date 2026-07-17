"""app_info.py 的测试：infer_app、group_by_app（merge 开/关）、相似度合并。"""
import unittest

from context_menu_manager import app_info
from context_menu_manager.model import (
    EntryKind, MenuEntry, Scope, TargetContext,
)


def _make_cmd(name, command, icon=None, target=TargetContext.FILES,
              scope=Scope.USER) -> MenuEntry:
    return MenuEntry(
        target=target, scope=scope, kind=EntryKind.COMMAND,
        key_path=f"HKCR\\*\\shell\\{name}", name=name,
        display_name=name, command=command, icon=icon,
    )


def _make_shellex(name, clsid, target=TargetContext.FILES,
                  scope=Scope.SYSTEM) -> MenuEntry:
    return MenuEntry(
        target=target, scope=scope, kind=EntryKind.SHELLEX,
        key_path=f"HKCR\\*\\shellex\\ContextMenuHandlers\\{name}",
        name=name, display_name=name, clsid=clsid,
    )


class TestInferApp(unittest.TestCase):
    def test_from_command(self):
        e = _make_cmd("vsc1", r'"C:\VSCode\Code.exe" "%V"')
        self.assertEqual(app_info.infer_app(e), "VSCode")

    def test_from_icon_when_no_command(self):
        e = MenuEntry(
            target=TargetContext.FILES, scope=Scope.USER,
            kind=EntryKind.COMMAND, key_path="x", name="n",
            display_name="n", command=None, icon=r"C:\Tools\notepad.exe,0",
        )
        self.assertEqual(app_info.infer_app(e), "记事本")

    def test_shellex_known_clsid(self):
        e = _make_shellex("X", "{00000000-0000-0000-0000-000000000000}")
        self.assertEqual(app_info.infer_app(e), "系统扩展")

    def test_unknown_returns_none(self):
        e = _make_cmd("unk", r'"C:\Tools\unknowntool.exe" "%V"')
        self.assertIsNone(app_info.infer_app(e))

    def test_icon_exe_name_fallback(self):
        """command 未知但 icon 含已知 exe 名时仍能推断。"""
        e = MenuEntry(
            target=TargetContext.FILES, scope=Scope.USER,
            kind=EntryKind.COMMAND, key_path="x", name="n",
            display_name="n", command="weirdwrapper %V",
            icon=r"C:\Windows\System32\cmd.exe,0",
        )
        self.assertEqual(app_info.infer_app(e), "命令提示符")


class TestGroupByApp(unittest.TestCase):
    def test_basic_grouping_no_merge(self):
        entries = [
            _make_cmd("vsc1", r'"C:\VSCode\Code.exe" "%V"',
                      target=TargetContext.FILES),
            _make_cmd("vsc2", r'"C:\VSCode\Code.exe" "%V"',
                      target=TargetContext.DIRECTORY),
            _make_cmd("7z1", "7z a archive.zip f",
                      target=TargetContext.FILES),
            _make_shellex("sx", "{00000000-0000-0000-0000-000000000000}"),
            _make_cmd("unk", "unknowntool.exe",
                      target=TargetContext.FILES),
        ]
        groups = app_info.group_by_app(entries, merge_similar=False)
        # 5 个应用分组：VSCode(2), 7-Zip(1), 系统扩展(1), 其他(1)
        self.assertEqual(len(groups), 4)
        # 按成员数降序：VSCode(2) 应在首位
        self.assertEqual(groups[0].app_name, "VSCode")
        self.assertEqual(len(groups[0].entries), 2)
        # 每个 group 的 merged 应为空
        for g in groups:
            self.assertEqual(g.merged, [])

    def test_merge_similar(self):
        entries = [
            # 同应用同命令跨 target -> 应合并
            _make_cmd("vsc1", r'"C:\VSCode\Code.exe" "%V"',
                      target=TargetContext.FILES),
            _make_cmd("vsc2", r'"C:\VSCode\Code.exe" "%V"',
                      target=TargetContext.DIRECTORY),
            _make_cmd("vsc3", r'"C:\VSCode\Code.exe" "%V"',
                      target=TargetContext.DIRECTORY_BACKGROUND),
        ]
        groups = app_info.group_by_app(entries, merge_similar=True)
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertEqual(g.app_name, "VSCode")
        # 合并为 1 个 MergedItem，含 3 个成员，3 个 target
        self.assertEqual(len(g.merged), 1)
        mi = g.merged[0]
        self.assertEqual(len(mi.members), 3)
        self.assertEqual(len(mi.targets), 3)
        # entries 仍保留全部成员
        self.assertEqual(len(g.entries), 3)

    def test_merge_different_actions_not_merged(self):
        entries = [
            _make_cmd("7z_compress", "7z a archive.zip f",
                      target=TargetContext.FILES),
            _make_cmd("7z_extract", "7z x archive.zip",
                      target=TargetContext.FILES),
        ]
        groups = app_info.group_by_app(entries, merge_similar=True)
        g = groups[0]
        self.assertEqual(g.app_name, "7-Zip")
        # 两个不同动作 -> 两个 MergedItem
        self.assertEqual(len(g.merged), 2)

    def test_merge_different_commands_not_merged(self):
        entries = [
            _make_cmd("vsc1", r'"C:\VSCode\Code.exe" "%V"',
                      target=TargetContext.FILES),
            _make_cmd("vsc2", r'"C:\VSCode\Code.exe" "%1"',
                      target=TargetContext.FILES),
        ]
        groups = app_info.group_by_app(entries, merge_similar=True)
        g = groups[0]
        # %V 与 %1 规范化后都为 %，应合并为 1 个
        self.assertEqual(len(g.merged), 1)
        self.assertEqual(len(g.merged[0].members), 2)

    def test_sort_by_member_count_desc(self):
        entries = [
            _make_cmd("a1", r'"C:\VSCode\Code.exe" "%V"'),
            _make_cmd("a2", r'"C:\VSCode\Code.exe" "%V"'),
            _make_cmd("a3", r'"C:\VSCode\Code.exe" "%V"'),
            _make_cmd("b1", "7z a x.zip f"),
        ]
        groups = app_info.group_by_app(entries, merge_similar=False)
        # VSCode(3) 在 7-Zip(1) 之前
        self.assertEqual(groups[0].app_name, "VSCode")
        self.assertEqual(len(groups[0].entries), 3)
        self.assertEqual(groups[1].app_name, "7-Zip")
        self.assertEqual(len(groups[1].entries), 1)

    def test_other_and_system_extension_groups(self):
        entries = [
            _make_cmd("unk", "unknowntool.exe"),
            _make_shellex("sx", "{00000000-0000-0000-0000-000000000000}"),
        ]
        groups = app_info.group_by_app(entries, merge_similar=False)
        names = {g.app_name for g in groups}
        self.assertIn("其他", names)
        self.assertIn("系统扩展", names)

    def test_empty_input(self):
        groups = app_info.group_by_app([], merge_similar=False)
        self.assertEqual(groups, [])
        groups2 = app_info.group_by_app([], merge_similar=True)
        self.assertEqual(groups2, [])

    def test_merge_targets_dedup(self):
        """同 target 的多个成员，targets 去重。"""
        entries = [
            _make_cmd("vsc1", r'"C:\VSCode\Code.exe" "%V"',
                      target=TargetContext.FILES),
            _make_cmd("vsc2", r'"C:\VSCode\Code.exe" "%V"',
                      target=TargetContext.FILES),
        ]
        groups = app_info.group_by_app(entries, merge_similar=True)
        mi = groups[0].merged[0]
        self.assertEqual(len(mi.members), 2)
        self.assertEqual(len(mi.targets), 1)  # 同 target 去重


if __name__ == "__main__":
    unittest.main()
