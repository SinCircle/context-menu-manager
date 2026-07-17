"""placeholders.py 的测试：PLACEHOLDERS、describe、validate_command。"""
import unittest

from context_menu_manager import placeholders as ph


class TestPlaceholders(unittest.TestCase):
    def test_placeholders_contains_expected_keys(self):
        self.assertEqual(ph.PLACEHOLDERS["%1"], "文件路径")
        self.assertEqual(ph.PLACEHOLDERS["%V"], "文件/文件夹路径")
        self.assertEqual(ph.PLACEHOLDERS["%w"], "工作目录")
        self.assertEqual(ph.PLACEHOLDERS["%L"], "长路径名")
        self.assertEqual(len(ph.PLACEHOLDERS), 4)

    def test_describe_returns_list_of_tuples(self):
        desc = ph.describe()
        self.assertIsInstance(desc, list)
        for item in desc:
            self.assertIsInstance(item, tuple)
            self.assertEqual(len(item), 2)
        keys = [k for k, _ in desc]
        self.assertEqual(set(keys), set(ph.PLACEHOLDERS.keys()))

    def test_validate_empty_command(self):
        self.assertEqual(ph.validate_command(""), ["命令不能为空"])
        self.assertEqual(ph.validate_command("   "), ["命令不能为空"])

    def test_validate_good_command(self):
        # 含占位符、引号配对 -> 空表
        self.assertEqual(ph.validate_command('notepad.exe "%V"'), [])
        self.assertEqual(ph.validate_command("cmd.exe /k %1"), [])

    def test_validate_no_placeholder(self):
        warnings = ph.validate_command("notepad.exe")
        self.assertEqual(len(warnings), 1)
        self.assertIn("占位符", warnings[0])

    def test_validate_unbalanced_quotes(self):
        warnings = ph.validate_command('notepad.exe "%V')
        self.assertTrue(any("引号" in w for w in warnings))

    def test_validate_multiple_issues(self):
        # 无占位符且引号不配对 -> 两条警告
        warnings = ph.validate_command('notepad.exe "')
        self.assertEqual(len(warnings), 2)


if __name__ == "__main__":
    unittest.main()
