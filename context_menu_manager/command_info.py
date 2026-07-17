"""命令行解析与描述。

从命令行提取可执行路径（处理引号、环境变量展开、rundll32/cmd 前缀），
推断所属应用（KNOWN_APPS 表）与动作动词，生成"用 VSCode 打开"式描述。
"""
from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass


@dataclass
class CommandInfo:
    exe_path: str | None        # 提取的可执行文件路径
    exe_name: str | None        # 小写文件名，如 "code.exe"
    app_name: str | None        # 推断应用名，如 "VSCode"
    action: str                 # 动作，如 "打开" / "压缩" / "上传"
    description: str            # 人类可读描述，如 "用 VSCode 打开"


# 已知应用表：exe 文件名(小写) -> 应用中文名
# 同时收录带 .exe 与裸名两种形式（命令行中两种都常见）
KNOWN_APPS: dict[str, str] = {
    "code.exe": "VSCode",
    "code.cmd": "VSCode",
    "code": "VSCode",
    "vscodium.exe": "VSCodium",
    "vscodium.cmd": "VSCodium",
    "codium.exe": "VSCodium",
    "vscodium": "VSCodium",
    "git.exe": "Git",
    "git": "Git",
    "git-bash.exe": "Git Bash",
    "git-bash": "Git Bash",
    "bash.exe": "Git Bash",
    "bash": "Git Bash",
    "sh.exe": "Git Bash",
    "sh": "Git Bash",
    "wsl.exe": "WSL",
    "wsl": "WSL",
    "7z.exe": "7-Zip",
    "7z": "7-Zip",
    "7zfm.exe": "7-Zip",
    "7zg.exe": "7-Zip",
    "powershell.exe": "PowerShell",
    "powershell": "PowerShell",
    "pwsh.exe": "PowerShell",
    "pwsh": "PowerShell",
    "wt.exe": "Windows Terminal",
    "wt": "Windows Terminal",
    "cmd.exe": "命令提示符",
    "cmd": "命令提示符",
    "notepad.exe": "记事本",
    "notepad": "记事本",
    "notepad++.exe": "Notepad++",
    "explorer.exe": "资源管理器",
    "explorer": "资源管理器",
    "regedit.exe": "注册表编辑器",
    "regedit": "注册表编辑器",
    "reg.exe": "注册表",
    "reg": "注册表",
    "python.exe": "Python",
    "python": "Python",
    "pythonw.exe": "Python",
    "python3.exe": "Python",
    "py.exe": "Python",
    "py": "Python",
    "node.exe": "Node.js",
    "node": "Node.js",
    "npm.exe": "Node.js",
    "npm": "Node.js",
    "nvim.exe": "Vim",
    "vim.exe": "Vim",
    "vim": "Vim",
    "gvim.exe": "Vim",
    "sublime_text.exe": "Sublime Text",
    "subl.exe": "Sublime Text",
    "idea64.exe": "IntelliJ IDEA",
    "idea.exe": "IntelliJ IDEA",
    "pycharm64.exe": "PyCharm",
    "webstorm64.exe": "WebStorm",
    "clion64.exe": "CLion",
    "goland64.exe": "GoLand",
    "rider64.exe": "Rider",
    "rustrover64.exe": "RustRover",
    "typora.exe": "Typora",
    "hbuilderx.exe": "HBuilderX",
    "weixin.exe": "微信",
    "wechat.exe": "微信",
    "qq.exe": "QQ",
    "qqprotect.exe": "QQ",
    "dingtalk.exe": "钉钉",
    "dingtalklauncher.exe": "钉钉",
    "feishu.exe": "飞书",
    "lark.exe": "飞书",
    "excel.exe": "Excel",
    "winword.exe": "Word",
    "powerpnt.exe": "PowerPoint",
    "outlook.exe": "Outlook",
    "acrobat.exe": "Adobe Acrobat",
    "acrord32.exe": "Adobe Reader",
    "sumatrapdf.exe": "SumatraPDF",
    "foxitreader.exe": "Foxit Reader",
    "potplayer.exe": "PotPlayer",
    "potplayermini64.exe": "PotPlayer",
    "vlc.exe": "VLC",
    "mpc-hc.exe": "MPC-HC",
    "mpc-hc64.exe": "MPC-HC",
    "spotify.exe": "Spotify",
    "devenv.exe": "Visual Studio",
    "msedge.exe": "Microsoft Edge",
    "chrome.exe": "Google Chrome",
    "firefox.exe": "Mozilla Firefox",
    "brave.exe": "Brave",
    "opera.exe": "Opera",
    "iexplore.exe": "Internet Explorer",
    "calc.exe": "计算器",
    "mspaint.exe": "画图",
    "snippingtool.exe": "截图工具",
    "snipaste.exe": "Snipaste",
    "everything.exe": "Everything",
    "listary.exe": "Listary",
    "wox.exe": "Wox",
    "autohotkey.exe": "AutoHotkey",
    "autohotkey64.exe": "AutoHotkey",
    "filezilla.exe": "FileZilla",
    "winrar.exe": "WinRAR",
    "rar.exe": "WinRAR",
    "unrar.exe": "WinRAR",
    "zip.exe": "Zip",
    "unzip.exe": "Zip",
    "tar.exe": "Tar",
    "robocopy.exe": "Robocopy",
    "xcopy.exe": "Xcopy",
    "taskkill.exe": "Taskkill",
    "schtasks.exe": "计划任务",
    "msiexec.exe": "Windows Installer",
    "rundll32.exe": "Rundll32",
    "control.exe": "控制面板",
    "mmc.exe": "管理控制台",
    "services.msc": "服务",
    "compmgmtlauncher.exe": "计算机管理",
}


