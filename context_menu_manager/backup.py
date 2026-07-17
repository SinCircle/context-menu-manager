r"""备份与恢复注册表分支（reg.exe export / import）。

备份目录：%APPDATA%\右键管理器\backups\
- backup_branch：导出单分支到 .reg 文件。
- backup_all：导出多个 target 的 HKCU 分支，合并为一个带时间戳的 .reg 文件。
- restore_from：reg.exe import 恢复。
- list_backups / delete_backup：管理历史备份。

注意：reg export 对 HKCU 分支无需管理员；HKCR 分支导出可能需要管理员，
遇权限问题捕获并抛 RegistryError，不崩。
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .model import TargetContext
from .registry import RegistryError, _TARGET_SHELL_PATH, _shellex_rel_path

BACKUP_DIR: Path = Path(
    os.environ.get("APPDATA") or str(Path.home())
) / "右键管理器" / "backups"

_REG_ROOT_MAP = {
    "HKCR": "HKEY_CLASSES_ROOT",
    "HKCU": "HKEY_CURRENT_USER",
    "HKLM": "HKEY_LOCAL_MACHINE",
}

_REG_HEADER = "Windows Registry Editor Version 5.00"


@dataclass
class BackupInfo:
    name: str
    path: Path
    created_at: str   # ISO 时间戳
    targets: list[str]


# ── 工具 ──────────────────────────────────────────────────────
def _ensure_backup_dir() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_reg_path(key_path: str) -> str:
    r"""把 HKCR\... / HKCU\... 转为 reg.exe 需要的 HKEY_*\... 形式。"""
    parts = key_path.split("\\", 1)
    root = parts[0]
    rest = parts[1] if len(parts) > 1 else ""
    full_root = _REG_ROOT_MAP.get(root, root)
    return full_root + ("\\" + rest if rest else "")


def _run_reg_export(reg_path: str, dest: Path) -> None:
    """执行 reg.exe export 到 dest；失败抛 RegistryError。"""
    cmd = ["reg", "export", reg_path, str(dest), "/y"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=30)
    except FileNotFoundError as exc:
        raise RegistryError(f"无法找到 reg.exe: {exc}")
    except subprocess.TimeoutExpired:
        raise RegistryError("reg export 超时")
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "").strip()
        raise RegistryError(f"reg export 失败（{reg_path}）: {msg}")


def _run_reg_import(reg_file: Path) -> None:
    """执行 reg.exe import；失败抛 RegistryError。"""
    cmd = ["reg", "import", str(reg_file)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=60)
    except FileNotFoundError as exc:
        raise RegistryError(f"无法找到 reg.exe: {exc}")
    except subprocess.TimeoutExpired:
        raise RegistryError("reg import 超时")
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "").strip()
        raise RegistryError(f"reg import 失败: {msg}")


def _target_branches(tgt: TargetContext) -> list[str]:
    r"""返回 target 对应的 HKCU 相对分支（shell + shellex）。

    FILETYPE 不参与批量备份（需逐个 ext），返回空。
    """
    if tgt is TargetContext.FILETYPE:
        return []
    shell_rel = _TARGET_SHELL_PATH[tgt]
    shellex_rel = _shellex_rel_path(tgt, None)
    return [shell_rel, shellex_rel]


def _read_reg_text(f: Path) -> str:
    """读取 .reg 文件，自动适配编码（BOM/无BOM 的 UTF-16/UTF-8）。"""
    raw = f.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-16-le")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    return raw.decode("latin-1")


def _merge_reg_files(parts: list[Path], dest: Path) -> None:
    """把多个 .reg 文件合并为一个（去重 header）。"""
    chunks: list[str] = [_REG_HEADER, ""]
    for p in parts:
        text = _read_reg_text(p)
        lines = text.splitlines()
        # 跳过 header 行及其后的空行
        idx = 0
        if lines and lines[0].startswith("Windows Registry Editor"):
            idx = 1
            if idx < len(lines) and lines[idx] == "":
                idx += 1
        body = "\r\n".join(lines[idx:])
        if body.strip():
            chunks.append(body)
    # utf-16 写入会自动加 BOM，reg.exe import 需要 BOM
    dest.write_text("\r\n".join(chunks) + "\r\n", encoding="utf-16")


# ── target 标签匹配（用于解析 .reg 中的分支归属）─────────────────
def _match_target_label(rel: str) -> str | None:
    r"""从 HKCU\Software\Classes 下的相对路径推断 target label。"""
    for prefix, tgt in [
        (r"Directory\Background\shell", TargetContext.DIRECTORY_BACKGROUND),
        (r"Directory\Background\shellex", TargetContext.DIRECTORY_BACKGROUND),
        (r"Directory\shell", TargetContext.DIRECTORY),
        (r"Directory\shellex", TargetContext.DIRECTORY),
        (r"*\shell", TargetContext.FILES),
        (r"*\shellex", TargetContext.FILES),
        (r"Drive\shell", TargetContext.DRIVE),
        (r"Drive\shellex", TargetContext.DRIVE),
        (r"AllFilesystemObjects\shell", TargetContext.ALLFILESYSTEMOBJECTS),
        (r"AllFilesystemObjects\shellex", TargetContext.ALLFILESYSTEMOBJECTS),
    ]:
        if rel == prefix or rel.startswith(prefix + "\\"):
            return tgt.label
    return None


def _extract_targets_from_reg(f: Path) -> list[str]:
    """从 .reg 文件内容提取涉及的 target 标签。"""
    try:
        text = _read_reg_text(f)
    except OSError:
        return []
    found: list[str] = []
    for m in re.finditer(r"\[HKEY_[A-Z_]+\\Software\\Classes\\([^\]]+)\]",
                         text):
        rel = m.group(1)
        label = _match_target_label(rel)
        if label and label not in found:
            found.append(label)
    if not found:
        # 可能是 HKCR 导出（无 Software\Classes 前缀）
        for m in re.finditer(r"\[HKEY_CLASSES_ROOT\\([^\]]+)\]", text):
            rel = m.group(1)
            label = _match_target_label(rel)
            if label and label not in found:
                found.append(label)
    return found


# ── 公开接口 ──────────────────────────────────────────────────
def backup_branch(key_path: str) -> Path:
    """reg.exe export 单分支，返回生成的 .reg 文件路径。"""
    _ensure_backup_dir()
    reg_path = _normalize_reg_path(key_path)
    safe = re.sub(r'[\\/:*?"<>|]', "_", key_path)
    dest = BACKUP_DIR / f"{safe}.reg"
    _run_reg_export(reg_path, dest)
    return dest


def backup_all(targets: list[TargetContext]) -> Path:
    """多分支备份（HKCU 下各 target 的 shell+shellex），带时间戳文件名。

    不存在的分支静默跳过；返回合并后的 .reg 文件路径。
    """
    _ensure_backup_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    final = BACKUP_DIR / f"backup_{ts}.reg"
    parts: list[Path] = []
    backed: list[str] = []
    for tgt in targets:
        for rel in _target_branches(tgt):
            cu_path = "HKCU\\Software\\Classes\\" + rel
            tmp = BACKUP_DIR / f".tmp_{ts}_{len(parts)}.reg"
            try:
                _run_reg_export(_normalize_reg_path(cu_path), tmp)
                parts.append(tmp)
                if tgt.label not in backed:
                    backed.append(tgt.label)
            except RegistryError:
                # 分支不存在或权限不足 -> 跳过
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
    if not parts:
        # 无任何分支可备份：仍生成一个空 header 文件
        final.write_text(_REG_HEADER + "\r\n\r\n", encoding="utf-16")
    else:
        _merge_reg_files(parts, final)
        for p in parts:
            try:
                p.unlink()
            except OSError:
                pass
    return final


def restore_from(reg_file: Path) -> None:
    """reg.exe import 恢复。"""
    reg_file = Path(reg_file)
    if not reg_file.exists():
        raise RegistryError(f"备份文件不存在: {reg_file}")
    _run_reg_import(reg_file)


def list_backups() -> list[BackupInfo]:
    """列出所有备份（按创建时间倒序）。"""
    _ensure_backup_dir()
    infos: list[BackupInfo] = []
    for f in sorted(BACKUP_DIR.glob("*.reg"), reverse=True):
        if f.name.startswith(".tmp_"):
            continue
        stat = f.stat()
        created_at = datetime.fromtimestamp(stat.st_mtime).isoformat()
        targets = _extract_targets_from_reg(f)
        infos.append(BackupInfo(
            name=f.stem, path=f, created_at=created_at, targets=targets))
    return infos


def delete_backup(name: str) -> None:
    """按名称（stem）删除备份文件。"""
    _ensure_backup_dir()
    target = BACKUP_DIR / f"{name}.reg"
    if not target.exists():
        raise RegistryError(f"备份不存在: {name}")
    try:
        target.unlink()
    except OSError as exc:
        raise RegistryError(f"删除备份失败: {exc}")
