# GUI TABS KNOWLEDGE BASE

## OVERVIEW

`gui/tabs/` 包含四个主功能页：图库、脚本编写、循环脚本、流程编排。它们共享 `ScriptModel`/`ActionNode` 和 `gui.action_props`。

## STRUCTURE

```text
gui/tabs/
├── library_tab.py       # targets/ 图库目录、缩略图、多选测试、删除
├── script_tab.py        # 脚本录制/编辑；保存到 Scripts/<name>/script.json
├── loop_script_tab.py   # 循环脚本配置、多模板转换、导入外部脚本
├── workflow_tab.py      # Workflows/<name>/workflow.json + 设备批次配置
└── __init__.py          # 导出四个 Tab 类
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| 全局图库 | `library_tab.py` | 只管理 `targets/`；这是运行时数据目录 |
| 录制/普通脚本 | `script_tab.py` | 点击录制、快照、升级找图、弹窗守卫配置 |
| 循环脚本 | `loop_script_tab.py` | `ScriptConfig.scan_interval/max_loops`；可转换为 `multi_match` |
| 流程编排 | `workflow_tab.py` | 复用 `ActionNode`；另有批次设备配置 |
| 动作属性 | `../action_props.py` | Tab 只传 context 和保存模型，不复制 builder |

## CODE MAP

| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `ImageLibraryTab` | class | `library_tab.py` | 扫描/展示/维护 `targets/` 子目录 |
| `ScriptTab` | class | `script_tab.py` | 普通脚本项目的录制、编辑、保存、运行时配置同步 |
| `_RecordClickWorker` | class | `script_tab.py` | 点击录制时后台 ADB 截图保存到 `Temp/` |
| `LoopScriptTab` | class | `loop_script_tab.py` | 循环执行参数和多模板匹配脚本生成 |
| `WorkflowModel` | class | `workflow_tab.py` | `Workflows/<name>/workflow.json` 数据模型 |
| `WorkflowTab` | class | `workflow_tab.py` | 流程步骤和设备批次编辑器 |

## CONVENTIONS

- 三个编辑类 Tab 都用三栏式布局：左侧 `QTreeWidget` 工具箱，中间 `QListWidget` 步骤列表，右侧 `QStackedWidget` 属性面板。
- `QListWidgetItem.UserRole` 存 `ActionNode.id`；拖拽排序后必须同步 model 中 actions/steps 顺序。
- 新动作默认参数要在对应 Tab 的 toolbox double-click 逻辑里补齐，并在 `action_props.py` / `script_engine.py` 同步。
- `ScriptTab` 排除 `multi_match`；`WorkflowTab` 排除 `loop_start`/`loop_end`；`LoopScriptTab` 支持 `multi_match`。
- `ScriptTab.get_runtime_config()` 和 `sync_to_runtime_config()` 被 `MainWindow` 热更新调用；改运行参数时保持兼容。
- 流程 `WorkflowModel` 使用文件夹模式，并会迁移旧版扁平 JSON。

## ANTI-PATTERNS

- 不要把 `Scripts/`、`Workflows/`、`targets/` 当项目源码修改；这些是用户运行时数据。
- 不要复制粘贴一份动作属性表到 Tab；维护 `gui/action_props.py` 这个共享源。
- 不要让录制时的点击再走后台 ADB tap；预览区 Scrcpy 已实时发送触控，录制线程只记录。
- 不要假设 `loop_start`/`loop_end` 已有执行语义；当前执行器跳过它们。
- 不要在无设备环境下把 Scrcpy/ADB 交互测试作为默认单元测试。

## COMMANDS

```bash
python -m py_compile gui/tabs/script_tab.py gui/tabs/loop_script_tab.py gui/tabs/workflow_tab.py gui/tabs/library_tab.py
python gui.py
```

## NOTES

- `script_tab.py` 是最热路径，包含录制、保存、升级找图、运行时同步；小步修改并手动跑 GUI。
- `loop_script_tab.py` 的转换路径依赖 `gui/convert_dialog.py` 和 `multi_match` 子动作 builder。
- `workflow_tab.py` 的执行不在本目录，实际运行由 `workflow_runner.py` 接管。
