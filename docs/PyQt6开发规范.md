# Python + PyQt6 桌面应用开发规范

> 镜界工作室 · 企业级桌面软件开发标准 v2.0
> 基于实际项目开发经验总结

本文档总结了我们在 Windows 桌面应用开发过程中的最佳实践、踩坑经验和技术方案，用于指导后续 Python + PyQt6 项目开发。

---

## 一、项目结构规范

```
ProjectName/
├── main.py              # 程序入口
├── gui.py               # GUI 界面层（可选，小项目可合并）
├── core.py              # 核心业务逻辑（可选）
├── app_icon.ico         # 应用图标
├── app_icon.png         # 应用图标（PNG 格式备用）
├── *.png                # 其他资源图片
├── build.bat            # 打包脚本
└── requirements.txt     # 依赖列表
```

---

## 二、字体渲染优化（消除锯齿）

### 问题现象
在某些 Windows 系统或非 100% 缩放比例下，Qt 渲染的字体边缘出现发虚、锯齿或笔画不匀。

### 强制规则
```python
# main.py - 必须在 QApplication 创建后立即设置
from PyQt6.QtGui import QFont

app = QApplication(sys.argv)

# 禁用字体微调，使用灰度抗锯齿消除锯齿
font = app.font()
font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
app.setFont(font)
```

### 字体选择
- **中文界面**：优先使用 `Microsoft YaHei`（微软雅黑）
- **英文界面**：优先使用 `Segoe UI`
- **等宽字体**：推荐 `Cascadia Code` 或 `Consolas`

### 正确示例
```python
# ✅ 正确：使用 QFont 设置加粗
label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))

# ❌ 错误：使用 CSS font-weight（可能导致锯齿）
label.setStyleSheet("font-weight: bold;")
```

### 控件单独设置字体（确保高 DPI 清晰）
```python
btn_font = QFont("Microsoft YaHei", 9)
btn_font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
btn.setFont(btn_font)
```

---

## 三、高 DPI 图片清晰度优化

### 问题现象
在 4K 屏幕或 150%+ 缩放倍率下，普通的 `QPixmap` 渲染会导致图片出现明显的马赛克或模糊。

### 强制规则
```python
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt

# 获取设备像素比（DPR）
dpr = widget.devicePixelRatio()
logical_width = 360  # 逻辑像素宽度
target_width_px = int(logical_width * dpr)  # 物理像素宽度

# 缩放到物理像素尺寸
pixmap = QPixmap("image.png")
scaled_pixmap = pixmap.scaledToWidth(target_width_px, Qt.TransformationMode.SmoothTransformation)
scaled_pixmap.setDevicePixelRatio(dpr)  # 关键：设置 DPR

label.setPixmap(scaled_pixmap)
```

### 禁止事项
```python
# ❌ 禁止：直接使用 scaled() 而不设置 DPR
pixmap.scaled(360, 360)

# ❌ 禁止：设置 QT_ENABLE_HIGHDPI_SCALING 环境变量（与 Windows 缩放冲突）
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
```

---

## 四、窗口闪动/抖动问题修复

### 问题现象
在 Windows 高 DPI 环境或多显示器环境下，拖拽 QDialog 时，窗口会莫名其妙地向上或向下瞬间"跳动"。

### 强制规则

#### 1. 移除帮助按钮标志位
```python
dialog = QDialog(parent)
dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
```

#### 2. 使用 resize + setMinimumSize 替代 setFixedSize
```python
# ✅ 正确：允许系统进行微小的布局自适应修正
dialog.resize(420, 580)
dialog.setMinimumSize(420, 580)

# ❌ 错误：强制固定尺寸可能导致抖动
dialog.setFixedSize(420, 580)
```

#### 3. 维持父子窗口关系
```python
# ✅ 正确：传入父窗口
dialog = QDialog(self)

# ❌ 错误：无父窗口的独立对话框
dialog = QDialog()
```

#### 4. 禁止手动接管拖拽
```python
# ❌ 禁止：重写 mouseMoveEvent 接管标题栏拖拽（会与系统冲突）
def mouseMoveEvent(self, event):
    self.move(...)  # 极易导致死循环抖动
```

#### 5. 动态内容按钮使用固定尺寸
```python
# 倒计时按钮等动态内容，设置固定尺寸防止布局抖动
confirm_btn = QPushButton("确认 (3)")
confirm_btn.setFixedSize(160, 44)  # 按钮固定尺寸
```

---

## 五、优雅的状态切换

