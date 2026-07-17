"""registry.py 的测试：在 HKCU 测试子键上做真实增删改查。

⚠️ 所有测试键以 __cmm_ut_ 为前缀，测完务必删除，绝不污染真实菜单。
使用 addCleanup 确保即使断言失败也清理。
HKLM/SYSTEM 路由与系统屏蔽的测试用 skipUnless(is_admin()) 守卫。
"""
import unittest
from unittest import mock

from context_menu_manager import elevation, registry as r
from context_menu_manager.model import (
    EntryKind, MenuEntry, Scope, TargetContext,
)

TARGET = TargetContext.DIRECTORY_BACKGROUND
SHELL_BASE = r"Directory\Background\shell"


def _key(name: str) -> str:
    return "HKCR\\" + SHELL_BASE + "\\" + name


def _make_entry(name="__cmm_ut_cmd__", **kw) -> MenuEntry:
    defaults = dict(
        target=TARGET, scope=Scope.USER, kind=EntryKind.COMMAND,
        key_path=_key(name), name=name, display_name="UT 命令",
        command='notepad.exe "%V"', icon="notepad.exe,0",
        position="Top", extended=True,
    )
    defaults.update(kw)
    return MenuEntry(**defaults)


class _RegistryTestBase(unittest.TestCase):
    """公共：注册清理函数，确保测试键被删除。"""

    def _reg_del(self, key_path: str):
        try:
            r.delete_entry(key_path)
        except Exception:
            pass

    def _create_and_register(self, entry: MenuEntry):
        r.create_entry(entry)
        self.addCleanup(self._reg_del, entry.key_path)
        return entry


class TestCommandCRUD(_RegistryTestBase):
    def test_create_get(self):
        e = _make_entry()
        self._create_and_register(e)
        got = r.get_entry(e.key_path)
        self.assertEqual(got.name, "__cmm_ut_cmd__")
        self.assertEqual(got.display_name, "UT 命令")
        self.assertEqual(got.command, 'notepad.exe "%V"')
        self.assertEqual(got.icon, "notepad.exe,0")
        self.assertEqual(got.position, "Top")
        self.assertTrue(got.extended)
        self.assertEqual(got.scope, Scope.USER)
        self.assertEqual(got.kind, EntryKind.COMMAND)

    def test_update(self):
        e = _make_entry()
        self._create_and_register(e)
        e2 = _make_entry(
            display_name="改名了", command="calc.exe",
            icon=None, position=None, extended=False,
        )
        r.update_entry(e2)
        got = r.get_entry(e.key_path)
        self.assertEqual(got.display_name, "改名了")
        self.assertEqual(got.command, "calc.exe")
        self.assertIsNone(got.icon)
        self.assertIsNone(got.position)
        self.assertFalse(got.extended)

    def test_delete(self):
        e = _make_entry("__cmm_ut_del__")
        r.create_entry(e)
        r.delete_entry(e.key_path)
        with self.assertRaises(r.KeyNotFoundError):
            r.get_entry(e.key_path)

    def test_delete_nonexistent_raises(self):
        with self.assertRaises(r.KeyNotFoundError):
            r.delete_entry(_key("__cmm_ut_noexist__"))

    def test_get_nonexistent_raises(self):
        with self.assertRaises(r.KeyNotFoundError):
            r.get_entry(_key("__cmm_ut_noexist__"))


class TestCascadeCRUD(_RegistryTestBase):
    def test_cascade_create_get(self):
        child = MenuEntry(
            target=TARGET, scope=Scope.USER, kind=EntryKind.COMMAND,
            key_path=_key("__cmm_ut_cas__") + r"\shell\子项",
            name="子项", display_name="子命令",
            command='cmd.exe "%V"',
        )
        parent = MenuEntry(
            target=TARGET, scope=Scope.USER, kind=EntryKind.CASCADE,
            key_path=_key("__cmm_ut_cas__"), name="__cmm_ut_cas__",
            display_name="级联测试", icon="a.exe,0",
            children=[child],
        )
        self._create_and_register(parent)

        got = r.get_entry(parent.key_path)
        self.assertEqual(got.kind, EntryKind.CASCADE)
        self.assertEqual(got.display_name, "级联测试")
        self.assertEqual(len(got.children), 1)
        kid = got.children[0]
        self.assertEqual(kid.name, "子项")
        self.assertEqual(kid.display_name, "子命令")
        self.assertEqual(kid.command, 'cmd.exe "%V"')
        self.assertEqual(kid.kind, EntryKind.COMMAND)

    def test_cascade_in_list_entries(self):
        child = MenuEntry(
            target=TARGET, scope=Scope.USER, kind=EntryKind.COMMAND,
            key_path=_key("__cmm_ut_cas2__") + r"\shell\c1",
            name="c1", display_name="C1", command="x.exe",
        )
        parent = MenuEntry(
            target=TARGET, scope=Scope.USER, kind=EntryKind.CASCADE,
            key_path=_key("__cmm_ut_cas2__"), name="__cmm_ut_cas2__",
            display_name="级联2", children=[child],
        )
        self._create_and_register(parent)
        listed = r.list_entries(TARGET)
        names = [x.name for x in listed]
        self.assertIn("__cmm_ut_cas2__", names)


