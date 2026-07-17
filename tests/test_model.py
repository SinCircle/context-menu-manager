"""model.py 的测试：to_dict 序列化、editable 属性（类型判定）、children 默认值。"""
import unittest
from unittest import mock

from context_menu_manager import elevation
from context_menu_manager.model import (
    EntryKind, MenuEntry, Scope, TargetContext,
)


class TestMenuEntry(unittest.TestCase):
    def test_to_dict_contains_all_fields(self):
        child = MenuEntry(
            target=TargetContext.FILES, scope=Scope.USER,
            kind=EntryKind.COMMAND,
            key_path=r"HKCR\*\shell\Child", name="Child",
            display_name="子项", command="notepad.exe %1",
        )
        e = MenuEntry(
            target=TargetContext.DIRECTORY, scope=Scope.USER,
            kind=EntryKind.CASCADE,
            key_path=r"HKCR\Directory\shell\Parent", name="Parent",
            display_name="父项", icon="a.exe,0", position="Top",
            extended=True, children=[child],
        )
        d = e.to_dict()
        self.assertEqual(d["target"], "directory")
        self.assertEqual(d["scope"], "user")
        self.assertEqual(d["kind"], "cascade")
        self.assertEqual(d["key_path"], r"HKCR\Directory\shell\Parent")
        self.assertEqual(d["name"], "Parent")
        self.assertEqual(d["display_name"], "父项")
        self.assertEqual(d["icon"], "a.exe,0")
        self.assertEqual(d["position"], "Top")
        self.assertTrue(d["extended"])
        self.assertIsNone(d["command"])
        self.assertIsNone(d["clsid"])
        self.assertFalse(d["blocked"])
        self.assertEqual(len(d["children"]), 1)
        self.assertEqual(d["children"][0]["name"], "Child")
        self.assertEqual(d["children"][0]["command"], "notepad.exe %1")

    def test_editable_user_command(self):
        e = MenuEntry(
            target=TargetContext.FILES, scope=Scope.USER,
            kind=EntryKind.COMMAND,
            key_path="x", name="n", display_name="d",
        )
        # editable 现为类型判定：COMMAND 不论 scope 都可编辑
        self.assertTrue(e.editable)

    def test_editable_is_type_based(self):
        """editable 现为类型判定（kind != SHELLEX），与 scope 无关。"""
        # SYSTEM scope 的 COMMAND 仍可编辑（作用域判定改由 elevation.can_edit 负责）
        e_sys_cmd = MenuEntry(
            target=TargetContext.FILES, scope=Scope.SYSTEM,
            kind=EntryKind.COMMAND,
            key_path="x", name="n", display_name="d",
        )
        self.assertTrue(e_sys_cmd.editable)
        # USER scope 的 CASCADE 也可编辑
        e_user_cas = MenuEntry(
            target=TargetContext.FILES, scope=Scope.USER,
            kind=EntryKind.CASCADE,
            key_path="x", name="n", display_name="d",
        )
        self.assertTrue(e_user_cas.editable)
        # SYSTEM scope 的 CASCADE 也可编辑（类型上）
        e_sys_cas = MenuEntry(
            target=TargetContext.FILES, scope=Scope.SYSTEM,
            kind=EntryKind.CASCADE,
            key_path="x", name="n", display_name="d",
        )
        self.assertTrue(e_sys_cas.editable)

    def test_not_editable_shellex(self):
        e = MenuEntry(
            target=TargetContext.FILES, scope=Scope.USER,
            kind=EntryKind.SHELLEX,
            key_path="x", name="n", display_name="d",
            clsid="{00000000-0000-0000-0000-000000000000}",
        )
        # SHELLEX 不论 scope 都不可编辑
        self.assertFalse(e.editable)

    def test_not_editable_shellex_system(self):
        e = MenuEntry(
            target=TargetContext.FILES, scope=Scope.SYSTEM,
            kind=EntryKind.SHELLEX,
            key_path="x", name="n", display_name="d",
            clsid="{00000000-0000-0000-0000-000000000000}",
        )
        self.assertFalse(e.editable)

    def test_children_default_empty(self):
        e = MenuEntry(
            target=TargetContext.FILES, scope=Scope.USER,
            kind=EntryKind.COMMAND,
            key_path="x", name="n", display_name="d",
        )
        self.assertEqual(e.children, [])

    def test_to_dict_roundtrip_children(self):
        e = MenuEntry(
            target=TargetContext.FILES, scope=Scope.USER,
            kind=EntryKind.COMMAND,
            key_path="x", name="n", display_name="d",
            file_type_ext=".txt", command="c", icon="i",
            position="Bottom", extended=False, clsid=None,
            blocked=True,
        )
        d = e.to_dict()
        self.assertEqual(d["file_type_ext"], ".txt")
        self.assertEqual(d["command"], "c")
        self.assertEqual(d["icon"], "i")
        self.assertEqual(d["position"], "Bottom")
        self.assertFalse(d["extended"])
        self.assertTrue(d["blocked"])


