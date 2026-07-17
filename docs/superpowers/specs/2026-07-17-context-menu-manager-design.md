# 右键上下文菜单管理器 - 设计文档

- 日期：2026-07-17
- 状态：已批准
- 技术栈：Python 3.14 + tkinter/ttk（零额外依赖）

## 1. 目标

一个 Windows 右键上下文菜单管理器，能够：

- 直观地浏览每个右键菜单项目的信息与从属关系（目标场景、作用域、级联父子）。
- 按多种分类方式查看（目标位置 / 作用域 / 项目类型 / 扁平+搜索）。
- 新增 / 编辑 / 删除自定义命令（含图标、位置、Shift-only、级联子菜单）。
- 备份与恢复相关注册表分支（安全网）。
- 默认编辑 HKCU（用户级，无需管理员），系统级条目只读展示。

## 2. 非目标（YAGNI）

- 应用内撤销队列（已有备份/恢复作为安全网，不另做）。
- 启用/禁用切换功能（本期不做；仅展示 `blocked` 状态）。
- 管理 Shell 扩展（CLSID）的内容，仅只读展示。
- 强制管理员权限 / 写 HKLM。

## 3. 架构

```
右键管理器/
├── context_menu_manager/        # 主包
│   ├── model.py                 # 数据模型：MenuEntry / 枚举 / 序列化（共享契约）
│   ├── registry.py              # 注册表读写层（纯 winreg，无 UI）
│   ├── backup.py                # 备份/恢复（reg export|import）
│   ├── placeholders.py          # %1/%V/%w 占位符说明与校验
│   ├── explorer.py              # 刷新资源管理器（SHChangeNotify）
│   └── ui/
│       ├── main_window.py       # 主窗口：工具栏 + 树 + 详情面板
│       ├── tree_view.py         # 多分类树视图（核心）
│       ├── detail_panel.py      # 右侧详情/编辑
│       ├── edit_dialog.py       # 新增/编辑对话框
│       └── backup_dialog.py     # 备份管理
├── main.py                      # 入口
├── tests/                       # pytest
└── docs/superpowers/specs/      # 本文档
```

分层原则：注册表操作全部锁在 `registry.py`，UI 不直接碰 `winreg`；`model.py` 是前后端共享契约。

## 4. 数据模型（model.py）

```python
class TargetContext(Enum):
    FILES = "文件（所有文件 *）"
    DIRECTORY = "文件夹"
    DIRECTORY_BACKGROUND = "桌面与文件夹背景"
    DRIVE = "驱动器"
    ALLFILESYSTEMOBJECTS = "所有文件系统对象"
    FILETYPE = "文件类型"          # 配合 file_type_ext

class Scope(Enum):
    USER = "用户级（可编辑）"        # HKCU\Software\Classes
    SYSTEM = "系统级（只读）"        # HKCR/HKLM 合并视图

class EntryKind(Enum):
    COMMAND = "自定义命令"          # shell\<名>\command
    SHELLEX = "Shell 扩展"          # shellex\ContextMenuHandlers（CLSID，只读）
    CASCADE = "级联子菜单"          # 含子命令的父项

@dataclass
class MenuEntry:
    target: TargetContext
    file_type_ext: str | None      # 仅 FILETYPE，如 ".txt"
    scope: Scope                   # 决定可否编辑
    kind: EntryKind
    key_path: str                  # 完整注册表路径
    name: str                      # 键名（注册表标识）
    display_name: str              # MUIVerb 或默认值
    command: str | None            # command 默认值
    icon: str | None
    position: str | None           # Top/Bottom
    extended: bool                 # 仅 Shift+右键显示
    clsid: str | None              # SHELLEX 用
    children: list["MenuEntry"]    # 级联子项 -> 体现"从属"
    blocked: bool                  # 键名带屏蔽前缀（仅展示）
```

从属关系由 `children`（级联父子）与 `target`/`scope`（归属场景与作用域）共同体现。

## 5. 多分类树视图（ui/tree_view.py）

左侧 `ttk.Treeview`，顶部工具栏有"分类方式"下拉框，切换四种视图：

1. **按目标位置**（默认）：根节点为场景（文件/文件夹/背景/驱动器/文件类型），下挂该场景菜单项；级联子菜单可展开为父->子。最直观体现从属。
2. **按来源/作用域**：分"用户级（可编辑）"与"系统级（只读）"两棵子树。
3. **按项目类型**：自定义命令 / Shell 扩展 / 级联子菜单。
4. **扁平列表**：全部条目按字母排序，配搜索框（按显示名/命令/路径实时过滤）。

节点显示：图标占位 + 显示名 + 徽章（`用户`/`系统`/`只读`）+ 命令摘要。点击节点 -> 右侧详情面板显示全部字段并可编辑（系统项编辑按钮置灰）。

```
📁 文件（所有文件 *）
   ├─ 用 VSCode 打开            [用户]
   ├─ 📂 我的工具集              [用户] ▸  ← 级联，可展开
   │     ├─ 压缩
   │     └─ 上传
   └─ Open with PowerShell      [系统/只读]
```

## 6. 注册表操作（registry.py）

接口（前后端契约）：

