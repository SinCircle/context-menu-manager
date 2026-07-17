"""command_info.py 的测试：KNOWN_APPS 命中、动作推断、description 生成、
rundll32/cmd 前缀、None 情况。"""
import unittest

from context_menu_manager import command_info as ci


class TestKnownApps(unittest.TestCase):
    def test_code_exe(self):
        self.assertEqual(ci.KNOWN_APPS["code.exe"], "VSCode")
        self.assertEqual(ci.KNOWN_APPS["code"], "VSCode")

    def test_git_bash(self):
        self.assertEqual(ci.KNOWN_APPS["git-bash.exe"], "Git Bash")
        self.assertEqual(ci.KNOWN_APPS["bash.exe"], "Git Bash")

    def test_7z(self):
        self.assertEqual(ci.KNOWN_APPS["7z.exe"], "7-Zip")
        self.assertEqual(ci.KNOWN_APPS["7zfm.exe"], "7-Zip")

    def test_powershell(self):
        self.assertEqual(ci.KNOWN_APPS["powershell.exe"], "PowerShell")
        self.assertEqual(ci.KNOWN_APPS["pwsh.exe"], "PowerShell")

    def test_chinese_apps(self):
        self.assertEqual(ci.KNOWN_APPS["weixin.exe"], "微信")
        self.assertEqual(ci.KNOWN_APPS["qq.exe"], "QQ")

    def test_required_coverage(self):
        """任务要求覆盖的最低集合。"""
        required = {
            "code.exe": "VSCode", "vscodium.exe": "VSCodium",
            "git.exe": "Git", "git-bash.exe": "Git Bash",
            "bash.exe": "Git Bash", "7z.exe": "7-Zip", "7zfm.exe": "7-Zip",
            "powershell.exe": "PowerShell", "pwsh.exe": "PowerShell",
            "wt.exe": "Windows Terminal", "cmd.exe": "命令提示符",
            "notepad.exe": "记事本", "explorer.exe": "资源管理器",
            "regedit.exe": "注册表编辑器", "python.exe": "Python",
            "node.exe": "Node.js", "nvim.exe": "Vim", "vim.exe": "Vim",
            "sublime_text.exe": "Sublime Text", "idea64.exe": "IntelliJ IDEA",
            "typora.exe": "Typora", "hbuilderx.exe": "HBuilderX",
            "weixin.exe": "微信", "qq.exe": "QQ",
        }
        for k, v in required.items():
            self.assertEqual(ci.KNOWN_APPS.get(k), v,
                             f"缺少已知应用: {k}")


class TestParseExe(unittest.TestCase):
    def test_quoted_path(self):
        info = ci.parse_command(r'"C:\VSCode\Code.exe" "%V"')
        self.assertIsNotNone(info)
        self.assertEqual(info.exe_name, "code.exe")
        self.assertEqual(info.app_name, "VSCode")

    def test_env_expansion(self):
        info = ci.parse_command(r"%SystemRoot%\System32\notepad.exe %1")
        self.assertIsNotNone(info)
        self.assertEqual(info.exe_name, "notepad.exe")
        self.assertEqual(info.app_name, "记事本")
        # 路径已展开
        self.assertIn("System32", info.exe_path or "")
        self.assertNotIn("%SystemRoot%", info.exe_path or "")

    def test_bare_exe(self):
        info = ci.parse_command("notepad.exe %1")
        self.assertEqual(info.exe_name, "notepad.exe")
        self.assertEqual(info.app_name, "记事本")

    def test_rundll32_prefix(self):
        info = ci.parse_command(
            r"rundll32 %SystemRoot%\System32\shwebsvc.dll,AddNetPlaceRunDll")
        self.assertIsNotNone(info)
        # rundll32 应提取实际目标 dll
        self.assertEqual(info.exe_name, "shwebsvc.dll")
        self.assertIn("shwebsvc.dll", info.exe_path or "")

    def test_cmd_c_prefix(self):
        info = ci.parse_command(r'cmd /c "C:\Tools\app.exe" arg1')
        self.assertIsNotNone(info)
        # cmd /c 跳过前缀，取实际目标
        self.assertEqual(info.exe_name, "app.exe")

    def test_powershell_c_prefix(self):
        info = ci.parse_command(r'powershell -c "Get-Process"')
        self.assertIsNotNone(info)
        # powershell -c 跳过前缀；后续参数被当作命令
        # 具体提取哪个不强制，但不应是 powershell 本身
        self.assertNotEqual(info.exe_name, "powershell.exe")

    def test_empty_and_none(self):
        self.assertIsNone(ci.parse_command(None))
        self.assertIsNone(ci.parse_command(""))
        self.assertIsNone(ci.parse_command("   "))