class TestResolveScope(_RegistryTestBase):
    def test_user_after_create(self):
        e = _make_entry("__cmm_ut_scope__")
        self._create_and_register(e)
        self.assertEqual(r.resolve_scope(e.key_path), Scope.USER)

    def test_system_after_delete(self):
        e = _make_entry("__cmm_ut_scope2__")
        r.create_entry(e)
        r.delete_entry(e.key_path)
        # 删除后 HKCU 无此键 -> SYSTEM
        self.assertEqual(r.resolve_scope(e.key_path), Scope.SYSTEM)

    def test_hkcu_path_form(self):
        # HKCU 形式的 key_path 也能正确判定
        e = _make_entry("__cmm_ut_scope3__")
        self._create_and_register(e)
        cu_path = (r"HKCU\Software\Classes\\" + SHELL_BASE
                   + r"\__cmm_ut_scope3__")
        self.assertEqual(r.resolve_scope(cu_path), Scope.USER)


class TestShellexReadOnly(_RegistryTestBase):
    def test_create_shellex_raises(self):
        e = MenuEntry(
            target=TARGET, scope=Scope.USER, kind=EntryKind.SHELLEX,
            key_path=_key("__cmm_ut_shx__"), name="__cmm_ut_shx__",
            display_name="X", clsid="{00000000-0000-0000-0000-000000000000}",
        )
        with self.assertRaises(r.RegistryError):
            r.create_entry(e)

    def test_update_shellex_raises(self):
        e = MenuEntry(
            target=TARGET, scope=Scope.USER, kind=EntryKind.SHELLEX,
            key_path=_key("__cmm_ut_shx2__"), name="__cmm_ut_shx2__",
            display_name="X", clsid="{00000000-0000-0000-0000-000000000000}",
        )
        with self.assertRaises(r.RegistryError):
            r.update_entry(e)


class TestEnumAndFileTypes(unittest.TestCase):
    def test_enum_targets_no_filetype(self):
        targets = r.enum_targets()
        self.assertIn(TargetContext.FILES, targets)
        self.assertIn(TargetContext.DIRECTORY, targets)
        self.assertIn(TargetContext.DIRECTORY_BACKGROUND, targets)
        self.assertIn(TargetContext.DRIVE, targets)
        self.assertIn(TargetContext.ALLFILESYSTEMOBJECTS, targets)
        self.assertIn(TargetContext.NEW, targets)
        self.assertIn(TargetContext.SENDTO, targets)
        self.assertIn(TargetContext.OPENWITH, targets)
        self.assertIn(TargetContext.WINX, targets)
        self.assertNotIn(TargetContext.FILETYPE, targets)

    def test_list_file_types(self):
        fts = r.list_file_types()
        self.assertIsInstance(fts, list)
        self.assertGreater(len(fts), 0)
        for ext in fts:
            self.assertTrue(ext.startswith("."))
        # 应已排序
        self.assertEqual(fts, sorted(fts))


class TestListEntries(_RegistryTestBase):
    def test_list_returns_list(self):
        for tgt in r.enum_targets():
            entries = r.list_entries(tgt)
            self.assertIsInstance(entries, list)
            for e in entries:
                self.assertIsInstance(e, MenuEntry)

    def test_bad_key_skipping(self):
        """单键出错应跳过，不整体崩溃，其它键仍返回。"""
        e1 = _make_entry("__cmm_ut_bad1__")
        e2 = _make_entry("__cmm_ut_bad2__")
        self._create_and_register(e1)
        self._create_and_register(e2)

        original = r._read_static_entry

        def side_effect(target, ext, base, name):
            if name == "__cmm_ut_bad1__":
                raise RuntimeError("simulated bad key")
            return original(target, ext, base, name)

        with mock.patch.object(r, "_read_static_entry", side_effect=side_effect):
            listed = r.list_entries(TARGET)
        names = [x.name for x in listed]
        self.assertIn("__cmm_ut_bad2__", names)
        self.assertNotIn("__cmm_ut_bad1__", names)


