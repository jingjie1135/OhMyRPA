# 模拟器 · 自动化脚本系统 v0.1

安卓游戏多开自动化脚本，支持模拟器 ADB 截图、图像识别、自动购买等功能。

## 📁 项目目录结构

```
模拟器/0.1/
├── gui.py                  # GUI 入口文件（启动: python gui.py）
├── gui/                    # GUI 模块包
│   ├── __init__.py         # 包入口，导出 MainWindow 和 main()
│   ├── constants.py        # 配色常量、字体工具函数
│   ├── workers.py          # 截图后台线程（ADB + scrcpy 实时同步）
│   ├── widgets.py          # ScreenshotWidget 截图预览控件
│   ├── main_window.py      # MainWindow 主窗口（布局、信号、业务逻辑）
│   └── tabs/               # 功能页子包
│       ├── __init__.py     # Tab 统一导出
│       ├── library_tab.py  # 🖼 图库：模板图片管理（缩略图网格、删除）
│       ├── script_tab.py   # 📜 脚本：参数调整 + 控制按钮 + 快捷操作
│       └── workflow_tab.py # 🔗 流程：自由组合脚本（预留）
│
├── config.py               # 全局配置（路径、分辨率、阈值、ADB 扫描）
├── adb_utils.py            # ADB 底层操作（截图、点击、设备管理）
├── image_engine.py         # 图像识别引擎（模板匹配）
├── shop_bot.py             # 神秘商店自动购买逻辑
├── bot_worker.py           # 工作线程封装
├── recovery.py             # 异常恢复
├── main.py                 # 命令行入口
├── targets/                # 模板图片目录
├── popups/                 # 弹窗模板
└── requirements.txt        # 依赖列表
```

## 🚀 快速启动

```bash
# 安装依赖
pip install -r requirements.txt

# 启动 GUI
python gui.py
```

## 🔑 核心功能

| 功能 | 说明 |
|------|------|
| **ADB 管理** | 自动扫描雷电/MUMU 模拟器 ADB，支持切换和重启 |
| **截图预览** | 实时同步模拟器画面（scrcpy 30fps+），支持坐标拾取 |
| **区域截图** | 鼠标拖拽选区 → 裁切保存为模板图片 |
| **图库管理** | 缩略图网格展示模板，支持刷新和删除 |
| **自动购买** | 神秘商店物品图像识别 + 自动点击购买 |
| **参数热更** | 运行中实时调整匹配阈值、延迟等参数 |

## 📦 依赖

- Python 3.10+
- PyQt6
- OpenCV (opencv-python)
- numpy
- py-scrcpy-client (可选，用于实时同步)