### 问题现象
界面需要在"拖拽区"和"列表区"等不同状态之间切换时，手动 `hide()`/`show()` 控件代码混乱且容易出错。

### 强制规则
使用 `QStackedWidget` 管理多个视图状态：

```python
# 创建堆叠容器
self.content_stack = QStackedWidget()

# 添加不同状态的页面
self.content_stack.addWidget(self.drop_frame)      # Page 0: 拖拽区
self.content_stack.addWidget(self.list_container)  # Page 1: 列表区

# 切换状态
self.content_stack.setCurrentIndex(0)  # 显示拖拽区
self.content_stack.setCurrentIndex(1)  # 显示列表区
```

### 优点
- 代码结构清晰，易于维护
- 避免 `hide()`/`show()` 导致的布局问题
- 支持任意数量的状态页面

---

## 六、资源保护

### 问题现象
用户关闭窗口时，后台线程可能仍在运行，导致资源泄漏或程序假死。

### 强制规则
在 `closeEvent` 中强制停止线程：

```python
def closeEvent(self, event):
    # 检查线程是否存在且正在运行
    if self.thread and self.thread.isRunning():
        self.thread.requestInterruption()  # 请求中断
        self.thread.wait()                 # 等待线程结束
    event.accept()
```

### 线程端配合
线程的 `run()` 方法中应检查中断请求：

```python
def run(self):
    for item in items:
        if self.isInterruptionRequested():
            break
        # 处理逻辑...
```

---

## 七、UI 组件常见问题与解决方案

### 7.1 QListWidget 选中框样式去除

**问题**：QListWidget 默认有蓝色选中框和焦点虚线框，影响美观。

**解决方案**：
```python
self.setStyleSheet("""
    QListWidget {
        border: 1px solid #dcdfe6;
        border-radius: 8px;
        background-color: white;
        outline: none;
    }
    QListWidget::item {
        padding: 5px;
        border-bottom: 1px solid #f0f2f5;
        border-radius: 6px;
    }
    QListWidget::item:selected {
        background-color: #ecf5ff;
        border: none;
        outline: none;
    }
    QListWidget::item:focus {
        outline: none;
        border: none;
    }
""")
```

### 7.2 按钮文字显示不全

**问题**：在高 DPI 下按钮文字被截断。

**解决方案**：
```python
btn = QPushButton("清空列表")
btn.setObjectName("deleteBtn")

# 设置字体确保高 DPI 显示正常
btn_font = QFont("Microsoft YaHei", 9)
btn_font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
btn.setFont(btn_font)

# 使用固定尺寸
btn.setFixedSize(80, 26)
btn.setCursor(Qt.CursorShape.PointingHandCursor)
```

### 7.3 QComboBox 下拉箭头样式

**CSS 伪元素不可用**：Qt 样式表不支持 `::after` 等 CSS 伪元素。

**正确方案**：
```python
"""
QComboBox {
    border: 1px solid #dcdfe6;
    border-radius: 6px;
    padding: 5px 10px;
    background: white;
    min-width: 120px;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 20px;
    border-left: 1px solid #dcdfe6;
    background: #f5f7fa;
}
QComboBox::down-arrow {
    width: 0;
    height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #606266;
}
"""
```

### 7.4 进度条内嵌文字

```python
self.pbar = QProgressBar()
self.pbar.setValue(0)
self.pbar.setFormat("当前进度: %p%")

# 样式设置
"""
QProgressBar {
    border: none;
    background-color: #e4e7ed;
    height: 22px;
    border-radius: 11px;
    text-align: center;
    font-size: 12px;
    font-weight: bold;
    color: #606266;
}
QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
        stop:0 #409eff, stop:1 #66b1ff);
    border-radius: 11px;
}
"""
```

---

## 八、消息框样式规范

### 问题现象
默认的 `QMessageBox.information()` 在某些主题下文字颜色太浅，不清晰。

### 强制规则
所有消息框必须使用自定义样式：

```python
msg_box = QMessageBox(self)
msg_box.setWindowTitle("提示")
msg_box.setIcon(QMessageBox.Icon.Information)
msg_box.setText("消息内容")
msg_box.setStyleSheet("""
    QMessageBox {
        background-color: #ffffff;
    }
    QMessageBox QLabel {
        color: #333333;
        font-size: 13px;
    }
    QMessageBox QPushButton {
        background-color: #0078d4;
        color: white;
        padding: 6px 20px;
        border: none;
        border-radius: 4px;
    }
    QMessageBox QPushButton:hover {
        background-color: #1084d8;
    }
""")
msg_box.exec()
```