class TestActionInference(unittest.TestCase):
    def test_compress_action(self):
        info = ci.parse_command("7z a archive.zip file.txt")
        self.assertEqual(info.action, "压缩")

    def test_compress_keyword_zip(self):
        info = ci.parse_command("zip archive.zip file")
        self.assertEqual(info.action, "压缩")

    def test_extract_action(self):
        info = ci.parse_command("unzip archive.zip")
        self.assertEqual(info.action, "解压")

    def test_extract_chinese(self):
        info = ci.parse_command("tool 解压 file.zip")
        self.assertEqual(info.action, "解压")

    def test_upload_action(self):
        info = ci.parse_command("tool upload file")
        self.assertEqual(info.action, "上传")

    def test_upload_chinese(self):
        info = ci.parse_command("tool 上传 file")
        self.assertEqual(info.action, "上传")

    def test_download_action(self):
        info = ci.parse_command("tool download url")
        self.assertEqual(info.action, "下载")

    def test_edit_action(self):
        info = ci.parse_command("tool edit file")
        self.assertEqual(info.action, "编辑")

    def test_print_action(self):
        info = ci.parse_command("tool print file")
        self.assertEqual(info.action, "打印")

    def test_copy_action(self):
        info = ci.parse_command("tool copy file")
        self.assertEqual(info.action, "复制")

    def test_delete_action(self):
        info = ci.parse_command("tool delete file")
        self.assertEqual(info.action, "删除")

    def test_delete_remove(self):
        info = ci.parse_command("tool remove file")
        self.assertEqual(info.action, "删除")

    def test_run_action(self):
        info = ci.parse_command("tool run script")
        self.assertEqual(info.action, "运行")

    def test_default_open(self):
        info = ci.parse_command("notepad.exe %1")
        self.assertEqual(info.action, "打开")

    def test_word_boundary_no_false_positive(self):
        """pushd 不应命中 push（push 已移除）；archive.zip 的 zip 应命中（. 是边界）。"""
        info = ci.parse_command(r'cmd /c pushd "%V"')
        self.assertNotEqual(info.action, "上传")
        # zip 在 "archive.zip" 中应命中（. 为单词边界）
        info2 = ci.parse_command("7z a archive.zip f")
        self.assertEqual(info2.action, "压缩")


class TestDescription(unittest.TestCase):
    def test_description_with_app_open(self):
        info = ci.parse_command(r'"C:\VSCode\Code.exe" "%V"')
        self.assertEqual(info.description, "用 VSCode 打开")

    def test_description_with_app_other_action(self):
        info = ci.parse_command("7z a archive.zip f")
        self.assertEqual(info.description, "用 7-Zip 压缩")

    def test_description_no_app_open(self):
        info = ci.parse_command("someunknowntool.exe %1")
        # 无 app + 动作打开 -> "执行：{exe_name}"
        self.assertEqual(info.description, "执行：someunknowntool.exe")

    def test_description_no_app_other_action(self):
        info = ci.parse_command("unknowntool upload f")
        # 无 app + 动作上传 -> "上传：{exe_name}"
        self.assertEqual(info.description, "上传：unknowntool")


if __name__ == "__main__":
    unittest.main()