# 动作关键词（按优先级排序）：扫描命令与参数中的关键词推断动作
# (关键词列表, 动作名) -- 前面的优先级高。
# 注意：解压必须排在压缩之前，否则 "unzip archive.zip" 会被 "zip" 命中为压缩。
# 英文关键词用单词边界匹配（避免 "pushd" 命中 "push" 之类误判）；
# 中文关键词用子串匹配。
_ACTION_RULES: list[tuple[tuple[str, ...], str]] = [
    (("extract", "unzip", "unrar", "decompress", "解压"), "解压"),
    (("compress", "zip", "7z", "rar", "archive", "压缩"), "压缩"),
    (("upload", "上传"), "上传"),
    (("download", "下载"), "下载"),
    (("edit", "modify", "编辑"), "编辑"),
    (("print", "打印"), "打印"),
    (("copy", "clipboard", "复制"), "复制"),
    (("delete", "remove", "uninstall", "删除"), "删除"),
    (("run", "execute", "launch", "start", "执行", "运行"), "运行"),
    (("open", "view", "preview", "read", "打开"), "打开"),
]

# 编译英文关键词的正则（单词边界）。中文用直接子串。
_WORD_RE_CACHE: dict[str, "re.Pattern[str]"] = {}


def _word_re(kw: str) -> "re.Pattern[str]":
    r = _WORD_RE_CACHE.get(kw)
    if r is None:
        r = re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
        _WORD_RE_CACHE[kw] = r
    return r


def _keyword_matches(kw: str, haystack: str) -> bool:
    """英文关键词用单词边界；非 ASCII（中文等）用子串。"""
    if kw.isascii():
        return _word_re(kw).search(haystack) is not None
    return kw in haystack


# 前缀处理规则：当命令以这些前缀开头时，跳过前缀，提取实际目标
# (前缀名小写, 处理方式) -- 处理方式：
#   "skip"  -- 跳过前缀，从后续参数中找第一个非选项参数作为目标
#   "rundll32" -- rundll32 <dll>,<entry> 形式，取 dll 作为目标
_CMD_PREFIXES: dict[str, str] = {
    "rundll32.exe": "rundll32",
    "rundll32": "rundll32",
    "cmd.exe": "skip",
    "cmd": "skip",
    "command.com": "skip",
    "powershell.exe": "skip",
    "powershell": "skip",
    "pwsh.exe": "skip",
    "pwsh": "skip",
    "start": "skip",
}


def _expand_env(s: str) -> str:
    """展开环境变量（%SystemRoot% 等）。"""
    try:
        return os.path.expandvars(s)
    except Exception:
        return s


def _split_args(command: str) -> list[str]:
    """用 shlex 安全切分命令行；失败时退化为空格切分。"""
    try:
        # posix=True 下 shlex 对 Windows 路径反斜杠处理不佳，用 posix=False
        return shlex.split(command, posix=False)
    except ValueError:
        # 引号不匹配等
        return command.split()