---

## 九、多线程处理

### 9.1 QThread 基本模式

```python
class WorkerThread(QThread):
    progress_update = pyqtSignal(int)
    log_update = pyqtSignal(str)
    finished_signal = pyqtSignal(bool)
    
    def __init__(self, params):
        super().__init__()
        self.params = params
    
    def run(self):
        try:
            for i, item in enumerate(self.items):
                # 处理逻辑...
                progress = int((i + 1) / total * 100)
                self.progress_update.emit(progress)
                self.log_update.emit(f"处理中: {item}")
            
            self.finished_signal.emit(True)
        except Exception as e:
            self.log_update.emit(f"错误: {str(e)}")
            self.finished_signal.emit(False)
```

### 9.2 线程信号连接

```python
def start_task(self):
    self.start_btn.setEnabled(False)
    
    self.thread = WorkerThread(self.params)
    self.thread.progress_update.connect(self.update_progress)
    self.thread.log_update.connect(self.log_output.append)
    self.thread.finished_signal.connect(self.task_finished)
    self.thread.start()

def task_finished(self, success):
    self.start_btn.setEnabled(True)
    if success:
        QTimer.singleShot(500, self.show_result_dialog)
```

---

## 十、定时器使用

### 10.1 一次性延时执行

```python
from PyQt6.QtCore import QTimer

# 500ms 后执行
QTimer.singleShot(500, self.some_function)
```

### 10.2 倒计时实现

```python
countdown = [3]  # 使用列表以便在内部函数中修改

def update_countdown():
    countdown[0] -= 1
    if countdown[0] > 0:
        btn.setText(f"确认 ({countdown[0]})")
    else:
        btn.setText("确认")
        btn.setEnabled(True)
        timer.stop()

timer = QTimer(dialog)  # 父对象为对话框，对话框关闭时自动清理
timer.timeout.connect(update_countdown)
timer.start(1000)
```

---

## 十一、子进程调用规范

### 问题现象
使用 `subprocess.run()` 时，在 Windows 上会弹出黑色控制台窗口。

### 强制规则
```python
import subprocess

# ✅ 正确：隐藏控制台窗口
result = subprocess.run(
    ["pip", "install", "package"],
    capture_output=True,
    text=True,
    creationflags=subprocess.CREATE_NO_WINDOW  # 关键
)

# ❌ 错误：会弹出黑色窗口
result = subprocess.run(["pip", "install", "package"])
```

---

## 十二、样式设计规范

### 12.1 推荐配色方案

| 用途 | 颜色值 | 示例 |
|------|--------|------|
| 主色调 | `#409eff` | 按钮、链接 |
| 成功色 | `#67c23a` | 成功提示、确认按钮 |
| 警告色 | `#e6a23c` | 警告提示 |
| 危险色 | `#f56c6c` | 删除按钮、错误提示 |
| 背景色 | `#f5f7fa` | 主窗口背景 |
| 边框色 | `#dcdfe6` | 输入框、卡片边框 |
| 主文字 | `#2c3e50` | 标题、正文 |
| 次要文字 | `#606266` | 说明文字 |
| 辅助文字 | `#909399` | 提示、禁用文字 |

### 12.2 渐变按钮模板

```python
"""
QPushButton#primaryBtn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
        stop:0 #67c23a, stop:1 #5daf34);
    color: white;
    border: none;
    border-radius: 6px;
    padding: 10px 20px;
    font-size: 14px;
    font-weight: bold;
}
QPushButton#primaryBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
        stop:0 #85ce61, stop:1 #67c23a);
}
QPushButton#primaryBtn:disabled {
    background: #c0c4cc;
    color: #909399;
}
"""
```

### 12.3 标题栏渐变效果

```python
"""
QFrame#headerFrame {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
        stop:0 #1a2a3a, stop:0.5 #2c3e50, stop:1 #1a2a3a);
    border-bottom: 2px solid #409eff;
}
"""
```

---

## 十三、文件路径处理

### 13.1 Windows 长路径支持

```python
def get_long_path(self, path):
    """Windows 长路径支持前缀"""
    if os.name == 'nt' and not path.startswith('\\\\?\\'):
        return f'\\\\?\\{os.path.abspath(path)}'
    return path
```

### 13.2 资源文件路径获取

```python
import os

# 获取与脚本同目录的资源文件
resource_path = os.path.join(os.path.dirname(__file__), "image.png")
```

