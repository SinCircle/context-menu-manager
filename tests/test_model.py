"""model.py 的测试：to_dict 序列化、editable 属性、children 默认值。"""
import unittest

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
        self.assertTrue(e.editable)

    def test_not_editable_system(self):
        e = MenuEntry(
            target=TargetContext.FILES, scope=Scope.SYSTEM,
            kind=EntryKind.COMMAND,
            key_path="x", name="n", display_name="d",
        )
        self.assertFalse(e.editable)

    def test_not_editable_shellex(self):
        e = MenuEntry(
            target=TargetContext.FILES, scope=Scope.USER,
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


if __name__ == "__main__":
    unittest.main()
