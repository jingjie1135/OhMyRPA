# PyQt6 开发规范速查

> 镜界工作室 · 快速参考 v2.0

本文档总结了 Windows 桌面应用开发过程中的最佳实践，用于指导 Python + PyQt6 项目开发。

---

## 一、项目结构规范

推荐目录结构：`main.py`（入口）、`gui.py`（界面）、`core.py`（逻辑）、`app_icon.ico/png`（图标）、`build.bat`（打包脚本）、`requirements.txt`（依赖）

---

## 二、字体渲染优化

- QApplication 创建后立即设置全局字体为 `PreferNoHinting`
- 中文优先 `Microsoft YaHei`，英文优先 `Segoe UI`
- 使用 `QFont` 设置加粗，避免 CSS `font-weight`
- 关键控件单独设置字体 + `PreferNoHinting`

---

## 三、高 DPI 图片清晰度

- 使用 `devicePixelRatio()` 获取设备像素比
- 缩放到 `目标宽度 × DPR`，再设置 pixmap 的 DPR
- **禁止**：直接 `scaled()` 不设置 DPR
- **禁止**：设置 `QT_ENABLE_HIGHDPI_SCALING` 环境变量

---

## 四、窗口闪动问题修复

1. 通过 `windowFlags` 移除帮助按钮
2. 使用 `resize()` + `setMinimumSize()` 替代 `setFixedSize()`
3. 创建 QDialog 必须传入 parent
4. 禁止手动重写 `mouseMoveEvent` 接管拖拽
5. 动态内容按钮（如倒计时）使用 `setFixedSize()` 固定尺寸

---

## 五、优雅的状态切换

- 使用 `QStackedWidget` 管理多个视图状态（如拖拽区/列表区）
- 通过 `setCurrentIndex()` 切换页面
- 优于手动 `hide()`/`show()` 控件

---

## 六、资源保护

- 在 `closeEvent` 中检查线程是否运行
- 使用 `requestInterruption()` 请求中断 + `wait()` 等待结束
- 线程 `run()` 方法中检查 `isInterruptionRequested()`

---

## 七、UI 组件常见问题

| 组件 | 问题 | 解决方案 |
|------|------|----------|
| QListWidget | 选中框/焦点框 | QSS 设置 `outline: none; border: none` |
| QPushButton | 高 DPI 文字截断 | 固定尺寸 + 明确设置字体 |
| QComboBox | 下拉箭头不显示 | 使用 Qt 子控件选择器 `::drop-down` 和 `::down-arrow` |
| QProgressBar | 进度文字显示 | 使用 `setFormat()` 在进度条内显示文字 |

---

## 八、消息框样式规范

- 默认 `QMessageBox` 文字颜色太浅
- 必须使用自定义样式：设置背景色、文字颜色、按钮样式

---

## 九、多线程处理

- 继承 `QThread`，使用 `pyqtSignal` 发射进度和完成信号
- 主线程通过 `connect` 连接信号槽更新 UI
- 任务期间禁用相关按钮，完成后恢复

---

## 十、定时器使用

- **延时执行**：`QTimer.singleShot(毫秒, 函数)`
- **循环执行**：创建 `QTimer` 对象，连接 `timeout` 信号，调用 `start(间隔)`
- 将 dialog 作为 timer 的父对象，对话框关闭时自动清理

---

## 十一、子进程调用规范

- Windows 下必须设置 `creationflags=subprocess.CREATE_NO_WINDOW`
- 避免弹出黑色控制台窗口

---

## 十二、样式设计规范

**配色方案**：
| 用途 | 颜色 |
|------|------|
| 主色调 | `#409eff` |
| 成功色 | `#67c23a` |
| 警告色 | `#e6a23c` |
| 危险色 | `#f56c6c` |
| 背景色 | `#f5f7fa` |
| 边框色 | `#dcdfe6` |
| 正文色 | `#2c3e50` |
| 禁用色 | `#909399` |

- 使用 `qlineargradient` 实现渐变按钮
- 为按钮添加 `:disabled` 和 `:hover` 伪类样式
- 标题栏可使用水平渐变效果

---

## 十三、文件路径处理

- **长路径**：Windows 下添加 `\\?\` 前缀突破 260 字符限制
- **资源路径**：使用 `os.path.dirname(__file__)` 获取脚本目录

---

## 十四、打包部署

### PyInstaller
- 使用 `--onefile --windowed` 生成单文件 GUI 程序
- 使用 `--add-data` 包含资源文件
- 运行时通过 `sys._MEIPASS` 获取解压路径

### Nuitka（推荐）
- 编译为 C++ 后打包，启动更快、体积更小
- 使用 `--enable-plugin=pyqt6` 启用 PyQt6 支持
- 使用 `--include-data-file` 包含资源文件
- 使用 `--windows-console-mode=disable` 隐藏控制台
- 首次编译自动下载 MinGW64 编译器

### PE Overlay 定制 EXE
- **原理**：在 EXE 末尾追加数据（魔术标记 + JSON 配置），不影响程序执行
- **优势**：毫秒级生成、单文件分发、启动自动加载配置
- **实现**：`OverlayManager` 类，使用 `|||VIBE_CFG|||` 作为魔术标记
- **读取配置**：`OverlayManager.read_embedded_config()`
- **生成定制 EXE**：`OverlayManager.create_custom_exe(source, output, config)`
- 代码位置：`core.py` → `OverlayManager` 类

---

## 十五、代码规范

**命名规范**：
| 类型 | 规范 | 示例 |
|------|------|------|
| 类名 | 大驼峰 | `MainWindow` |
| 方法名 | 下划线 | `show_donate` |
| 信号名 | 下划线 | `progress_update` |
| 控件实例 | 下划线+类型 | `start_btn` |
| 样式 objectName | 驼峰 | `primaryBtn` |

**注释规范**：函数添加中文文档字符串，复杂逻辑添加行内注释

---

## 十六、代码审查清单

- [ ] 字体用 `QFont` 设置，非 CSS
- [ ] 图片用 DPR 缩放
- [ ] Dialog 移除帮助按钮
- [ ] Dialog 用 `resize()` 非 `setFixedSize()`
- [ ] 动态按钮用 `setFixedSize()`
- [ ] 消息框自定义样式
- [ ] 子进程用 `CREATE_NO_WINDOW`
- [ ] 无 `QT_ENABLE_HIGHDPI_SCALING` 环境变量
- [ ] 使用 `QStackedWidget` 切换视图
- [ ] `closeEvent` 中停止线程

---

## 附录：常见问题速查

| 问题 | 解决 |
|------|------|
| 文字锯齿 | `PreferNoHinting` + 明确字体 |
| 图片模糊 | `devicePixelRatio()` 缩放 |
| 按钮截断 | `setFixedSize()` + 明确字体 |
| 列表选中框 | `outline: none` |
| Dialog 抖动 | 移除帮助按钮 + `resize()` |
| 下拉箭头 | Qt 子控件选择器 |
| 路径过长 | `\\?\` 前缀 |
| 子进程弹窗 | `CREATE_NO_WINDOW` |
| 视图切换 | `QStackedWidget` |
| 线程未停止 | `closeEvent` 中处理 |
| 定制 EXE 生成 | `OverlayManager` PE Overlay |

---

*镜界工作室 · 2026-01-12*
