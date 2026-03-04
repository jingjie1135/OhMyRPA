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
from gui.tabs import ImageLibraryTab, ScriptTab, WorkflowTab


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
        self._worker = None             # 工作线程引用
        self._runtime_config = None     # 运行时参数引用
        self._last_picked_coord = None  # 最近一次拾取的坐标
        self._screencap_worker = None   # 截图后台线程
        self._buy_count = 0

        self._init_ui()
        self._connect_signals()
        self._apply_styles()

        # 参数热更新定时器：每 500ms 同步 UI 参数到工作线程（手册 §十）
        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self._sync_params)

    def _init_ui(self):
        """构建主界面布局。"""
        self.setWindowTitle("模拟器 · 自动化脚本 v0.1")
        self.resize(1000, 800)
        self.setMinimumSize(1000, 800)

        # 中央控件
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # ===== 顶部：ADB + 设备选择栏 =====
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

        self.buy_count_label = QLabel("已购买: 0")
        self.buy_count_label.setFont(create_font(9, bold=True))
        self.buy_count_label.setStyleSheet(f"color: {COLOR_SUCCESS};")
        top_bar.addWidget(self.buy_count_label)

        self.fps_label = QLabel("")
        self.fps_label.setFont(create_font(9, bold=True))
        self.fps_label.setStyleSheet(f"color: {COLOR_PRIMARY};")
        self.fps_label.setMinimumWidth(80)
        top_bar.addWidget(self.fps_label)

        self.resolution_label = QLabel("")
        self.resolution_label.setFont(create_font(8))
        self.resolution_label.setStyleSheet(f"color: {COLOR_DISABLED};")
        top_bar.addWidget(self.resolution_label)

        main_layout.addLayout(top_bar)

        # ===== 中部：截图预览 + 功能面板 =====
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧：截图预览 + 侧边栏
        preview_container = QWidget()
        preview_layout = QHBoxLayout(preview_container)
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

        sidebar.addStretch()
        preview_layout.addLayout(sidebar)

        splitter.addWidget(preview_container)

        # 右侧：功能 Tab 页
        self.tab_widget = QTabWidget()
        self.tab_widget.setFont(create_font(9))

        # 图库 Tab
        self.library_tab = ImageLibraryTab()
        self.tab_widget.addTab(self.library_tab, "🖼 图库")

        # 脚本 Tab
        self.script_tab = ScriptTab()
        self.tab_widget.addTab(self.script_tab, "📜 脚本")

        # 流程 Tab
        self.workflow_tab = WorkflowTab()
        self.tab_widget.addTab(self.workflow_tab, "🔗 流程")

        # 默认选中脚本 Tab
        self.tab_widget.setCurrentIndex(1)

        splitter.addWidget(self.tab_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        main_layout.addWidget(splitter, 1)

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
        main_layout.addWidget(log_group)

        # 初始加载设备列表
        QTimer.singleShot(100, self._refresh_devices)

    def _connect_signals(self):
        """连接信号槽。"""
        self.adb_combo.currentIndexChanged.connect(self._on_adb_changed)
        self.refresh_device_btn.clicked.connect(self._refresh_devices)
        self.restart_adb_btn.clicked.connect(self._restart_adb)
        self.script_tab.start_btn.clicked.connect(self._on_start)
        self.script_tab.pause_btn.clicked.connect(self._on_pause)
        self.script_tab.stop_btn.clicked.connect(self._on_stop)
        self.screenshot_btn.clicked.connect(self._on_manual_screenshot)
        self.live_sync_btn.clicked.connect(self._on_toggle_live_sync)

        # Y 偏移变化时实时更新预览标记
        self.script_tab.y_offset_spin.valueChanged.connect(
            self.screenshot_widget.set_y_offset
        )

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
        self.device_combo.clear()
        if devices:
            self.device_combo.addItems(devices)
            self._append_log(f"发现 {len(devices)} 个设备: {', '.join(devices)}")
            self._detect_resolution(devices[0])
        else:
            self._append_log("未发现设备，请检查模拟器是否启动")
            self.resolution_label.setText("")

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

    def _on_start(self):
        """启动按钮：创建并启动工作线程。"""
        device_id = self.device_combo.currentText()
        if not device_id:
            self._append_log("请先选择一个设备")
            return

        self._runtime_config = self.script_tab.get_runtime_config()
        self._worker = BotWorker(device_id, self._runtime_config, parent=self)

        self._worker.log_signal.connect(self._append_log)
        self._worker.screenshot_signal.connect(self.screenshot_widget.update_screenshot)
        self._worker.match_signal.connect(self.screenshot_widget.update_matches)
        self._worker.status_signal.connect(self._update_status)
        self._worker.buy_count_signal.connect(self._update_buy_count)
        self._worker.finished_signal.connect(self._on_worker_finished)

        self._worker.start()
        self._sync_timer.start(500)

        # UI 状态更新
        self.script_tab.start_btn.setEnabled(False)
        self.script_tab.pause_btn.setEnabled(True)
        self.script_tab.stop_btn.setEnabled(True)
        self.device_combo.setEnabled(False)
        self._buy_count = 0

    def _on_pause(self):
        """暂停/继续按钮。"""
        if self._worker is None:
            return

        if self._worker.is_paused():
            self._worker.resume()
            self.script_tab.pause_btn.setText("⏸ 暂停")
            self._append_log("已恢复运行")
        else:
            self._worker.pause()
            self.script_tab.pause_btn.setText("▶ 继续")
            self._append_log("已暂停")

    def _on_stop(self):
        """停止按钮（手册 §六资源保护）。"""
        if self._worker is None:
            return

        self._append_log("正在停止...")
        self._worker.stop()
        self._worker.wait(5000)
        self._on_worker_finished()

    def _on_worker_finished(self):
        """工作线程结束后的清理。"""
        self._sync_timer.stop()
        self._worker = None
        self._runtime_config = None

        self.script_tab.start_btn.setEnabled(True)
        self.script_tab.pause_btn.setEnabled(False)
        self.script_tab.pause_btn.setText("⏸ 暂停")
        self.script_tab.stop_btn.setEnabled(False)
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

    def _on_toggle_live_sync(self, checked):
        """实时同步开关：启动/停止持续截图。"""
        if checked:
            worker = self._ensure_screencap_worker()
            if worker is None:
                self._append_log("请先选择一个设备")
                self.live_sync_btn.setChecked(False)
                return

            worker.setup(self.device_combo.currentText(), continuous=True)
            if not worker.isRunning():
                worker.start()

            self.live_sync_btn.setText("⏹\n停止")
            self.screenshot_btn.setEnabled(False)
            self._append_log("实时画面同步已启动")
        else:
            if self._screencap_worker is not None:
                self._screencap_worker.requestInterruption()
                self._screencap_worker.wait(2000)

            self.live_sync_btn.setText("▶\n同步")
            self.screenshot_btn.setEnabled(True)
            self._append_log("实时画面同步已停止")



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
        self._append_log(f"拾取坐标: ({x}, {y})")

    def on_coord_hover(self, x, y):
        """截图预览区鼠标悬停坐标回调。"""
        self.coord_label.setText(f"坐标: ({x}, {y})")

    # ==================== 状态更新 ====================

    @pyqtSlot(str)
    def _update_status(self, status):
        """更新状态栏。"""
        self.status_label.setText(f"状态: {status}")

    @pyqtSlot(int)
    def _update_buy_count(self, count):
        """更新购买计数。"""
        self._buy_count = count
        self.buy_count_label.setText(f"已购买: {count}")

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
        if self._worker is not None and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(3000)
        if self._screencap_worker is not None and self._screencap_worker.isRunning():
            self._screencap_worker.requestInterruption()
            self._screencap_worker.wait(2000)
        self._sync_timer.stop()
        event.accept()
