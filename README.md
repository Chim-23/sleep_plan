# Sleep Plan

Windows 桌面小工具：按计划执行 **睡眠**、**锁屏**、**关机**、**重启**。界面基于 CustomTkinter，深色简洁风格。

## 功能

- **一次任务**：指定日期与时间执行一次
- **每天重复**：每天在固定时间执行（如 23:30 锁屏）
- **倒计时**：若干秒/分/小时后执行；选择「倒计时」时显示 15 分钟 / 30 分钟 / 1 小时快捷按钮
- **睡眠/锁屏/关机/重启**：到点前 **15 秒** 弹窗倒计时，可「取消此次计划」或「立即执行」，超时自动执行
- **设置**（标题栏右侧）：关闭窗口最小化到托盘（默认开）、开机自启（默认开）
- **历史**：每条计划每次触发只记一条最终结果（已执行 / 已取消 / 失败），见 `~/.sleep_plan/history.json`
- 关机/重启使用 **`/f` 强制**，尽量关闭阻止关机的应用
- 计划保存在 `~/.sleep_plan/tasks.json`，设置在 `~/.sleep_plan/settings.json`
- 窗口与 `SleepPlan.exe` 使用同一套 `assets/icon.ico` 图标

## 运行（开发）

```bash
pip install -r requirements.txt
python main.py
```

## 打包 exe

双击 `build.bat`，或在项目目录执行：

```bash
pip install -r requirements.txt
pyinstaller --onefile --windowed --name SleepPlan main.py
```

生成的可执行文件：`dist/SleepPlan.exe`

## 说明

- 睡眠与锁屏通过 Windows API 调用，无需额外管理员权限（一般用户即可）
- 关机/重启使用系统 `shutdown` 命令；若需延迟关机可在代码中扩展
- 仅支持 Windows