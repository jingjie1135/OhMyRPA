# 镜界自动化

镜界自动化是基于 Python、PyQt6、ADB、Scrcpy 和 OpenCV 的通用安卓自动化工具。项目定位是脚本录制、模板管理、多设备群控和批次流程编排，不绑定任何具体应用或业务场景。

## 核心能力

- 图形化脚本录制与编辑：记录点击、滑动、等待、找图点击等动作，并保存为 JSON 脚本项目。
- 图像模板管理：通过截图、裁剪和图库管理维护 OpenCV 模板匹配素材。
- 设备抽象层：通过 `DeviceAdapter` 统一封装 ADB 截图、Scrcpy 控制和系统按键操作。
- 多设备群控：同一脚本可在多台手机或模拟器实例上并行执行。
- 流程编排：按批次启动模拟器、等待 ADB 就绪、执行脚本步骤，并按配置关闭实例。
- 模拟器适配：内置雷电模拟器、MuMu 模拟器的 ADB 路径扫描和实例管理能力。

## 快速启动

```bash
pip install -r requirements.txt
python gui.py
```

## 主要目录

```text
gui.py                    GUI 入口
gui/                      PyQt6 界面模块
script_model.py           脚本数据模型
script_engine.py          脚本执行引擎
workflow_runner.py        批次流程编排线程
device_adapter.py         ADB/Scrcpy 设备操作抽象
adb_utils.py              ADB 工具函数
scrcpy_client.py          Scrcpy 客户端
image_engine.py           模板匹配与图像识别
template_meta.py          模板元数据
emulator_manager.py       模拟器实例管理
Scripts/                  用户脚本项目目录（运行时数据）
Workflows/                用户流程配置目录（运行时数据）
targets/                  全局模板目录（运行时数据）
popups/                   弹窗守卫模板目录（运行时数据）
docs/                     项目文档
```

## 依赖

- Python 3.10+
- PyQt6
- OpenCV (`opencv-python`)
- NumPy
- adbutils
- PyAV

安装命令：

```bash
pip install -r requirements.txt
```

## 打包

Windows 下可运行：

```bat
build.bat
```

打包产物默认输出到 `dist/MirrorAutomation.exe`。