class TestFileTypeTarget(unittest.TestCase):
    def test_filetype_requires_ext(self):
        with self.assertRaises(ValueError):
            r.list_entries(TargetContext.FILETYPE, None)


# ── 新场景读取冒烟测试 ──────────────────────────────────────────
class TestNewScenarios(unittest.TestCase):
    """NEW/SENDTO/OPENWITH/WINX 读取冒烟测试：不崩即可。"""

    def test_new_returns_list(self):
        entries = r.list_entries(TargetContext.NEW)
        self.assertIsInstance(entries, list)
        for e in entries:
            self.assertEqual(e.target, TargetContext.NEW)
            self.assertIsInstance(e.display_name, str)

    def test_sendto_returns_list(self):
        entries = r.list_entries(TargetContext.SENDTO)
        self.assertIsInstance(entries, list)
        for e in entries:
            self.assertEqual(e.target, TargetContext.SENDTO)
            self.assertEqual(e.scope, Scope.USER)
            # SENDTO 的 key_path 是文件路径
            self.assertTrue(e.command)

    def test_openwith_returns_list(self):
        entries = r.list_entries(TargetContext.OPENWITH)
        self.assertIsInstance(entries, list)
        for e in entries:
            self.assertEqual(e.target, TargetContext.OPENWITH)

    def test_winx_returns_list(self):
        entries = r.list_entries(TargetContext.WINX)
        self.assertIsInstance(entries, list)
        for e in entries:
            self.assertEqual(e.target, TargetContext.WINX)
            self.assertEqual(e.scope, Scope.SYSTEM)

    def test_winx_typically_has_entries(self):
        r"""CommandStore\shell 在正常 Windows 上应有大量条目。"""
        entries = r.list_entries(TargetContext.WINX)
        self.assertGreater(len(entries), 0,
                           "CommandStore\\shell 应有命令项")


# ── block/unblock 测试（HKCU 真实操作）─────────────────────────
class TestBlockUnblockCommand(_RegistryTestBase):
    """COMMAND/CASCADE 的 block/unblock：在 HKCU 测试子键上真实操作。"""

    def test_block_sets_legacy_disable(self):
        e = _make_entry("__cmm_ut_blk__")
        self._create_and_register(e)
        r.block_entry(e)
        self.addCleanup(r.unblock_entry, e)
        got = r.get_entry(e.key_path)
        self.assertTrue(got.blocked, "block_entry 后 blocked 应为 True")

    def test_unblock_removes_legacy_disable(self):
        e = _make_entry("__cmm_ut_ublk__")
        self._create_and_register(e)
        r.block_entry(e)
        r.unblock_entry(e)
        got = r.get_entry(e.key_path)
        self.assertFalse(got.blocked, "unblock_entry 后 blocked 应为 False")

    def test_block_unblock_idempotent(self):
        e = _make_entry("__cmm_ut_blk2__")
        self._create_and_register(e)
        # 重复 unblock 不应抛异常
        r.unblock_entry(e)
        r.unblock_entry(e)
        got = r.get_entry(e.key_path)
        self.assertFalse(got.blocked)


