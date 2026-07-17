# 右键上下文菜单管理器

Windows 右键上下文菜单管理器。浏览、新增、编辑、删除、屏蔽右键菜单项，按应用归类，解析常见命令，并备份/恢复相关注册表分支。启动自动提权以便管理系统级项。

## 运行

```powershell
python main.py
```

- 需 Windows + Python 3（自带 tkinter，零额外依赖）。
- 启动时若未提权，自动弹 UAC 请求管理员权限（用于编辑系统级项）；拒绝则降级为"仅用户级可编辑"模式。
- `python main.py --selftest`：烟雾测试，构建界面后立即退出（不提权、不进入主循环）。
- `python -m unittest discover -s tests -t .`：运行 114 个单元测试。
- `python scripts/probe_menus.py`：探测本机真实右键菜单项。
- `python scripts/describe_commands.py`：遍历全部命令并打印解析描述表。

## 功能

- **五种分类视图**（工具栏下拉切换）：
  - 按目标位置（文件 / 文件夹 / 桌面与背景 / 驱动器 / 文件类型 / 新建 / 发送到 / 打开方式 / WinX 菜单）--默认，最直观体现从属
  - 按作用域（用户级可编辑 / 系统级）
  - 按项目类型（自定义命令 / Shell 扩展 / 级联子菜单）
  - 扁平列表 + 搜索（按显示名/命令/路径实时过滤）
  - **按应用分类**：按所属应用分组（VSCode/Git/7-Zip…），可勾选"合并相似项"把同应用同动作、跨目标的相似项合并显示
- **新增 / 编辑 / 删除**自定义命令：显示名、命令（`%1`/`%V`/`%w`/`%L` 占位符）、图标、位置(Top/Bottom)、仅 Shift 右键、级联子菜单。
- **屏蔽 / 启用**：用系统键值法（`LegacyDisable` / `Shell Extensions\Blocked`）隐藏而非删除，可恢复。屏蔽 Shell 扩展会提示重启资源管理器生效。
- **命令解析**：详情面板自动生成"用 VSCode 打开"式描述（内置 100+ 常见应用、10 类动作识别）。
- **定位**：一键定位到注册表（regedit）/ 定位到文件（资源管理器选中 exe）。
- **显示选项**：隐藏已屏蔽项、隐藏系统项。
- **详情面板**：选中即看全部字段；可编辑项就地编辑保存。
- **备份与恢复**：导出/还原注册表分支，带时间戳历史。
- **刷新资源管理器**：改动后通知 Shell 刷新关联。

## 安全

- **提权后**可写 HKCU（用户级）与 HKLM（系统级）；**未提权**仅写 HKCU，系统级只读。
- 编辑/删除/屏蔽按钮依据提权状态与作用域自动启用/置灰。
- 删除前弹确认框并显示完整键路径；建议先备份。
- 备份存于 `%APPDATA%\右键管理器\backups\`。

## 已知限制

要点：
- 编辑级联菜单时移除子项不会自动同步到注册表；请在树中选中子项节点单独删除。
- Shell 扩展显示名为原始键名（不解析 CLSID 友好名）。
- 新建/打开方式的显示名多为 `@dll,-NNN` 资源字符串（未展开）。
- `get_entry` 不支持新场景（NEW/SENDTO/OPENWITH/WINX）路径，仅 `list_entries` 可读。

## 结构

```
context_menu_manager/
  model.py          共享数据契约
  registry.py       注册表读写层（winreg，HKCU/HKLM 路由 + 屏蔽 + 9 场景）
  elevation.py      提权与权限判定
  command_info.py   命令解析与描述
  app_info.py       应用推断与分组（含相似度合并）
  placeholders.py   命令占位符说明与校验
  backup.py         备份/恢复（reg.exe）
  explorer.py       刷新资源管理器 / 定位注册表与文件
  ui/               tkinter 界面（五种分类视图）
main.py             入口（自动提权）
scripts/probe_menus.py        注册表探测脚本
scripts/describe_commands.py  命令描述脚本
tests/              单元测试（114）
```
