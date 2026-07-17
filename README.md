# 右键上下文菜单管理器

Windows 右键上下文菜单管理器。浏览、新增、编辑、删除右键菜单项，并备份/恢复相关注册表分支。

## 运行

```powershell
python main.py
```

- 需 Windows + Python 3（自带 tkinter，零额外依赖）。
- `python main.py --selftest`：烟雾测试，构建界面后立即退出（不进入主循环）。
- `python -m unittest discover -s tests -t .`：运行 46 个单元测试。

## 功能

- **四种分类视图**（工具栏下拉切换）：
  - 按目标位置（文件 / 文件夹 / 桌面与背景 / 驱动器 / 文件类型）--默认，最直观体现从属
  - 按作用域（用户级可编辑 / 系统级只读）
  - 按项目类型（自定义命令 / Shell 扩展 / 级联子菜单）
  - 扁平列表 + 搜索（按显示名/命令/路径实时过滤）
- **新增 / 编辑 / 删除**自定义命令：显示名、命令（`%1`/`%V`/`%w`/`%L` 占位符）、图标、位置(Top/Bottom)、仅 Shift 右键、级联子菜单。
- **详情面板**：选中即看全部字段；用户级可就地编辑保存。
- **备份与恢复**：导出/还原注册表分支，带时间戳历史。
- **刷新资源管理器**：改动后通知 Shell 刷新关联。

## 安全

- **只写 HKCU**（`HKCU\Software\Classes\...`），无需管理员，不影响其他用户。
- 系统级条目（HKCR/HKLM）只读展示，编辑/删除按钮置灰。
- 删除前弹确认框并显示完整键路径；建议先备份。
- 备份存于 `%APPDATA%\右键管理器\backups\`。

## 已知限制

见 `docs/superpowers/specs/2026-07-17-context-menu-manager-design.md` 第 14 节。要点：
- 编辑级联菜单时移除子项不会自动同步到注册表；请在树中选中子项节点单独删除。
- Shell 扩展显示名为原始键名（不解析 CLSID 友好名）。

## 结构

```
context_menu_manager/
  model.py          共享数据契约
  registry.py       注册表读写层（winreg）
  placeholders.py   命令占位符说明与校验
  backup.py         备份/恢复（reg.exe）
  explorer.py       刷新资源管理器
  ui/               tkinter 界面
main.py             入口
scripts/probe_menus.py   注册表探测脚本
tests/              单元测试
```
