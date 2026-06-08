# GUI PACKAGE KNOWLEDGE BASE

## OVERVIEW

`gui/` 承载 PyQt6 桌面界面：应用入口、主窗口、截图预览、自定义控件、动作属性面板和四个功能 Tab。

## STRUCTURE

```text
gui/
├── __init__.py                 # QApplication 入口、图标、Qt 中文翻译、字体
├── main_window.py              # 主窗口；设备栏、截图区、Tab、群控、线程协调
├── workers.py                  # ScreencapWorker；ADB 单帧/Scrcpy 连续流
├── widgets.py                  # ScreenshotWidget；截图显示、裁切、录制触控
├── action_props.py             # ACTION_REGISTRY + 动态属性面板构建器
├── template_gallery_dialog.py  # 模板选择覆盖页
├── template_save_dialog.py     # 模板保存和偏移量可视化
├── multi_region_widget.py      # 多区域框选控件，转换向导使用
├── convert_dialog.py           # 流水线脚本 → 多模板匹配转换
├── device_selector.py          # 流程批次设备选择页
├── top_bar.py                  # 运行时顶栏组件
└── tabs/                       # 四个主功能页；见 gui/tabs/AGENTS.md
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| 应用启动 | `__init__.py`, `../gui.py` | `gui.py` 只转调 `gui.main()` |
| 主窗口布局/状态 | `main_window.py` | 设备扫描、截图 worker、群控、执行/暂停/停止 |
| 截图和录制交互 | `widgets.py`, `workers.py` | Scrcpy 实时触摸；ADB 无损截图保存快照 |
| 动作参数 UI | `action_props.py` | 新动作先改注册表和 builder，再改 Tab/执行器 |
| 顶栏 | `top_bar.py`, `docs/顶栏设计规范.md` | `docs/top_bar.py` 是参考拷贝 |
| 模板选择/保存 | `template_gallery_dialog.py`, `template_save_dialog.py`, `multi_region_widget.py` | 偏移量写 `meta.json` |

## CODE MAP

| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `MainWindow` | class | `main_window.py` | 组合所有 UI 和后台线程 |
| `AdbTask` | class | `main_window.py` | 通用 ADB 后台 callable 包装 |
| `ScreencapWorker` | class | `workers.py` | 单帧 ADB 与连续 Scrcpy 两种截图模式 |
| `ScreenshotWidget` | class | `widgets.py` | 自绘截图、坐标拾取、裁切保存、实时触控 |
| `ACTION_REGISTRY` | dict | `action_props.py` | 动作类型、图标、显示名、分类唯一注册源 |
| `build_action_props()` | function | `action_props.py` | 根据 ActionNode 动态生成右侧属性面板 |
| `ConvertDialog` | class | `convert_dialog.py` | 从录制流水线批量提取模板 |

## CONVENTIONS

- UI 样式集中用 `gui/constants.py:create_font()` 和常量色；局部样式跟随现有控件。
- `QStackedWidget` 用于覆盖式页面切换，不要用新窗口替代图库/设备选择这种内嵌流程。
- 截图显示走自绘控件；坐标转换集中在 `_calc_layout()` / `_widget_to_original()`。
- 实时预览/录制依赖 Scrcpy 控制通道；普通执行和群控偏向 ADB/Hybrid adapter。
- 主窗口只保存线程引用，停止时 `requestInterruption()`；不要让临时 `QThread` 被 GC。
- 属性面板 builder 接收 `context`，用它拿 `device_id`、`adapter`、`pictures_dir`、测试按钮回调。

## ANTI-PATTERNS

- 不要在 GUI 主线程做阻塞 `subprocess.run()`、ADB 截图、OpenCV 扫描。
- 不要让 worker 直接改 QWidget；通过 signal 回主线程。
- 不要把动作 UI 分散到每个 Tab；公共动作参数属于 `action_props.py`。
- 不要移动或删除 `official_qr.png`、`donate_qr.png`、`icon.png`，顶栏和打包依赖这些资源。
- 不要把 `docs/top_bar.py` 的示例改成运行时代码。

## COMMANDS

```bash
python -c "import gui; print(gui.main.__name__)"
python gui.py
```

## NOTES

- `main_window.py` 仍含少量旧命名如 `_buy_count`；清理时先确认没有 UI 绑定。
- `widgets.py` 在录制模式下点击/滑动已经通过 Scrcpy 实时发给设备，录制 worker 只保存快照和动作数据。
- `action_props.py` 的测试按钮会开后台 `threading.Thread`，不要在其中触碰 Qt UI。