---

## 十四、打包部署

### 14.1 PyInstaller 打包

```bash
pyinstaller --onefile --windowed --icon=app.ico --name="应用名称" main.py
```

资源文件包含：
```bash
pyinstaller --onefile --windowed \
    --add-data "image.png;." \
    --add-data "icon.ico;." \
    main.py
```

运行时获取资源路径：
```python
def resource_path(relative_path):
    """获取资源文件路径（兼容打包后运行）"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(__file__), relative_path)
```

### 14.2 Nuitka 打包（推荐）

Nuitka 将 Python 代码编译为 C++ 再生成可执行文件：
- 更快的启动速度
- 更小的文件体积
- 更好的代码保护

#### 打包脚本模板 (build.bat)

```batch
@echo off
REM Nuitka Build Script
REM Use Nuitka to compile Python to C++ and generate executable

echo ========================================
echo  Nuitka Build - [应用名称]
echo ========================================

REM Check Nuitka
python -m nuitka --version >nul 2>&1
if errorlevel 1 (
    echo Installing Nuitka...
    pip install nuitka
)

echo.
echo Starting compilation...
echo.

python -m nuitka ^
    --standalone ^
    --onefile ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=app_icon.ico ^
    --enable-plugin=pyqt6 ^
    --include-data-file=*.png=./ ^
    --include-data-file=app_icon.ico=./ ^
    --output-filename=AppName.exe ^
    --output-dir=dist_nuitka ^
    --remove-output ^
    --assume-yes-for-downloads ^
    main.py

echo.
if exist "dist_nuitka\AppName.exe" (
    echo ========================================
    echo  Build Success!
    echo  Output: dist_nuitka\AppName.exe
    echo ========================================
) else (
    echo Build failed, please check errors above.
)

pause
```

#### 关键参数说明

| 参数 | 说明 |
|------|------|
| `--standalone` | 生成独立可运行的程序 |
| `--onefile` | 打包为单个 EXE 文件 |
| `--windows-console-mode=disable` | 隐藏控制台窗口 |
| `--enable-plugin=pyqt6` | 启用 PyQt6 插件 |
| `--include-data-file=*.png=./` | 包含所有 PNG 资源文件 |
| `--remove-output` | 编译完成后删除临时文件 |
| `--assume-yes-for-downloads` | 自动下载依赖（如 C++ 编译器） |

#### 首次使用注意

1. Nuitka 会自动下载 MinGW64 C++ 编译器（约 200MB）
2. 首次编译耗时较长（5-15 分钟），后续增量编译更快
3. 安装命令：`pip install nuitka`

### 14.3 PE Overlay 定制 EXE 生成

#### 问题场景
如何让用户快速生成包含自定义软件配置的 EXE，而无需重新编译？

#### 解决方案
利用 Windows PE 格式的特性：**在 EXE 末尾追加数据，不影响程序执行**。

```
┌─────────────────────────────┐
│      原始 EXE 二进制         │
├─────────────────────────────┤
│   |||VIBE_CFG|||            │  魔术标记
├─────────────────────────────┤
│   {"apps": [...]}           │  JSON 配置
└─────────────────────────────┘
```

#### 核心实现（OverlayManager 类）

```python
import os
import sys
import json

class OverlayManager:
    """PE Overlay 管理器 - 在 EXE 末尾追加/读取配置数据"""
    
    # 魔术标记，用于定位配置数据起始位置
    MAGIC_MARKER = b"|||VIBE_CFG|||"
    
    @classmethod
    def read_embedded_config(cls) -> dict | None:
        """
        从当前 EXE 的 Overlay 区域读取嵌入的配置
        
        Returns:
            dict: 解析后的配置字典，如果不存在则返回 None
        """
        try:
            exe_path = sys.executable
            with open(exe_path, 'rb') as f:
                content = f.read()
            
            # 查找魔术标记位置
            marker_pos = content.rfind(cls.MAGIC_MARKER)
            if marker_pos == -1:
                return None
            
            # 提取并解析 JSON 配置
            config_start = marker_pos + len(cls.MAGIC_MARKER)
            config_bytes = content[config_start:]
            return json.loads(config_bytes.decode('utf-8'))
            
        except Exception:
            return None
    
    @classmethod
    def create_custom_exe(cls, source_exe: str, output_exe: str, config: dict) -> bool:
        """
        创建包含自定义配置的 EXE（在原 EXE 末尾追加配置）
        
        Args:
            source_exe: 源 EXE 文件路径
            output_exe: 输出 EXE 文件路径
            config: 要嵌入的配置字典
            
        Returns:
            bool: 是否成功创建
        """
        try:
            # 读取源 EXE
            with open(source_exe, 'rb') as f:
                exe_content = f.read()
            
            # 如果源文件已有配置，先移除（获取干净的 EXE）
            marker_pos = exe_content.rfind(cls.MAGIC_MARKER)
            if marker_pos != -1:
                exe_content = exe_content[:marker_pos]
            
            # 序列化配置为 JSON
            config_bytes = json.dumps(config, ensure_ascii=False, indent=2).encode('utf-8')
            
            # 写入新 EXE = 原始 EXE + 魔术标记 + 配置
            with open(output_exe, 'wb') as f:
                f.write(exe_content)
                f.write(cls.MAGIC_MARKER)
                f.write(config_bytes)
            
            return True
            
        except Exception:
            return False
```