```python
def list_entries(target: TargetContext, file_type_ext: str | None = None) -> list[MenuEntry]
def get_entry(key_path: str) -> MenuEntry
def create_entry(entry: MenuEntry) -> None          # 写 HKCU
def update_entry(entry: MenuEntry) -> None           # 写 HKCU
def delete_entry(key_path: str) -> None
def enum_targets() -> list[TargetContext]
def list_file_types() -> list[str]                   # 扫描 HKCR 下的扩展名
def resolve_scope(key_path: str) -> Scope            # 判定 HKCU 是否存在
```

- 读取用 HKCR（合并视图）；可编辑性判定检查 `HKCU\Software\Classes\<相对路径>` 是否存在 -> 存在则 `USER`，否则 `SYSTEM` 只读。
- 新建/编辑一律写 `HKCU\Software\Classes\...`，无需管理员。
- 目标键根：
  - `*\shell`、`Directory\shell`、`Directory\Background\shell`、`Drive\shell`、`AllFilesystemObjects\shell`
  - 文件类型：`HKCR\.<ext>` 取默认值（ProgID）-> `HKCR\<ProgID>\shell`
- 静态命令：`shell\<名>` 默认值为显示名（或 `MUIVerb`），`shell\<名>\command` 默认值为命令行。
- 级联：`shell\<父>\shell\<子>\command`，父项 `SubCommands` 或直接子键。
- Shell 扩展：`shellex\ContextMenuHandlers\<名>` 默认值为 CLSID，只读展示。
- 类型化异常：`RegistryAccessError`、`KeyNotFoundError`、`PermissionDeniedError`、`ParseError`。

## 7. 参数占位符（placeholders.py）

`%1`=文件路径、`%V`=文件/文件夹路径、`%w`=工作目录、`%L`=长路径。提供说明表与基本校验（至少含一个占位符或为静态命令）。

## 8. 备份与恢复（backup.py）

```python
def export_branch(key_path: str, dest: Path) -> Path   # reg.exe export
def backup_all(targets: list[TargetContext]) -> Path    # 带时间戳
def restore_from(reg_file: Path) -> None                # reg.exe import
def list_backups() -> list[BackupInfo]
def delete_backup(name: str) -> None
```

- 备份目录：`%APPDATA%\右键管理器\backups\`，文件名带时间戳。
- 新增/编辑/删除前自动备份受影响分支（可关）。
- 首次运行导出"原始快照"作为底线。
- 备份管理对话框：列出历史、一键还原、删除。

## 9. 刷新资源管理器（explorer.py）

- `ctypes` 调 `SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)` 刷新关联。
- 兜底按钮：`taskkill /f /im explorer.exe` 后 `start explorer.exe`。

## 10. 错误处理

- 类型化异常向上传播；UI 层捕获并转为友好提示。
- 删除前确认对话框；命令/路径校验。
- 单个坏键不致崩溃：跳过并在状态栏记录。
- 系统键访问被拒时优雅降级为只读。

## 11. 测试

- pytest 覆盖：`registry.py`（在 HKCU 测试子键做真实增删改，测完清理）、`model.py` 序列化、`backup.py` 路径生成与 `.reg` 解析、`placeholders.py` 校验。
- UI 层手动测试清单。
- 遵循 TDD（superpowers）。

## 12. 技术细节

- 纯标准库 + tkinter/ttk，零额外依赖，`python main.py` 运行。
- 图标：显示路径文本；`.ico/.png/.bmp` 尽力用 `tkinter.PhotoImage` 预览。
- 打包：附带 PyInstaller 脚本，可生成单 exe。

## 13. 并行开发分工

两个 subagent 并行：

- **A（后端/提取）**：`model.py`、`registry.py`、`placeholders.py`、`backup.py`、`explorer.py` + tests。先用脚本验证能从真实注册表提取出哪些右键项目及其信息。
- **B（前端）**：`ui/` 包 + `main.py`，依据 `model.py` 契约与 `registry.py` 接口构建界面。

共享契约 `model.py` 与 `registry.py` 接口先行确定，使两者可并行。

## 14. 实现备忘与已知限制（集成后补充）

- **`blocked` 判定**：实现中用注册表 `LegacyDisable` 值的存在性判定（真实 Windows 禁用机制），而非键名前缀。`model.py` 注释已同步。
- **级联子菜单编辑**：`update_entry` 对级联项是增量式--会写入/更新 `children` 列表中的子项，但**不会删除**列表中未出现的旧子项。移除子项请改为在树中选中该子项节点后点"删除"（级联子项是可单独选中的可编辑节点）。此限制是非破坏性的（不会误删），故暂不引入按名匹配删除以免误删。
- **Shell 扩展显示名**：SHELLEX 的 `display_name` 为原始键名，不解析 CLSID 友好名（需 COM 查询，超范围）。展示以键名 + CLSID 为准。
- **备份范围**：`backup_all` 导出 HKCU 分支（无需管理员）；HKCR 分支导出可能需管理员，遇权限问题抛 `RegistryError`。
- **command 值类型**：写为 `REG_EXPAND_SZ`，`%SystemRoot%` 等环境变量会被系统展开，`%1`/`%V` 等 Shell 占位符不受影响。
- **测试**：46 个单元测试通过（标准库 `unittest`，HKCU 测试子键真实 CRUD 后清理）；`python main.py --selftest` 对真实注册表完整构建四种分类视图（1113/796/797/794 节点）。
