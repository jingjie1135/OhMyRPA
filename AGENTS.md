# PROJECT KNOWLEDGE BASE

**Generated:** 2026-05-25
**Commit:** 6875e7b
**Branch:** main

## OVERVIEW

镜界自动化是 Windows Python/PyQt6 安卓自动化工具。核心栈：PyQt6 GUI、ADB/Scrcpy 设备控制、OpenCV 模板匹配、JSON 脚本/流程模型、Nuitka 单文件打包。

## STRUCTURE

```text
./
├── gui.py                    # 兼容入口；实际入口在 gui.__init__.main()
├── gui/                      # PyQt6 主窗口、控件、Tab、属性面板；见 gui/AGENTS.md
├── script_model.py           # ActionNode/ScriptConfig/ScriptModel；Scripts/<name>/script.json
├── script_engine.py          # ActionNode 执行器；tap/swipe/find/wait/multi_match/run_script/loop
├── workflow_runner.py        # 流程批次 QThread；批次串行、设备内并行
├── device_adapter.py         # DeviceAdapter 抽象；ADB 无损截图 vs Scrcpy 低延迟控制
├── scrcpy_client.py          # 自研 scrcpy v3.3.3 客户端和控制通道
├── emulator_manager.py       # 雷电/MuMu/真机扫描、启动、关闭、ADB 就绪等待
├── image_engine.py           # OpenCV 模板加载、缓存、NMS、匹配
├── template_meta.py          # Pictures/meta.json 偏移量缓存
├── build.bat                 # 项目文件；Nuitka 打包 MirrorAutomation.exe
├── docs/                     # PyQt6、顶栏、MuMuManager 参考文档
├── Scripts/                  # 用户脚本运行时数据；不要改
├── Workflows/                # 用户流程运行时数据；不要改
├── targets/                  # 全局模板运行时数据；不要改
└── popups/                   # 弹窗守卫模板运行时数据；不要改
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| 启动/应用级设置 | `gui.py`, `gui/__init__.py`, `gui/main_window.py` | 入口命令是 `python gui.py`；`main.py` 已删除 |
| 脚本数据格式 | `script_model.py` | 项目目录格式：`Scripts/<项目>/script.json`, `Temp/`, `Pictures/` |
| 动作执行语义 | `script_engine.py` | 统一走 `DeviceAdapter`；新增动作要同步 UI 注册表 |
| 设备控制 | `device_adapter.py`, `adb_utils.py`, `scrcpy_client.py` | ADB 用于无损截图/群控；Scrcpy 用于实时预览/录制低延迟触控 |
| 模板匹配 | `image_engine.py`, `template_meta.py`, `crop_utils.py` | 模板文件常带 `@WxH` 后缀；偏移量在 `meta.json` |
| 模拟器编排 | `emulator_manager.py`, `workflow_runner.py`, `docs/MuMuManager命令行.md` | 雷电端口和 MuMu 端口推导在代码内 |
| GUI 约定 | `gui/AGENTS.md` | 主窗口、控件、线程、样式 |
| Tab 约定 | `gui/tabs/AGENTS.md` | 脚本、循环、流程、图库四个功能页 |
| 清理契约 | `test_project_cleanup.py` | 禁止旧品牌/旧业务/旧入口回流 |

## CODE MAP

| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `main()` | function | `gui/__init__.py` | QApplication、图标、中文 Qt 翻译、字体、MainWindow |
| `MainWindow` | class | `gui/main_window.py` | 顶栏、设备栏、截图预览、四个 Tab、群控、线程协调 |
| `ScriptModel` | class | `script_model.py` | 脚本 JSON 持久化、图片内化、项目列表/导入 |
| `ScriptEngine` | class | `script_engine.py` | 线性/循环执行 ActionNode，弹窗守卫，嵌套 run_script |
| `DeviceAdapter` | ABC | `device_adapter.py` | 设备操作唯一抽象；调用方不要直连 ADB/Scrcpy |
| `HybridDeviceAdapter` | class | `device_adapter.py` | 默认执行适配器，按能力选择 ADB/Scrcpy |
| `ScrcpyClient` | class | `scrcpy_client.py` | H.264 帧流和控制 socket 生命周期 |
| `WorkflowRunner` | class | `workflow_runner.py` | 批次流程执行线程；手动停止不关闭实例 |
| `EmulatorManager` | class | `emulator_manager.py` | 模拟器发现、launch/quit/wait_adb_ready |
| `ACTION_REGISTRY` | dict | `gui/action_props.py` | 所有动作类型的 UI 注册源 |

## CONVENTIONS

- 项目名是 `镜界自动化`；打包产物是 `MirrorAutomation.exe`。
- `build.bat` 是项目文件，不是运行时数据；修改品牌/入口/资源时同步它。
- 运行时/用户数据：`Daily/`, `Scripts/`, `Workflows/`, `targets/`, `popups/`。默认不要编辑、清空、重命名或格式化这些目录。
- 入口是 `python gui.py`；不要恢复 `main.py`、`shop_bot.py`、`recovery.py`。
- GUI 线程：耗时 ADB/Scrcpy/执行器操作放入 `QThread` 或后台线程；UI 更新通过 `pyqtSignal` 回主线程。
- 动作新增/改名必须同时检查 `gui/action_props.py`、`script_engine.py`、`script_model.py`、相关 Tab 的默认参数和显示文本。
- 脚本/流程模型复用 `ActionNode`；流程文件在 `Workflows/<name>/workflow.json`，脚本文件在 `Scripts/<name>/script.json`。
- 图片模板路径优先级通常是绝对路径 → 当前项目 `Pictures/` → `templates/`；当前仓库没有跟踪 `templates/`。
- 中文注释和 UI 文案是常态；不要把用户可见文案批量英文化。

## ANTI-PATTERNS (THIS PROJECT)

- 不要把项目重新绑定到具体游戏/业务；`test_project_cleanup.py` 会拦截旧词。
- 不要修改运行时数据目录来“修复测试”或清理仓库。
- 不要绕过 `DeviceAdapter` 在执行引擎里直接调用 `adb_utils`，除非是在已存在的局部兼容路径中做最小修复。
- 不要在 GUI 主线程里运行阻塞 ADB、截图、模板匹配、模拟器启动。
- 不要把 `loop_start`/`loop_end` 当作已实现控制流；当前执行器只警告并跳过。
- 不要把 `docs/top_bar.py` 当运行时代码；运行时代码在 `gui/top_bar.py`。

## UNIQUE STYLES

- 大文件集中：`gui/main_window.py`、`gui/tabs/script_tab.py`、`gui/action_props.py`、`scrcpy_client.py`。优先局部手术，避免顺手重构。
- 视觉/交互偏 Windows 桌面：微软雅黑、固定按钮尺寸、`QStackedWidget` 页面切换、浅蓝选中态。
- 设备执行日志大量使用中文和 emoji；新增日志保持用户可读，不要替换为机器化 debug 文案。
- 弹窗守卫由连续找图失败触发，默认目录是 `popups`。

## COMMANDS

```bash
pip install -r requirements.txt
python gui.py
python -m unittest test_project_cleanup.py
python -m py_compile bot_worker.py config.py device_adapter.py gui.py gui/tabs/script_tab.py test_scrcpy.py test_project_cleanup.py
build.bat
```

## NOTES

- LSP 环境未提供 Python type server；以 `py_compile`、unittest、人工 GUI/设备路径验证为准。
- `test_scrcpy.py` 需要可用 ADB 设备和 scrcpy server 环境；不要放进无设备的默认快速测试。
- `build.bat` 为规避中文路径复制到 `G:\MirrorAutomationBuild`，并排除 `Daily`/`Scripts` 等运行时目录。
- `scrcpy-server` 是打包资源；删除或改名会破坏实时预览/控制。
- `nuitka-crash-report.xml`, `.omo/`, `.gemini/`, `dist/`, `build/`, `.venv/` 已忽略。