#### 使用示例

```python
# 程序启动时自动加载嵌入配置
if __name__ == "__main__":
    embedded_config = OverlayManager.read_embedded_config()
    if embedded_config:
        print(f"已加载嵌入配置: {embedded_config}")
        # 使用嵌入的配置初始化程序...
    else:
        print("未检测到嵌入配置，使用默认设置")

# 生成定制版 EXE
config = {
    "apps": ["VSCode", "Git", "Python"],
    "version": "1.0.0"
}
OverlayManager.create_custom_exe(
    source_exe="MyApp.exe",
    output_exe="MyApp_Custom.exe",
    config=config
)
```

#### 技术优势

| 特性 | 说明 |
|------|------|
| ⚡ 毫秒级生成 | 无需编译，直接文件追加 |
| 📦 单文件分发 | 配置内嵌于 EXE，无外部依赖 |
| 🔄 自动识别 | 程序启动时自动检测并加载配置 |
| 📝 可迭代更新 | 可多次追加覆盖配置 |

#### 注意事项

1. 魔术标记应足够独特，避免与 EXE 内容冲突
2. 建议配置数据使用 UTF-8 编码
3. 此方法不影响程序签名验证（Windows 不检查 Overlay 区域）
4. 代码位置：`core.py` → `OverlayManager` 类

---

## 十五、代码规范

### 15.1 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| 类名 | 大驼峰 | `MainWindow`, `ExtractThread` |
| 方法名 | 下划线分隔 | `show_donate`, `update_progress` |
| 信号名 | 下划线分隔 | `progress_update`, `finished_signal` |
| 控件实例 | 下划线分隔+类型后缀 | `start_btn`, `log_output`, `type_combo` |
| 样式 objectName | 驼峰式 | `primaryBtn`, `headerFrame`, `tipLabel` |

### 15.2 注释规范

- 所有函数添加中文文档字符串
- 复杂逻辑添加行内注释
- 样式定义前添加用途说明

---

## 十六、代码审查清单

每次提交代码前，必须检查以下事项：

- [ ] 字体使用 `QFont` 设置，非 CSS
- [ ] 图片加载使用 DPR 动态缩放
- [ ] QDialog 移除了帮助按钮标志位
- [ ] QDialog 使用 `resize()` + `setMinimumSize()` 而非 `setFixedSize()`
- [ ] 动态内容按钮使用 `setFixedSize()`
- [ ] 消息框使用自定义样式
- [ ] 子进程使用 `CREATE_NO_WINDOW`
- [ ] 无 `QT_ENABLE_HIGHDPI_SCALING` 环境变量

---

## 附录：常见问题速查表

| 问题 | 解决方案 |
|------|----------|
| 文字锯齿 | `PreferNoHinting` + 明确设置字体 |
| 图片模糊 | 使用 `devicePixelRatio()` 缩放 |
| 按钮文字截断 | 使用 `setFixedSize()` + 明确字体 |
| 列表选中框 | QSS 设置 `outline: none; border: none;` |
| 对话框闪烁 | 移除帮助按钮 + `resize()` + 动态按钮固定尺寸 |
| 下拉箭头不显示 | 使用 Qt 子控件选择器（非 CSS 伪元素） |
| 路径过长报错 | 添加 `\\?\` 前缀 |
| 子进程弹窗 | 使用 `CREATE_NO_WINDOW` |
| 定制 EXE 配置嵌入 | 使用 `OverlayManager` PE Overlay 技术 |

---

**文档编制**：镜界工作室  
**版本**：v2.0  
**最后更新**：2026-01-12
