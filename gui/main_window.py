"""
主窗口：集成截图预览、参数面板、控制按钮、日志区。
"""

import sys
import subprocess
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSlot, pyqtSignal
from PyQt6.QtGui import QFont, QImage
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QTabWidget, QTextEdit,
    QGroupBox, QSplitter,
)

import config
from config import scan_adb_paths, set_adb_path, set_device_resolution
from adb_utils import get_connected_devices, get_resolution
from bot_worker import BotWorker

from gui.constants import (
    COLOR_PRIMARY, COLOR_SUCCESS, COLOR_WARNING, COLOR_DANGER,
    COLOR_BG, COLOR_BORDER, COLOR_TEXT, COLOR_DISABLED,
    create_font,
)
from gui.workers import ScreencapWorker
from gui.widgets import ScreenshotWidget
from gui.tabs import ImageLibraryTab, ScriptTab, LoopScriptTab, WorkflowTab


class AdbTask(QThread):
    """
    通用 ADB 后台任务线程：避免阻塞 UI。
    将任意 callable 放到后台执行，完成后通过信号回调。
    """
    finished = pyqtSignal(object)  # 携带返回值
    error = pyqtSignal(str)        # 携带错误信息

    def __init__(self, fn, *args, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._args = args

    def run(self):
        try:
            result = self._fn(*self._args)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    """
    主窗口：集成截图预览、参数面板、控制按钮、日志区。
    遵循 PyQt6 速查手册全部规范。
    """

    def __init__(self):
        super().__init__()
        self._workers = []              # 并发执行的多个工作线程
        self._workflow_runner = None     # 流程批次编排线程
        self._runtime_config = None     # 运行时参数引用
        self._last_picked_coord = None  # 最近一次拾取的坐标
        self._screencap_worker = None   # 截图后台线程
        self._buy_count = 0

        # 群控管理
        self._group_adapters = {}

        self._init_ui()
        self._connect_signals()
        self._apply_styles()

        # 参数热更新定时器：每 500ms 同步 UI 参数到工作线程（手册 §十）
        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self._sync_params)

    def _init_ui(self):
        """构建主界面布局。"""
        self.setWindowTitle("模拟器 · 自动化脚本 v0.1")
        self.resize(1000, 900)
        self.setMinimumSize(1000, 800)

        central = QWidget()
        self.setCentralWidget(central)
        
        # 外层布局：无边距，使顶栏贴边
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 引入并添加顶栏
        from gui.top_bar import TopBar
        self.header = TopBar("模拟器 · 自动化脚本")
        main_layout.addWidget(self.header)

        # 内部主内容布局：还原原有的边距和间距
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(8)
        content_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.addWidget(content_widget, 1)

        # ===== 控制栏：ADB + 设备选择栏 =====
        top_bar = QHBoxLayout()

        # ADB 选择器
        adb_label = QLabel("ADB:")
        adb_label.setFont(create_font(9, bold=True))
        top_bar.addWidget(adb_label)

        self.adb_combo = QComboBox()
        self.adb_combo.setFont(create_font())
        self.adb_combo.setMinimumWidth(100)
        self.adb_combo.setToolTip("选择模拟器的 ADB 路径")

        # 填充扫描结果（阻塞信号，避免每加一项都触发 _on_adb_changed）
        self.adb_combo.blockSignals(True)
        scanned = scan_adb_paths()
        if scanned:
            for name, path in scanned.items():
                self.adb_combo.addItem(f"{name}", path)
        else:
            self.adb_combo.addItem("未找到 ADB", "adb")
        self.adb_combo.blockSignals(False)

        top_bar.addWidget(self.adb_combo)

        # 设备选择器
        device_label = QLabel("设备:")
        device_label.setFont(create_font(9, bold=True))
        top_bar.addWidget(device_label)

        self.device_combo = QComboBox()
        self.device_combo.setFont(create_font())
        self.device_combo.setMinimumWidth(140)
        top_bar.addWidget(self.device_combo)

        self.refresh_device_btn = QPushButton("🔄 刷新设备")
        self.refresh_device_btn.setFont(create_font())
        self.refresh_device_btn.setFixedSize(100, 28)
        top_bar.addWidget(self.refresh_device_btn)

        self.restart_adb_btn = QPushButton("重启ADB")
        self.restart_adb_btn.setFont(create_font())
        self.restart_adb_btn.setFixedSize(90, 28)
        self.restart_adb_btn.setToolTip("使用当前选中的 ADB 重启服务器")
        top_bar.addWidget(self.restart_adb_btn)

        self.group_control_btn = QPushButton("👥 群控")
        self.group_control_btn.setFont(create_font(9, bold=True))
        self.group_control_btn.setFixedSize(90, 28)
        self.group_control_btn.setStyleSheet(f"color: {COLOR_PRIMARY};")
        self.group_control_btn.setToolTip("开启多设备群控模式 (纯控制通道)")
        self.group_control_btn.setCheckable(True)
        top_bar.addWidget(self.group_control_btn)

        top_bar.addStretch()

        # 状态栏
        self.coord_label = QLabel("坐标: --")
        self.coord_label.setFont(create_font())
        self.coord_label.setMinimumWidth(120)
        top_bar.addWidget(self.coord_label)

        self.status_label = QLabel("状态: 就绪")
        self.status_label.setFont(create_font(9, bold=True))
        self.status_label.setMinimumWidth(100)
        top_bar.addWidget(self.status_label)

        self.scrcpy_count_label = QLabel("连接数: 0")
        self.scrcpy_count_label.setFont(create_font(9, bold=True))
        self.scrcpy_count_label.setStyleSheet(f"color: {COLOR_SUCCESS};")
        top_bar.addWidget(self.scrcpy_count_label)

        self.fps_label = QLabel("")
        self.fps_label.setFont(create_font(9, bold=True))
        self.fps_label.setStyleSheet(f"color: {COLOR_PRIMARY};")
        self.fps_label.setMinimumWidth(80)
        top_bar.addWidget(self.fps_label)

        self.resolution_label = QLabel("")
        self.resolution_label.setFont(create_font(8))
        self.resolution_label.setStyleSheet(f"color: {COLOR_DISABLED};")
        top_bar.addWidget(self.resolution_label)

        content_layout.addLayout(top_bar)

        # ===== 中部：截图预览 + 功能面板 =====
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧：截图预览 + 侧边栏（录制时感知鼠标进出）
        self.preview_container = QWidget()
        self.preview_container.setMouseTracking(True)
        preview_layout = QHBoxLayout(self.preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(4)

        self.screenshot_widget = ScreenshotWidget()
        preview_layout.addWidget(self.screenshot_widget, 1)

        # 侧边栏：截图 + 实时同步按钮（竖排）
        sidebar = QVBoxLayout()
        sidebar.setSpacing(6)

        self.screenshot_btn = QPushButton("📸\n截图")
        self.screenshot_btn.setFont(create_font(9))
        self.screenshot_btn.setFixedSize(50, 50)
        self.screenshot_btn.setToolTip("手动截图")
        sidebar.addWidget(self.screenshot_btn)

        self.live_sync_btn = QPushButton("▶\n同步")
        self.live_sync_btn.setFont(create_font(9))
        self.live_sync_btn.setFixedSize(50, 50)
        self.live_sync_btn.setToolTip("持续同步模拟器画面到预览区")
        self.live_sync_btn.setCheckable(True)
        sidebar.addWidget(self.live_sync_btn)

        self.display_power_btn = QPushButton("🌙\n熄屏")
        self.display_power_btn.setFont(create_font(9))
        self.display_power_btn.setFixedSize(50, 50)
        self.display_power_btn.setToolTip("【Scrcpy专属】关闭物理屏幕背光但保持画面传输")
        self.display_power_btn.setCheckable(True)
        sidebar.addWidget(self.display_power_btn)

        # 录制期间的控制按钮（仅录制时可见）
        self.sidebar_pause_btn = QPushButton("⏸\n暂停")
        self.sidebar_pause_btn.setFont(create_font(9))
        self.sidebar_pause_btn.setFixedSize(50, 50)
        self.sidebar_pause_btn.setToolTip("暂停/继续录制")
        self.sidebar_pause_btn.setObjectName("warningBtn")
        self.sidebar_pause_btn.setVisible(False)
        sidebar.addWidget(self.sidebar_pause_btn)

        self.sidebar_stop_btn = QPushButton("⏹\n停止")
        self.sidebar_stop_btn.setFont(create_font(9))
        self.sidebar_stop_btn.setFixedSize(50, 50)
        self.sidebar_stop_btn.setToolTip("停止录制")
        self.sidebar_stop_btn.setObjectName("dangerBtn")
        self.sidebar_stop_btn.setVisible(False)
        sidebar.addWidget(self.sidebar_stop_btn)

        sidebar.addStretch()

        # 底部系统级控制按钮
        self.back_btn = QPushButton("◀\n返回")
        self.back_btn.setFont(create_font(9))
        self.back_btn.setFixedSize(50, 50)
        self.back_btn.setToolTip("返回上一级")
        sidebar.addWidget(self.back_btn)

        self.home_btn = QPushButton("⌂\n主页")
        self.home_btn.setFont(create_font(9))
        self.home_btn.setFixedSize(50, 50)
        self.home_btn.setToolTip("回到主页")
        sidebar.addWidget(self.home_btn)

        self.app_switch_btn = QPushButton("⎕\n多任务")
        self.app_switch_btn.setFont(create_font(9))
        self.app_switch_btn.setFixedSize(50, 50)
        self.app_switch_btn.setToolTip("切换多任务")
        sidebar.addWidget(self.app_switch_btn)

        preview_layout.addLayout(sidebar)

        splitter.addWidget(self.preview_container)

        # 右侧：功能 Tab 页
        self.tab_widget = QTabWidget()
        self.tab_widget.setFont(create_font(9))

        # 图库 Tab
        self.library_tab = ImageLibraryTab()
        self.tab_widget.addTab(self.library_tab, "🖼 图库")

        # 脚本 Tab
        self.script_tab = ScriptTab()
        self.tab_widget.addTab(self.script_tab, "📜 脚本")

        # 循环 Tab
        self.loop_tab = LoopScriptTab()
        self.tab_widget.addTab(self.loop_tab, "🔄 循环")

        # 流程 Tab
        self.workflow_tab = WorkflowTab()
        self.tab_widget.addTab(self.workflow_tab, "🔗 流程")

        # 默认选中脚本 Tab
        self.tab_widget.setCurrentIndex(1)

        # 启动/停止 和 暂停/继续 按钮放在 Tab 栏右侧
        corner_widget = QWidget()
        corner_layout = QHBoxLayout(corner_widget)
        corner_layout.setContentsMargins(0, 0, 4, 0)
        corner_layout.setSpacing(4)

        self.start_btn = QPushButton("▶ 启动")
        self.start_btn.setFont(create_font(10, bold=True))
        self.start_btn.setFixedSize(80, 28)
        self.start_btn.setObjectName("successBtn")
        self.start_btn.setCheckable(True)

        self.pause_btn = QPushButton("⏸ 暂停")
        self.pause_btn.setFont(create_font(10, bold=True))
        self.pause_btn.setFixedSize(80, 28)
        self.pause_btn.setObjectName("warningBtn")
        self.pause_btn.setEnabled(False)

        corner_layout.addWidget(self.start_btn)
        corner_layout.addWidget(self.pause_btn)
        self.tab_widget.setCornerWidget(corner_widget)

        splitter.addWidget(self.tab_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        content_layout.addWidget(splitter, 1)

        # ===== 底部：日志区 =====
        log_group = QGroupBox("运行日志")
        log_group.setFont(create_font(9, bold=True))
        log_layout = QVBoxLayout(log_group)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setMaximumHeight(180)
        self.log_text.setStyleSheet(
            "background-color: #1e1e2e; color: #cdd6f4; "
            f"border: 1px solid {COLOR_BORDER}; border-radius: 4px;"
        )

        log_layout.addWidget(self.log_text)
        content_layout.addWidget(log_group)

        # 初始加载设备列表
        QTimer.singleShot(100, self._refresh_devices)

    def _connect_signals(self):
        """连接信号槽。"""
        self.adb_combo.currentIndexChanged.connect(self._on_adb_changed)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        self.refresh_device_btn.clicked.connect(self._refresh_devices)
        self.restart_adb_btn.clicked.connect(self._restart_adb)
        self.start_btn.toggled.connect(self._on_start_toggled)
        self.pause_btn.clicked.connect(self._on_pause)
        self.screenshot_btn.clicked.connect(self._on_manual_screenshot)
        self.live_sync_btn.clicked.connect(self._on_toggle_live_sync)
        self.display_power_btn.clicked.connect(self._on_toggle_display_power)
        self.group_control_btn.clicked.connect(self._on_toggle_group_control)

        # 系统控制按钮
        self.back_btn.clicked.connect(self._on_action_back)
        self.home_btn.clicked.connect(self._on_action_home)
        self.app_switch_btn.clicked.connect(self._on_action_app_switch)

        # 预览区鼠标进出事件过滤（录制时自动暂停/恢复）
        self.preview_container.installEventFilter(self)

        # 侧边栏录制控制按钮
        self.sidebar_stop_btn.clicked.connect(self.script_tab._on_stop_record)
        self.sidebar_pause_btn.clicked.connect(self.script_tab._toggle_record_pause)

        # Y 偏移变化时实时更新预览标记
        self.script_tab.y_offset_spin.valueChanged.connect(
            self.screenshot_widget.set_y_offset
        )

    def eventFilter(self, obj, event):
        """预览区鼠标进出事件：录制时自动暂停/恢复，遮罩始终保持"""
        from PyQt6.QtCore import QEvent
        if obj is self.preview_container and self.script_tab.is_recording:
            if event.type() == QEvent.Type.Leave:
                # 鼠标离开预览区 → 自动暂停
                if not self.script_tab._recording_paused:
                    self.script_tab._toggle_record_pause()
            elif event.type() == QEvent.Type.Enter:
                # 鼠标进入预览区 → 自动恢复
                if self.script_tab._recording_paused:
                    self.script_tab._toggle_record_pause()
        return super().eventFilter(obj, event)

    def _create_dim_effect(self):
        """创建变暗效果"""
        from PyQt6.QtWidgets import QGraphicsOpacityEffect
        effect = QGraphicsOpacityEffect()
        effect.setOpacity(0.3)
        return effect

    def _apply_styles(self):
        """应用全局样式（手册 §十二配色规范）。"""
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {COLOR_BG};
            }}
            QGroupBox {{
                border: 1px solid {COLOR_BORDER};
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 16px;
                color: {COLOR_TEXT};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
            QComboBox {{
                border: 1px solid {COLOR_BORDER};
                border-radius: 4px;
                padding: 4px 8px;
                background: white;
                color: {COLOR_TEXT};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid {COLOR_TEXT};
                margin-right: 6px;
            }}
            QSpinBox, QDoubleSpinBox {{
                border: 1px solid {COLOR_BORDER};
                border-radius: 4px;
                padding: 3px 6px;
                background: white;
                color: {COLOR_TEXT};
            }}
            QPushButton#successBtn {{
                background-color: {COLOR_SUCCESS};
                color: white;
                border: none;
                border-radius: 4px;
            }}
            QPushButton#successBtn:hover {{
                background-color: #85ce61;
            }}
            QPushButton#successBtn:disabled {{
                background-color: {COLOR_DISABLED};
            }}
            QPushButton#warningBtn {{
                background-color: {COLOR_WARNING};
                color: white;
                border: none;
                border-radius: 4px;
            }}
            QPushButton#warningBtn:hover {{
                background-color: #ebb563;
            }}
            QPushButton#warningBtn:disabled {{
                background-color: {COLOR_DISABLED};
            }}
            QPushButton#dangerBtn {{
                background-color: {COLOR_DANGER};
                color: white;
                border: none;
                border-radius: 4px;
            }}
            QPushButton#dangerBtn:hover {{
                background-color: #f78989;
            }}
            QPushButton#dangerBtn:disabled {{
                background-color: {COLOR_DISABLED};
            }}
            QPushButton {{
                background-color: white;
                color: {COLOR_TEXT};
                border: 1px solid {COLOR_BORDER};
                border-radius: 4px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{
                border-color: {COLOR_PRIMARY};
                color: {COLOR_PRIMARY};
            }}
            QTabWidget::pane {{
                border: 1px solid {COLOR_BORDER};
                border-radius: 4px;
                background: white;
            }}
            QTabBar::tab {{
                padding: 6px 16px;
                margin-right: 2px;
                border: 1px solid {COLOR_BORDER};
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                background: {COLOR_BG};
                color: {COLOR_TEXT};
            }}
            QTabBar::tab:selected {{
                background: white;
                border-bottom: 2px solid {COLOR_PRIMARY};
                color: {COLOR_PRIMARY};
            }}
            QLabel {{
                color: {COLOR_TEXT};
            }}
        """)

    # ==================== ADB / 设备管理（后台线程，不阻塞 UI） ====================

    def _on_adb_changed(self, index):
        """切换 ADB 路径。"""
        if index < 0:
            return
        adb_path = self.adb_combo.itemData(index)
        adb_name = self.adb_combo.itemText(index)
        set_adb_path(adb_path)
        self._append_log(f"已切换 ADB: {adb_name}")

    def _restart_adb(self):
        """后台重启 ADB 服务器（不阻塞 UI）。"""
        self.restart_adb_btn.setEnabled(False)
        self._append_log(f"正在重启 ADB 服务器 ({self.adb_combo.currentText()})...")

        def _do_restart():
            _flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            adb = config.ADB_PATH
            subprocess.run([adb, "kill-server"],
                           capture_output=True, timeout=10, creationflags=_flags)
            subprocess.run([adb, "start-server"],
                           capture_output=True, timeout=15, creationflags=_flags)
            return True

        task = AdbTask(_do_restart, parent=self)
        task.finished.connect(lambda _: self._on_restart_done())
        task.error.connect(lambda e: self._on_restart_error(e))
        self._adb_task = task  # 保持引用防止 GC
        task.start()

    def _on_restart_done(self):
        self.restart_adb_btn.setEnabled(True)
        self._append_log("ADB 服务器已重启")
        self._refresh_devices()

    def _on_restart_error(self, err):
        self.restart_adb_btn.setEnabled(True)
        self._append_log(f"重启 ADB 失败: {err}")

    def _refresh_devices(self):
        """后台刷新设备列表（不阻塞 UI）。"""
        self.refresh_device_btn.setEnabled(False)
        self.device_combo.clear()
        self.device_combo.addItem("扫描中...")

        task = AdbTask(get_connected_devices, parent=self)
        task.finished.connect(self._on_devices_found)
        task.error.connect(self._on_devices_error)
        self._adb_task = task
        task.start()

    @pyqtSlot(object)
    def _on_devices_found(self, devices):
        """设备扫描完成回调。"""
        self.refresh_device_btn.setEnabled(True)
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        if devices:
            self.device_combo.addItems(devices)
            self.device_combo.blockSignals(False)
            self._append_log(f"发现 {len(devices)} 个设备: {', '.join(devices)}")
            self._detect_resolution(devices[0])
            # 刷新设备列表后，如果之前状态是开启同步且选中了新设备，应该重启同步
            if self.live_sync_btn.isChecked():
                self._on_toggle_live_sync(False)
                self._on_toggle_live_sync(True)
        else:
            self.device_combo.blockSignals(False)
            self._append_log("未发现设备，请检查模拟器是否启动")
            self.resolution_label.setText("")

    @pyqtSlot(int)
    def _on_device_changed(self, index):
        """设备下拉选择变更时的响应。"""
        if index < 0:
            return
        device_id = self.device_combo.currentText()
        if not device_id or device_id == "扫描中...":
            return
            
        self._append_log(f"已切换目标设备 -> {device_id}")
        self._detect_resolution(device_id)
        
        # 切换设备时，如果当前属于开启同步状态，需要重启同步进程绑定到新设备上
        if self.live_sync_btn.isChecked():
            self._append_log("正在切换实时同步的设备...")
            self._on_toggle_live_sync(False)
            self._on_toggle_live_sync(True)

    @pyqtSlot(str)
    def _on_devices_error(self, err):
        self.refresh_device_btn.setEnabled(True)
        self.device_combo.clear()
        self._append_log(f"设备扫描失败: {err}")

    def _detect_resolution(self, device_id):
        """后台检测设备分辨率（不阻塞 UI）。"""
        task = AdbTask(get_resolution, device_id, parent=self)
        task.finished.connect(self._on_resolution_found)
        task.error.connect(lambda e: self._append_log(f"分辨率检测失败: {e}"))
        self._adb_task = task
        task.start()

    @pyqtSlot(object)
    def _on_resolution_found(self, result):
        """分辨率检测完成回调。"""
        w, h = result
        if w > 0 and h > 0:
            set_device_resolution(w, h)
            self.resolution_label.setText(f"{w}×{h}")
            self._append_log(f"设备分辨率: {w}×{h}")
        else:
            self.resolution_label.setText("分辨率未知")
            self._append_log("无法获取设备分辨率")

    # ==================== 控制按钮 ====================

    def _on_start_toggled(self, checked):
        """启动/停止 切换按钮。"""
        if checked:
            self._do_start()
        else:
            self._do_stop()

    def _do_start(self):
        """启动工作线程。"""
        device_id = self.device_combo.currentText()
        if not device_id:
            self._append_log("请先选择一个设备")
            self.start_btn.setChecked(False)
            return

        # 判断当前 Tab 决定执行模式
        current_tab = self.tab_widget.currentWidget()
        is_loop_mode = isinstance(current_tab, LoopScriptTab)
        is_workflow_mode = isinstance(current_tab, WorkflowTab)
        
        if is_loop_mode:
            if not self.loop_tab.current_model:
                self._append_log("请先在循环 Tab 中导入一个脚本项目")
                self.start_btn.setChecked(False)
                return
            script_model = self.loop_tab.current_model
            enabled_templates = self.loop_tab.get_enabled_templates()
        elif is_workflow_mode:
            # 流程模式
            wf_model = self.workflow_tab.current_model
            if not wf_model or not wf_model.steps:
                self._append_log("请先在流程 Tab 中添加执行步骤")
                self.start_btn.setChecked(False)
                return

            # 有批次配置时，使用 WorkflowRunner 按批次执行
            if wf_model.batches:
                self._start_workflow_runner(wf_model)
                return

            # 无批次，退化为在当前设备上单独执行
            from script_model import ScriptModel
            script_model = ScriptModel(name=f"流程:{wf_model.name}")
            script_model.actions = list(wf_model.steps)
            if wf_model.pictures_dir:
                script_model.project_dir = wf_model.project_dir
            enabled_templates = None
        else:
            script_model = self.script_tab.current_model
            enabled_templates = None

        # 预检查：脚本分辨率与模拟器分辨率是否一致
        script_cfg = script_model.config
        if script_cfg.check_resolution and script_cfg.resolution and script_cfg.resolution != "unknown":
            from config import get_resolution_tag
            device_res = get_resolution_tag()
            if device_res != "unknown" and script_cfg.resolution != device_res:
                from PyQt6.QtWidgets import QMessageBox
                reply = QMessageBox.warning(
                    self, "分辨率不匹配",
                    f"脚本适配分辨率为 {script_cfg.resolution}，\n当前模拟器分辨率为 {device_res}。\n\n"
                    "分辨率不一致可能导致找图失败，是否强制启动？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    self.start_btn.setChecked(False)
                    return

        self._runtime_config = self.script_tab.get_runtime_config()
        self._workers = []

        from device_adapter import HybridDeviceAdapter

        target_adapters = self._get_all_active_adapters()
        for raw_adapter in target_adapters:
            # 从适配器对象上获取设备 ID
            d_id = getattr(raw_adapter, 'device_id', device_id)
            # 提取现有的 Scrcpy client 连接，组装为混合适配器
            scrcpy_client = getattr(raw_adapter, 'client', None)
            hybrid_adapter = HybridDeviceAdapter(d_id, scrcpy_client=scrcpy_client)

            worker = BotWorker(
                d_id, script_model=script_model,
                loop_mode=is_loop_mode, enabled_templates=enabled_templates,
                adapter=hybrid_adapter, parent=self
            )

            worker.log_signal.connect(self._append_log)
            # 视觉组件暂时只绑定主设备(下拉框选中的设备)用于预览，不渲染其他群控窗口的画面
            if d_id == device_id:
                worker.screenshot_signal.connect(self.screenshot_widget.update_screenshot)
                worker.match_signal.connect(self.screenshot_widget.update_matches)
                
            worker.status_signal.connect(self._update_status)
            worker.finished_signal.connect(self._on_worker_finished)

            self._workers.append(worker)
            worker.start()

        self._sync_timer.start(500)

        # UI 状态更新：按钮切换为停止模式
        self.start_btn.setText("⏹ 停止")
        self.start_btn.setObjectName("dangerBtn")
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)
        self.pause_btn.setEnabled(True)
        self.tab_widget.tabBar().setEnabled(False)  # 运行时禁止切换 Tab
        self.device_combo.setEnabled(False)
        self._buy_count = 0

    def _start_workflow_runner(self, wf_model):
        """使用 WorkflowRunner 按批次执行流程。"""
        from workflow_runner import WorkflowRunner

        self._workflow_runner = WorkflowRunner(wf_model, parent=self)
        self._workflow_runner.log_signal.connect(self._append_log)
        self._workflow_runner.status_signal.connect(self._update_status)
        self._workflow_runner.batch_progress_signal.connect(
            lambda cur, total: self._update_status(f"批次 {cur}/{total}")
        )
        self._workflow_runner.finished_signal.connect(self._on_worker_finished)
        self._workflow_runner.start()

        # UI 状态更新
        self.start_btn.setText("⏹ 停止")
        self.start_btn.setObjectName("dangerBtn")
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)
        self.pause_btn.setEnabled(False)  # 批次模式暂不支持暂停
        self.tab_widget.tabBar().setEnabled(False)
        self.device_combo.setEnabled(False)

    def _on_pause(self):
        """暂停/继续按钮。"""
        if not self._workers:
            return

        # 以列表中第一个 Worker 的状态为准进行全局翻转
        if self._workers[0].is_paused():
            for w in self._workers:
                w.resume()
            self.pause_btn.setText("⏸ 暂停")
            self._append_log("所有设备已恢复运行")
        else:
            for w in self._workers:
                w.pause()
            self.pause_btn.setText("▶ 继续")
            self._append_log("所有设备已暂停")

    def _do_stop(self):
        """停止工作线程。"""
        # 停止 WorkflowRunner（如果有）
        if self._workflow_runner and self._workflow_runner.isRunning():
            self._append_log("正在停止流程执行...")
            self._workflow_runner.stop()
            self._workflow_runner.wait(10000)
            return

        if not self._workers:
            return

        self._append_log("正在停止所有运行中的设备...")
        for w in self._workers:
            w.stop()
        
        for w in self._workers:
            w.wait(5000)
            
        # _on_worker_finished 会在单个完毕时被接连调用，这里只需触发即可

    def _on_worker_finished(self):
        """工作线程结束后的清理。"""
        sender_worker = self.sender()

        # WorkflowRunner 完成
        if sender_worker is self._workflow_runner:
            self._workflow_runner = None
            # 继续执行下方的 UI 恢复逻辑
        elif sender_worker in self._workers:
            self._workers.remove(sender_worker)
            # 只有当所有 worker 全部跑完后，才恢复 UI
            if len(self._workers) > 0:
                return

        self._sync_timer.stop()
        self._runtime_config = None

        # 恢复按钮为启动状态
        self.start_btn.blockSignals(True)
        self.start_btn.setChecked(False)
        self.start_btn.blockSignals(False)
        self.start_btn.setText("▶ 启动")
        self.start_btn.setObjectName("successBtn")
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("⏸ 暂停")
        self.tab_widget.tabBar().setEnabled(True)  # 恢复 Tab 切换
        self.device_combo.setEnabled(True)
        self._update_status("已停止")

    # ==================== 快捷操作 ====================

    def _ensure_screencap_worker(self):
        """确保截图后台线程已创建并配置。"""
        device_id = self.device_combo.currentText()
        if not device_id:
            return None

        if self._screencap_worker is None:
            self._screencap_worker = ScreencapWorker(parent=self)
            self._screencap_worker.screenshot_ready.connect(
                self._on_screenshot_ready
            )
            self._screencap_worker.log_signal.connect(self._append_log)
            self._screencap_worker.fps_signal.connect(self._on_fps_update)
            # 连接 ScrcpyAdapter 就绪信号
            self._screencap_worker.adapter_ready.connect(
                self._on_adapter_ready
            )

        self._screencap_worker.setup(device_id)
        return self._screencap_worker

    def _on_manual_screenshot(self):
        """手动截图按钮：后台线程执行，不阻塞 UI。"""
        worker = self._ensure_screencap_worker()
        if worker is None:
            self._append_log("请先选择一个设备")
            return
        self._append_log("正在截图...")
        worker.capture_once()

    @pyqtSlot(QImage)
    def _on_screenshot_ready(self, q_image):
        """截图完成回调：更新预览区。"""
        self.screenshot_widget.update_screenshot(q_image)

    @pyqtSlot(object)
    def _on_adapter_ready(self, adapter):
        """ScrcpyAdapter 就绪回调：注入到 ScreenshotWidget 供录制/操作使用。"""
        self.screenshot_widget._scrcpy_adapter = adapter
        self._append_log("ScrcpyAdapter 已就绪（支持低延迟触摸操作）")
        self._update_ui_scrcpy_count()

    def _on_toggle_live_sync(self, checked):
        """实时同步开关：启动/停止持续截图与实时操纵。"""
        device_id = self.device_combo.currentText()
        if not device_id:
            self.live_sync_btn.setChecked(False)
            self._append_log("请先选择一个设备")
            return

        worker = self._ensure_screencap_worker()

        if checked:
            worker.setup(device_id, continuous=True)
            if not worker.isRunning():
                worker.start()

            self.live_sync_btn.setText("⏹\n停止")
            self.screenshot_btn.setEnabled(False)
            self.screenshot_widget._live_control_mode = True
            self._append_log("实时画面同步已启动（支持直接操作屏幕）")
        else:
            if self._screencap_worker is not None:
                self._screencap_worker.requestInterruption()
                self._screencap_worker.wait(2000)

            self.live_sync_btn.setText("▶\n同步")
            self.screenshot_btn.setEnabled(True)
            self.screenshot_widget._live_control_mode = False
            self.screenshot_widget._scrcpy_adapter = None # 清除旧设备的控制器引用
            self._append_log("实时画面同步已停止")

        self._update_ui_scrcpy_count()

    # ---------- 系统控制按钮操作 ----------

    def _get_active_adapter(self):
        """获取当前适配器：优先 ScrcpyAdapter，否则回退 AdbAdapter"""
        if getattr(self.screenshot_widget, '_scrcpy_adapter', None) and self.screenshot_widget._scrcpy_adapter.supports_touch:
            return self.screenshot_widget._scrcpy_adapter
        device_id = self.device_combo.currentText()
        if device_id:
            from device_adapter import AdbAdapter
            return AdbAdapter(device_id)
        return None
        
    def _get_all_active_adapters(self):
        """获取所有存活的可执行适配器（用于群控）。"""
        adapters = []
        seen_devices = set()
        
        # 主同步设备
        main_adapter = getattr(self.screenshot_widget, '_scrcpy_adapter', None)
        if main_adapter and main_adapter.supports_touch:
            adapters.append(main_adapter)
            seen_devices.add(main_adapter.device_id)
            
        # 群控的控制通道设备
        for device_id, adapter in self._group_adapters.items():
            if adapter and adapter.supports_touch and device_id not in seen_devices:
                adapters.append(adapter)
                seen_devices.add(device_id)
                
        # 如果既没有同步也没有群控，退化为仅在当前 ADB 设备上进行单控
        if not adapters:
            single = self._get_active_adapter()
            if single:
                adapters.append(single)
        return adapters

    def _on_toggle_group_control(self, checked: bool):
        from PyQt6.QtWidgets import QApplication
        from adb_utils import get_connected_devices
        
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if checked:
                devices = get_connected_devices()
                current_sync = self.device_combo.currentText() if self.live_sync_btn.isChecked() else None
                success_count = 0
                
                self._append_log(f"🔄 正在为 {len(devices)} 台设备初始化控制通道...")
                
                import threading
                def _connect_worker(d_id):
                    nonlocal success_count
                    if d_id == current_sync:
                        return # 已经有主通道了
                    try:
                        from scrcpy_client import ScrcpyClient
                        from device_adapter import ScrcpyAdapter
                        client = ScrcpyClient(d_id, control_only=True)
                        client.start(threaded=False)
                        adapter = ScrcpyAdapter(d_id, client)
                        self._group_adapters[d_id] = adapter
                        success_count += 1
                        self._append_log(f"✅ {d_id} 无画面控制通道建立成功")
                    except Exception as e:
                        self._append_log(f"❌ {d_id} 控制通道建立失败: {e}")
                
                threads = []
                for d in devices:
                    t = threading.Thread(target=_connect_worker, args=(d,))
                    threads.append(t)
                    t.start()
                
                for t in threads:
                    t.join()
                
                self._append_log(f"🎉 群控已启动（通道数: {success_count}）")
                self.group_control_btn.setText("⏹ 停控")
            else:
                self._append_log("🔴 正在关闭群控通道...")
                for d_id, adapter in self._group_adapters.items():
                    if adapter and getattr(adapter, 'client', None):
                        try:
                            adapter.client.stop()
                        except: pass
                self._group_adapters.clear()
                self._append_log("✅ 群控已停止")
                self.group_control_btn.setText("👥 群控")
                
            self._update_ui_scrcpy_count()
        finally:
            QApplication.restoreOverrideCursor()

    def _update_ui_scrcpy_count(self):
        """更新 UI 上的 Scrcpy 连接数"""
        active_devices = set(self._group_adapters.keys())
        main_adapter = getattr(self.screenshot_widget, '_scrcpy_adapter', None)
        if main_adapter and main_adapter.supports_touch:
            active_devices.add(main_adapter.device_id)
        self._update_scrcpy_count(len(active_devices))

    def _on_action_back(self):
        adapter = self._get_active_adapter()
        if adapter:
            adapter.back()
            self._record_system_action("back")

    def _on_action_home(self):
        adapter = self._get_active_adapter()
        if adapter:
            adapter.home()
            self._record_system_action("home")

    def _on_action_app_switch(self):
        adapter = self._get_active_adapter()
        if adapter:
            adapter.app_switch()
            self._record_system_action("app_switch")
            
    def _record_system_action(self, action_type: str):
        """如果当前处于录制状态，将系统快捷键操作发送到由于 ScriptTab"""
        if hasattr(self, 'script_tab') and getattr(self.script_tab, 'is_recording', False):
            self.script_tab.on_recorded_system_action(action_type)

    def _on_toggle_display_power(self, checked: bool):
        adapter = self._get_active_adapter()
        if adapter:
            on = not checked  # 选中(熄屏) -> on=False
            adapter.set_display_power(on)
            if checked:
                self.display_power_btn.setText("💡\n亮屏")
                self._append_log("已发送熄屏指令 (关闭物理屏幕背光)")
            else:
                self.display_power_btn.setText("🌙\n熄屏")
                self._append_log("已发送亮屏指令")



    # ==================== 参数同步 ====================

    def _sync_params(self):
        """定时将 UI 参数同步到运行时配置（热更新）。"""
        if self._runtime_config is not None:
            self.script_tab.sync_to_runtime_config(self._runtime_config)

    # ==================== 坐标拾取回调 ====================

    def on_coord_picked(self, x, y):
        """截图预览区坐标拾取回调。"""
        self._last_picked_coord = (x, y)
        self.coord_label.setText(f"坐标: ({x}, {y})")
        
        # 劫持模式拦截：在此将坐标分发给开启录制的脚本面板
        if getattr(self.script_tab, 'is_recording', False):
            self._append_log(f"🔴 [录制] 正在生成步骤指令 ({x}, {y})...")
            device_id = self.device_combo.currentText()
            self.script_tab.on_recorded_click(device_id, x, y)
        else:
            self._append_log(f"拾取坐标: ({x}, {y})")

    def on_swipe_picked(self, x1, y1, x2, y2, duration_ms=300, path=None):
        """截图预览区滑动拾取回调。"""
        self.coord_label.setText(f"滑动: ({x1},{y1})→({x2},{y2}) {duration_ms}ms")
        
        if getattr(self.script_tab, 'is_recording', False):
            self._append_log(f"🔴 [录制] 滑动 ({x1},{y1})→({x2},{y2}) {duration_ms}ms")
            device_id = self.device_combo.currentText()
            self.script_tab.on_recorded_swipe(device_id, x1, y1, x2, y2, duration_ms, path)
        else:
            self._append_log(f"滑动: ({x1},{y1})→({x2},{y2})")

    def on_coord_hover(self, x, y):
        """截图预览区鼠标悬停坐标回调。"""
        self.coord_label.setText(f"坐标: ({x}, {y})")

    # ==================== 状态更新 ====================

    @pyqtSlot(str)
    def _update_status(self, status):
        """更新状态栏。"""
        self.status_label.setText(f"状态: {status}")

    @pyqtSlot(int)
    def _update_scrcpy_count(self, count):
        """更新 Scrcpy 连接数显示。"""
        self.scrcpy_count_label.setText(f"连接数: {count}")

    @pyqtSlot(float)
    def _on_fps_update(self, fps):
        """更新 FPS 显示。"""
        self.fps_label.setText(f"FPS: {fps:.1f}")

    # ==================== 日志 ====================

    @pyqtSlot(str)
    def _append_log(self, msg):
        """追加日志到日志区（自动滚动到底部）。"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {msg}")
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ==================== 窗口关闭 ====================

    def closeEvent(self, event):
        """窗口关闭时安全停止所有工作线程。"""
        if self.live_sync_btn.isChecked():
            self.live_sync_btn.setChecked(False)
            self._on_toggle_live_sync(False)
        
        # Stop all bot workers
        if hasattr(self, '_workers') and self._workers: # Check if _workers exists and is not empty
            for worker in self._workers:
                if worker.isRunning():
                    worker.stop()
                    worker.wait(3000) # Wait for worker to finish
            self._workers.clear() # Clear the list after stopping all

        if self._screencap_worker is not None and self._screencap_worker.isRunning():
            self._screencap_worker.requestInterruption()
            self._screencap_worker.wait(2000)
        self._sync_timer.stop()
        event.accept()
