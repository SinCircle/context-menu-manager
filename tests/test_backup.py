"""backup.py 的测试：纯逻辑（路径、文件名、BackupInfo 解析）。

不真跑 reg import，不破坏系统。
"""
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from context_menu_manager import backup as b
from context_menu_manager.model import TargetContext
from context_menu_manager.registry import RegistryError


class TestBackupPaths(unittest.TestCase):
    def test_backup_dir_is_path(self):
        self.assertIsInstance(b.BACKUP_DIR, Path)

    def test_normalize_reg_path_hkcr(self):
        self.assertEqual(
            b._normalize_reg_path(r"HKCR\*\shell"),
            r"HKEY_CLASSES_ROOT\*\shell",
        )

    def test_normalize_reg_path_hkcu(self):
        self.assertEqual(
            b._normalize_reg_path(
                r"HKCU\Software\Classes\Directory\shell"),
            r"HKEY_CURRENT_USER\Software\Classes\Directory\shell",
        )

    def test_normalize_reg_path_hklm(self):
        self.assertEqual(
            b._normalize_reg_path(r"HKLM\Software\Classes\*\shell"),
            r"HKEY_LOCAL_MACHINE\Software\Classes\*\shell",
        )


class TestMatchTargetLabel(unittest.TestCase):
    def test_files_shell(self):
        self.assertEqual(
            b._match_target_label(r"*\shell\MyCmd"),
            TargetContext.FILES.label,
        )

    def test_files_shellex(self):
        self.assertEqual(
            b._match_target_label(r"*\shellex\ContextMenuHandlers\X"),
            TargetContext.FILES.label,
        )

    def test_directory(self):
        self.assertEqual(
            b._match_target_label(r"Directory\shell\cmd"),
            TargetContext.DIRECTORY.label,
        )

    def test_directory_background(self):
        # Background 必须优先于 Directory 匹配
        self.assertEqual(
            b._match_target_label(r"Directory\Background\shell\cmd"),
            TargetContext.DIRECTORY_BACKGROUND.label,
        )

    def test_drive(self):
        self.assertEqual(
            b._match_target_label(r"Drive\shell\cmd"),
            TargetContext.DRIVE.label,
        )

    def test_unknown(self):
        self.assertIsNone(b._match_target_label(r"txtfile\shell\open"))


class TestExtractTargets(unittest.TestCase):
    def _write_reg(self, content: str, tmpdir: Path) -> Path:
        f = tmpdir / "test.reg"
        f.write_text(content, encoding="utf-16")  # 带 BOM，模拟 reg.exe
        return f

    def test_extract_known_targets(self):
        content = (
            "Windows Registry Editor Version 5.00\r\n\r\n"
            r"[HKEY_CURRENT_USER\Software\Classes\*\shell\MyCmd]" "\r\n"
            r"[HKEY_CURRENT_USER\Software\Classes\Directory\shell\cmd]" "\r\n"
            r"[HKEY_CURRENT_USER\Software\Classes\Drive\shell\x]" "\r\n"
        )
        with tempfile.TemporaryDirectory() as td:
            f = self._write_reg(content, Path(td))
            targets = b._extract_targets_from_reg(f)
        self.assertIn(TargetContext.FILES.label, targets)
        self.assertIn(TargetContext.DIRECTORY.label, targets)
        self.assertIn(TargetContext.DRIVE.label, targets)

    def test_extract_empty_file(self):
        with tempfile.TemporaryDirectory() as td:
            f = self._write_reg(
                "Windows Registry Editor Version 5.00\r\n\r\n", Path(td))
            targets = b._extract_targets_from_reg(f)
        self.assertEqual(targets, [])

    def test_extract_dedup(self):
        content = (
            r"[HKEY_CURRENT_USER\Software\Classes\*\shell\A]" "\r\n"
            r"[HKEY_CURRENT_USER\Software\Classes\*\shell\B]" "\r\n"
        )
        with tempfile.TemporaryDirectory() as td:
            f = self._write_reg(content, Path(td))
            targets = b._extract_targets_from_reg(f)
        self.assertEqual(targets.count(TargetContext.FILES.label), 1)


class TestBackupInfo(unittest.TestCase):
    def test_dataclass_construction(self):
        info = b.BackupInfo(
            name="backup_20260101_120000",
            path=Path("/tmp/x.reg"),
            created_at="2026-01-01T12:00:00",
            targets=["文件（所有文件 *）"],
        )
        self.assertEqual(info.name, "backup_20260101_120000")
        self.assertEqual(info.targets, ["文件（所有文件 *）"])


class TestBackupAllFilename(unittest.TestCase):
    """验证 backup_all 生成带时间戳的文件名（空 targets 不调 reg.exe）。"""

    def setUp(self):
        self._created: list[Path] = []

    def tearDown(self):
        for p in self._created:
            try:
                p.unlink()
            except OSError:
                pass

    def test_empty_targets_creates_timestamped_file(self):
        p = b.backup_all([])
        self._created.append(p)
        self.assertTrue(p.exists())
        self.assertTrue(p.name.startswith("backup_"))
        self.assertTrue(p.suffix == ".reg")
        self.assertRegex(
            p.stem, r"^backup_\d{8}_\d{6}$",
            f"文件名 {p.stem} 不符合 backup_YYYYMMDD_HHMMSS 格式",
        )


class TestDeleteBackup(unittest.TestCase):
    def test_delete_nonexistent_raises(self):
        with self.assertRaises(RegistryError):
            b.delete_backup("__cmm_nonexistent_backup__")


if __name__ == "__main__":
    unittest.main()