class TestElevationCanEdit(unittest.TestCase):
    """elevation.can_edit/can_block 的判定逻辑（mock is_admin）。"""

    def _make(self, kind=EntryKind.COMMAND, scope=Scope.USER, clsid=None):
        return MenuEntry(
            target=TargetContext.FILES, scope=scope, kind=kind,
            key_path="x", name="n", display_name="d", clsid=clsid,
        )

    def test_can_edit_user_command_no_admin(self):
        e = self._make(kind=EntryKind.COMMAND, scope=Scope.USER)
        with mock.patch.object(elevation, "is_admin", return_value=False):
            self.assertTrue(elevation.can_edit(e))

    def test_can_edit_system_command_no_admin(self):
        e = self._make(kind=EntryKind.COMMAND, scope=Scope.SYSTEM)
        with mock.patch.object(elevation, "is_admin", return_value=False):
            # SYSTEM + 非管理员 -> 不可编辑
            self.assertFalse(elevation.can_edit(e))

    def test_can_edit_system_command_admin(self):
        e = self._make(kind=EntryKind.COMMAND, scope=Scope.SYSTEM)
        with mock.patch.object(elevation, "is_admin", return_value=True):
            self.assertTrue(elevation.can_edit(e))

    def test_can_edit_shellex_never(self):
        e = self._make(kind=EntryKind.SHELLEX, scope=Scope.USER,
                       clsid="{00000000-0000-0000-0000-000000000000}")
        with mock.patch.object(elevation, "is_admin", return_value=True):
            # SHELLEX 不论是否管理员都不可编辑
            self.assertFalse(elevation.can_edit(e))

    def test_can_block_user_shellex_no_admin(self):
        e = self._make(kind=EntryKind.SHELLEX, scope=Scope.USER,
                       clsid="{00000000-0000-0000-0000-000000000000}")
        with mock.patch.object(elevation, "is_admin", return_value=False):
            # USER scope 的 SHELLEX 可屏蔽（无需管理员）
            self.assertTrue(elevation.can_block(e))

    def test_can_block_system_shellex_no_admin(self):
        e = self._make(kind=EntryKind.SHELLEX, scope=Scope.SYSTEM,
                       clsid="{00000000-0000-0000-0000-000000000000}")
        with mock.patch.object(elevation, "is_admin", return_value=False):
            # SYSTEM scope 的 SHELLEX 需管理员才可屏蔽
            self.assertFalse(elevation.can_block(e))

    def test_can_block_system_shellex_admin(self):
        e = self._make(kind=EntryKind.SHELLEX, scope=Scope.SYSTEM,
                       clsid="{00000000-0000-0000-0000-000000000000}")
        with mock.patch.object(elevation, "is_admin", return_value=True):
            self.assertTrue(elevation.can_block(e))


if __name__ == "__main__":
    unittest.main()