class TestBlockUnblockShellex(unittest.TestCase):
    r"""SHELLEX 的 block/unblock：写/删 Shell Extensions\Blocked 键。

    使用 USER scope + 一个虚构 CLSID（测试用），操作 HKCU 的 Blocked 键。
    HKLM 的 Blocked 键在非管理员下静默跳过（USER scope 容忍）。
    """

    TEST_CLSID = "{12345678-1234-1234-1234-123456789abc}"

    def setUp(self):
        # 确保测试 CLSID 不在 Blocked 键中
        self._ensure_unblocked()

    def tearDown(self):
        self._ensure_unblocked()

    def _ensure_unblocked(self):
        from context_menu_manager.registry import _blocked_key_paths
        import winreg
        for root, path in _blocked_key_paths():
            k = r._open_key(root, path, r.KEY_WRITE_64)
            if k is None:
                continue
            try:
                r._delete_value_safe(k, self.TEST_CLSID)
            finally:
                winreg.CloseKey(k)

    def _make_shellex(self, scope=Scope.USER):
        return MenuEntry(
            target=TargetContext.FILES, scope=scope, kind=EntryKind.SHELLEX,
            key_path=r"HKCR\*\shellex\ContextMenuHandlers\__cmm_ut_shx_blk__",
            name="__cmm_ut_shx_blk__", display_name="UT Shellex",
            clsid=self.TEST_CLSID,
        )

    def test_block_shellex_writes_blocked_key(self):
        e = self._make_shellex(scope=Scope.USER)
        r.block_entry(e)
        # USER scope：HKCU Blocked 必有该 CLSID
        self.assertTrue(r._is_clsid_blocked(self.TEST_CLSID))
        # _read_shellex_entry 检测 blocked=True
        # (用一个真实存在的 shellex 项不便构造，直接验证 _is_clsid_blocked)

    def test_unblock_shellex_removes_from_blocked_key(self):
        e = self._make_shellex(scope=Scope.USER)
        r.block_entry(e)
        self.assertTrue(r._is_clsid_blocked(self.TEST_CLSID))
        r.unblock_entry(e)
        self.assertFalse(r._is_clsid_blocked(self.TEST_CLSID))

    def test_block_shellex_without_clsid_raises(self):
        e = MenuEntry(
            target=TargetContext.FILES, scope=Scope.USER,
            kind=EntryKind.SHELLEX,
            key_path="x", name="n", display_name="n", clsid=None,
        )
        with self.assertRaises(r.RegistryError):
            r.block_entry(e)


# ── SYSTEM 路由测试（需管理员，否则跳过）────────────────────────
@unittest.skipUnless(elevation.is_admin(), "需要管理员权限")
class TestSystemRouting(unittest.TestCase):
    """HKLM/SYSTEM 路由测试：仅在管理员下运行。"""

    def test_create_system_requires_admin_guarded(self):
        # 此类仅在 admin 下运行，故 create SYSTEM 应成功
        e = MenuEntry(
            target=TARGET, scope=Scope.SYSTEM, kind=EntryKind.COMMAND,
            key_path=_key("__cmm_ut_sys__"), name="__cmm_ut_sys__",
            display_name="UT SYS", command="notepad.exe %V",
        )
        try:
            r.create_entry(e)
            # 应写入 HKLM
            import winreg
            k = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Classes\\" + SHELL_BASE + r"\__cmm_ut_sys__",
                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            )
            winreg.CloseKey(k)
        finally:
            try:
                r.delete_entry(e.key_path)
            except Exception:
                pass


class TestSystemRoutingPermission(unittest.TestCase):
    """非管理员下 SYSTEM 路由应抛 PermissionDeniedError。"""

    def test_create_system_without_admin_raises(self):
        if elevation.is_admin():
            self.skipTest("当前已是管理员，跳过非管理员场景")
        e = MenuEntry(
            target=TARGET, scope=Scope.SYSTEM, kind=EntryKind.COMMAND,
            key_path=_key("__cmm_ut_sysperm__"), name="__cmm_ut_sysperm__",
            display_name="UT SYS", command="notepad.exe %V",
        )
        with self.assertRaises(r.PermissionDeniedError):
            r.create_entry(e)

    def test_update_system_without_admin_raises(self):
        if elevation.is_admin():
            self.skipTest("当前已是管理员，跳过非管理员场景")
        e = MenuEntry(
            target=TARGET, scope=Scope.SYSTEM, kind=EntryKind.COMMAND,
            key_path=_key("__cmm_ut_sysperm2__"), name="__cmm_ut_sysperm2__",
            display_name="UT SYS", command="notepad.exe %V",
        )
        with self.assertRaises(r.PermissionDeniedError):
            r.update_entry(e)

    def test_block_system_shellex_without_admin_raises(self):
        if elevation.is_admin():
            self.skipTest("当前已是管理员，跳过非管理员场景")
        e = MenuEntry(
            target=TargetContext.FILES, scope=Scope.SYSTEM,
            kind=EntryKind.SHELLEX,
            key_path="x", name="n", display_name="n",
            clsid="{00000000-0000-0000-0000-000000000000}",
        )
        with self.assertRaises(r.PermissionDeniedError):
            r.block_entry(e)


if __name__ == "__main__":
    unittest.main()