def _strip_quotes(token: str) -> str:
    """去掉包裹引号。"""
    t = token.strip()
    if len(t) >= 2 and t[0] in ('"', "'") and t[-1] == t[0]:
        return t[1:-1]
    return t


def _exe_from_path_token(token: str) -> str | None:
    """从路径 token 提取 exe 文件名（小写）。"""
    t = _strip_quotes(token)
    if not t:
        return None
    # 去掉可能的逗号索引（如 "notepad.exe,0"）
    t = t.split(",")[0]
    # 去掉参数（如 "rundll32 printui.dll,PrintUIEntry /il" 中的 /il）
    base = os.path.basename(t)
    # 处理无扩展但有路径的情况
    if not base:
        return None
    return base.lower()


def _extract_exe(command: str) -> tuple[str | None, str | None]:
    """从命令行提取 (exe_path, exe_name)。

    处理 rundll32/cmd /c 等前缀：取实际目标 dll/exe。
    """
    if not command or not command.strip():
        return None, None
    cmd = command.strip()
    # 先展开环境变量
    cmd = _expand_env(cmd)
    args = _split_args(cmd)
    if not args:
        return None, None
    first = _strip_quotes(args[0])
    first_lower = first.lower()
    basename = os.path.basename(first_lower)

    # 检查是否是已知前缀
    if basename in _CMD_PREFIXES:
        mode = _CMD_PREFIXES[basename]
        if mode == "rundll32":
            # rundll32 <dll>,<entry> <args> -- 第二个参数是 <dll>,<entry>
            for tok in args[1:]:
                t = _strip_quotes(tok)
                if not t or t.startswith("/"):
                    continue
                # 形如 "printui.dll,PrintUIEntry" 或
                # "%SystemRoot%\System32\shwebsvc.dll,AddNetPlaceRunDll"
                dll_part = t.split(",")[0]
                if not dll_part:
                    continue
                dll_part = _expand_env(dll_part)
                exe_name = os.path.basename(dll_part).lower()
                if exe_name:
                    return dll_part, exe_name
            return None, None
        # mode == "skip"：cmd /c <realcmd> / powershell -c <realcmd>
        # 找第一个非选项参数作为目标
        for tok in args[1:]:
            t = _strip_quotes(tok)
            if not t or t.startswith("/"):
                continue
            # cmd 的 /c 后跟命令，可能是 "exe args..." 或 "exe" args...
            # 递归提取
            sub = " ".join(args[args.index(tok):])
            return _extract_exe(sub)
        return None, None

    # 普通命令：第一个 token 是 exe
    exe_path = first
    exe_name = os.path.basename(first_lower)
    # 去掉逗号索引
    exe_name = exe_name.split(",")[0]
    if not exe_name:
        return None, None
    return exe_path, exe_name


def _infer_action(command: str, exe_name: str | None) -> str:
    """从命令文本与 exe 名扫描动作关键词。"""
    haystack = (command or "").lower()
    if exe_name:
        haystack = haystack + " " + exe_name.lower()
    for keywords, action in _ACTION_RULES:
        for kw in keywords:
            if _keyword_matches(kw, haystack):
                return action
    return "打开"


def _build_description(app_name: str | None, action: str,
                       exe_name: str | None) -> str:
    """生成人类可读描述。"""
    if app_name:
        if action == "打开":
            return f"用 {app_name} 打开"
        return f"用 {app_name} {action}"
    # 无 app
    if action == "打开" and exe_name:
        return f"执行：{exe_name}"
    if exe_name:
        return f"{action}：{exe_name}"
    return action


def parse_command(command: str | None) -> CommandInfo | None:
    """解析命令行，返回描述信息。无法解析返回 None。

    处理：
    - 引号包裹的路径。
    - ``%SystemRoot%`` / ``%ProgramFiles%`` 等环境变量展开。
    - ``rundll32`` / ``cmd /c`` / ``powershell -c`` 前缀时取实际目标。
    - KNOWN_APPS 命中 -> app_name；动作关键词扫描 -> action。
    """
    if not command or not command.strip():
        return None
    try:
        exe_path, exe_name = _extract_exe(command)
    except Exception:
        return None
    if not exe_name:
        return None
    app_name = KNOWN_APPS.get(exe_name)
    action = _infer_action(command, exe_name)
    description = _build_description(app_name, action, exe_name)
    return CommandInfo(
        exe_path=exe_path, exe_name=exe_name, app_name=app_name,
        action=action, description=description,
    )
