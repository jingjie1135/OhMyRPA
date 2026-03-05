"""
脚本编写页：可视化动作流编辑器。
"""

import time as _time
import os


import cv2
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, 
    QGroupBox, QLabel, QPushButton, QComboBox, QCheckBox,
    QSplitter, QListWidget, QTreeWidget, QTreeWidgetItem, QStackedWidget,
    QInputDialog
)

from gui.constants import create_font
from script_model import ScriptModel, ActionNode


class _RecordClickWorker(QThread):
    """录制点击时的后台线程，避免 ADB 截图/点击阻塞主线程。"""
    # 截图完成信号：(snapshot_path, x, y, timestamp)
    finished = pyqtSignal(str, int, int, float)
    
    def __init__(self, device_id: str, x: int, y: int, temp_dir: str = "Temp",
                 enable_snapshot: bool = True, parent=None):
        super().__init__(parent)
        self.device_id = device_id
        self.x = x
        self.y = y
        self.temp_dir = temp_dir
        self.enable_snapshot = enable_snapshot
        
    def run(self):
        from adb_utils import screencap_to_memory, tap
        
        now = _time.time()
        snapshot_name = ""
        
        # 1. 截图保存到项目 Temp 目录（可选，开启时有 1~3s 延迟）
        if self.enable_snapshot:
            img = screencap_to_memory(self.device_id)
            if img is not None:
                os.makedirs(self.temp_dir, exist_ok=True)
                snapshot_name = os.path.join(self.temp_dir, f"step_{int(now)}.png")
                cv2.imencode('.png', img)[1].tofile(snapshot_name)
        
        # 2. 执行点击
        tap(self.device_id, self.x, self.y)
        
        self.finished.emit(snapshot_name, self.x, self.y, now)

class ScriptTab(QWidget):
    """
    脚本编写与控制 Tab 页。
    包含：顶部控制栏 + 三栏式编辑器（左侧工具箱、中间动作列表、右侧属性面板）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_model = ScriptModel()
        self.is_recording = False
        self._recording_paused = False
        self._enable_snapshot = True  # 录制时点击前自动截图（默认开启）
        self.last_record_time = 0.0
        self._record_elapsed_before_pause = 0
        self._record_timer = None  # QElapsedTimer，录制时初始化
        self._init_ui()
        # 启动时主动加载下拉框中默认选中的脚本
        self._on_script_combo_changed(self.script_combo.currentText())

    def _init_ui(self):
        """构建界面。"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)

        # 1. 顶部工具栏 (Top Toolbar)
        top_bar = QHBoxLayout()
        
        # 脚本选择
        top_bar.addWidget(QLabel("当前脚本:"))
        self.script_combo = QComboBox()
        self.script_combo.setMinimumWidth(150)
        self._refresh_script_combo()  # 扫描目录中已有的脚本文件
        self.script_combo.currentTextChanged.connect(self._on_script_combo_changed)
        top_bar.addWidget(self.script_combo)
        
        # 新建、录制与保存
        self.new_btn = QPushButton("📁 新建")
        self.new_btn.clicked.connect(self._on_new_clicked)
        self.record_btn = QPushButton("🟢 录制操作")
        self.record_btn.setObjectName("successBtn")
        self.record_btn.clicked.connect(self._on_record_clicked)
        self.save_btn = QPushButton("💾 保存脚本")
        self.save_btn.clicked.connect(self._on_save_clicked)
        top_bar.addWidget(self.new_btn)
        top_bar.addWidget(self.record_btn)
        top_bar.addWidget(self.save_btn)
        
        top_bar.addStretch()

        main_layout.addLayout(top_bar)

        # 2. 三栏式编辑器 (Splitter)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # ================= 左侧：工具箱 =================
        left_widget = QGroupBox("指令工具箱")
        left_layout = QVBoxLayout(left_widget)
        self.toolbox_tree = QTreeWidget()
        self.toolbox_tree.setHeaderHidden(True)
        self._populate_toolbox()
        left_layout.addWidget(self.toolbox_tree)
        
        # ================= 中间：动作流水线 =================
        center_widget = QGroupBox("脚本流水线")
        center_layout = QVBoxLayout(center_widget)
        
        
        self.action_list = QListWidget()
        self.action_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.action_list.setAlternatingRowColors(True)
        # 覆盖默认深蓝选中背景，确保文字可读
        self.action_list.setStyleSheet("""
            QListWidget::item:selected {
                background-color: #e3f2fd;
                color: #1a1a2e;
            }
            QListWidget::item:hover {
                background-color: #f0f4f8;
            }
        """)
        center_layout.addWidget(self.action_list)
        
        # ================= 右侧：属性面板 =================
        right_widget = QGroupBox("参数属性")
        right_widget.setMinimumWidth(220)  # 固定最小宽度，避免切换指令时列宽跳动
        right_layout = QVBoxLayout(right_widget)
        self.props_stack = QStackedWidget()
        
        # 默认无选中时的提示
        empty_prop = QLabel("请在左侧点击指令以编辑属性")
        empty_prop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.props_stack.addWidget(empty_prop)
        
        right_layout.addWidget(self.props_stack)
        
        # 加入分割器并设置大致比例 1 : 2 : 1
        splitter.addWidget(left_widget)
        splitter.addWidget(center_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([200, 400, 250])
        
        main_layout.addWidget(splitter, stretch=1)

        # ================= 信号连接 =================
        self.toolbox_tree.itemDoubleClicked.connect(self._on_toolbox_double_clicked)
        self.action_list.currentRowChanged.connect(self._on_action_selected)
        # 拖拽排序后同步 model.actions 顺序
        self.action_list.model().rowsMoved.connect(self._on_actions_reordered)

        # ================= 占位：兼容原有 Y 偏移微调 =================
        # 这是为了不立马让 main_window 报错而弄的隐藏兼容层
        from PyQt6.QtWidgets import QSpinBox
        self.y_offset_spin = QSpinBox()
        self.y_offset_spin.hide()

    def _populate_toolbox(self):
        """填充左侧的基础工具指令到树形控件"""
        base_cat = QTreeWidgetItem(self.toolbox_tree, ["基础动作"])
        QTreeWidgetItem(base_cat, ["🖱 点击坐标"]).setData(0, Qt.ItemDataRole.UserRole, "tap")
        QTreeWidgetItem(base_cat, ["👆 滑动操作"]).setData(0, Qt.ItemDataRole.UserRole, "swipe")
        QTreeWidgetItem(base_cat, ["⏱ 延时等待"]).setData(0, Qt.ItemDataRole.UserRole, "sleep")
        
        image_cat = QTreeWidgetItem(self.toolbox_tree, ["图像识别"])
        QTreeWidgetItem(image_cat, ["🔍 找图并点击"]).setData(0, Qt.ItemDataRole.UserRole, "find_and_tap")
        QTreeWidgetItem(image_cat, ["🔍 等待图片出现"]).setData(0, Qt.ItemDataRole.UserRole, "wait_image")
        
        flow_cat = QTreeWidgetItem(self.toolbox_tree, ["流程控制"])
        QTreeWidgetItem(flow_cat, ["🔄 循环开始"]).setData(0, Qt.ItemDataRole.UserRole, "loop_start")
        QTreeWidgetItem(flow_cat, ["🔚 循环结束"]).setData(0, Qt.ItemDataRole.UserRole, "loop_end")
        
        self.toolbox_tree.expandAll()

    def _on_toolbox_double_clicked(self, item: QTreeWidgetItem, column: int):
        """双击左侧工具箱中的项，将其添加到中间流水线列表中"""
        action_type = item.data(0, Qt.ItemDataRole.UserRole)
        if not action_type:
            return  # 点击的是分类项

        from PyQt6.QtWidgets import QListWidgetItem
        from script_model import ActionNode
        
        # 常见初始参数模板
        default_params = {}
        if action_type == "tap":
            default_params = {"x": 0, "y": 0}
        elif action_type == "sleep":
            default_params = {"seconds": 1.0}
        elif action_type == "swipe":
            default_params = {"x1": 0, "y1": 0, "x2": 0, "y2": 0, "duration": 300}
        elif action_type == "find_and_tap":
            default_params = {"template": "", "threshold": 0.9, "timeout": 3.0}
        elif action_type == "wait_image":
            default_params = {"template": "", "timeout": 30.0, "action_on_fail": "abort"}

        node = ActionNode(action_type=action_type, params=default_params)
        self.current_model.add_action(node)
        self._add_node_to_ui_list(node)

    def _add_node_to_ui_list(self, node):
        """将 Node 挂载到中间视图，并刷新文本"""
        from PyQt6.QtWidgets import QListWidgetItem
        list_item = QListWidgetItem()
        list_item.setData(Qt.ItemDataRole.UserRole, node.id)
        self.action_list.addItem(list_item)
        self._refresh_action_list_text()
        
    def _on_record_clicked(self):
        """录制按钮：仅在未录制状态下触发开始"""
        if self.is_recording:
            return  # 录制中点击此按钮无效，使用侧边栏控制
        
        # 检查项目目录
        if not self.current_model.project_dir:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "请先点击「📁 新建」创建脚本项目后再开始录制。")
            return
        
        # 确认对话框（含截图开关）
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QCheckBox, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("录制操作提示")
        dlg_layout = QVBoxLayout(dlg)
        dlg_layout.addWidget(QLabel(
            "录制注意事项：\n\n"
            "• 请在预览区域内进行操作\n"
            "• 最小操作间隔为 1 秒\n"
            "• 过快操作可能导致识图错误或网络延迟出错\n"
            "• 离开预览区域会自动暂停录制\n"
            "• 使用侧边栏的按钮暂停/停止录制"
        ))
        snap_cb = QCheckBox("📸 点击前自动截图（可以把坐标点击升级为找图点击）")
        snap_cb.setChecked(self._enable_snapshot)
        dlg_layout.addWidget(snap_cb)
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(dlg.accept)
        btn_box.rejected.connect(dlg.reject)
        dlg_layout.addWidget(btn_box)
        
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._enable_snapshot = snap_cb.isChecked()
        
        # --- 开始录制 ---
        self.is_recording = True
        self._recording_paused = False
        self.record_btn.setText("🔴 正在录制")
        self.record_btn.setObjectName("dangerBtn")
        self.record_btn.style().unpolish(self.record_btn)
        self.record_btn.style().polish(self.record_btn)
        
        # 启动录制计时器
        from PyQt6.QtCore import QElapsedTimer
        self._record_timer = QElapsedTimer()
        self._record_timer.start()
        self._record_elapsed_before_pause = 0
        self.last_record_time = 0.0
        
        main_win = self.window()
        # 自动开启画面同步
        if hasattr(main_win, 'live_sync_btn') and not main_win.live_sync_btn.isChecked():
            main_win.live_sync_btn.setChecked(True)
            main_win._on_toggle_live_sync(True)
        # 激活遮罩（全程生效，直到停止录制）
        if hasattr(main_win, 'tab_widget'):
            main_win.tab_widget.setGraphicsEffect(main_win._create_dim_effect())
            main_win.tab_widget.setEnabled(False)
        # 录制模式：禁用截图框选
        if hasattr(main_win, 'screenshot_widget'):
            main_win.screenshot_widget._recording_mode = True
        # 显示侧边栏控制按钮
        if hasattr(main_win, 'sidebar_stop_btn'):
            main_win.sidebar_stop_btn.setVisible(True)
        if hasattr(main_win, 'sidebar_pause_btn'):
            main_win.sidebar_pause_btn.setVisible(True)
            main_win.sidebar_pause_btn.setText("⏸\n暂停")
        # 将鼠标移动到预览区中央
        if hasattr(main_win, 'preview_container'):
            from PyQt6.QtGui import QCursor
            center = main_win.preview_container.mapToGlobal(
                main_win.preview_container.rect().center()
            )
            QCursor.setPos(center)

    def _toggle_record_pause(self):
        """暂停/继续切换（由侧边栏按钮或鼠标进出触发）"""
        if not self.is_recording:
            return
        main_win = self.window()
        if not self._recording_paused:
            # 暂停：写入当前等待时间
            elapsed_ms = self._get_recording_elapsed_ms()
            if elapsed_ms > 100 and self.last_record_time > 0:
                sleep_sec = round(elapsed_ms / 1000.0, 1)
                sleep_node = ActionNode(action_type="sleep", params={"seconds": sleep_sec})
                self.current_model.actions.append(sleep_node)
                from PyQt6.QtWidgets import QListWidgetItem
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, sleep_node.id)
                self.action_list.addItem(item)
                self._refresh_action_list_text()
            self._recording_paused = True
            self._record_elapsed_before_pause = 0
            self.record_btn.setText("⏸ 已暂停")
            if hasattr(main_win, 'sidebar_pause_btn'):
                main_win.sidebar_pause_btn.setText("▶\n继续")
        else:
            # 继续
            self._recording_paused = False
            self._record_timer.start()
            self._record_elapsed_before_pause = 0
            self.record_btn.setText("🔴 正在录制")
            if hasattr(main_win, 'sidebar_pause_btn'):
                main_win.sidebar_pause_btn.setText("⏸\n暂停")

    def _on_stop_record(self):
        """停止录制（唯一解除遮罩的入口）"""
        if not self.is_recording:
            return
        # 写入最后等待时间
        if not self._recording_paused:
            elapsed_ms = self._get_recording_elapsed_ms()
            if elapsed_ms > 100 and self.last_record_time > 0:
                sleep_sec = round(elapsed_ms / 1000.0, 1)
                sleep_node = ActionNode(action_type="sleep", params={"seconds": sleep_sec})
                self.current_model.actions.append(sleep_node)
                from PyQt6.QtWidgets import QListWidgetItem
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, sleep_node.id)
                self.action_list.addItem(item)
                self._refresh_action_list_text()
        self.is_recording = False
        self._recording_paused = False
        self.record_btn.setText("🟢 录制操作")
        self.record_btn.setObjectName("successBtn")
        self.record_btn.style().unpolish(self.record_btn)
        self.record_btn.style().polish(self.record_btn)
        # 关闭画面同步
        main_win = self.window()
        if hasattr(main_win, 'live_sync_btn') and main_win.live_sync_btn.isChecked():
            main_win.live_sync_btn.setChecked(False)
            main_win._on_toggle_live_sync(False)
        # 解除遮罩 + 恢复 Tab 点击
        if hasattr(main_win, 'tab_widget'):
            main_win.tab_widget.setGraphicsEffect(None)
            main_win.tab_widget.setEnabled(True)
        # 恢复截图框选功能
        if hasattr(main_win, 'screenshot_widget'):
            main_win.screenshot_widget._recording_mode = False
        # 隐藏侧边栏控制按钮
        if hasattr(main_win, 'sidebar_stop_btn'):
            main_win.sidebar_stop_btn.setVisible(False)
        if hasattr(main_win, 'sidebar_pause_btn'):
            main_win.sidebar_pause_btn.setVisible(False)

    def _get_recording_elapsed_ms(self) -> int:
        """获取录制中的总累积时间(ms)，包含暂停前的时间"""
        if self._record_timer is None:
            return 0
        if self._recording_paused:
            return self._record_elapsed_before_pause
        return self._record_elapsed_before_pause + self._record_timer.elapsed()

    def on_recorded_click(self, device_id: str, x: int, y: int):
        """主窗口拦截点击后，调用的录制钩子"""
        # 暂停状态下忽略点击
        if self._recording_paused:
            return
        
        # 最小间隔保护 1 秒
        import time
        now = time.time()
        if self.last_record_time > 0 and (now - self.last_record_time) < 1.0:
            # 在日志区提示（通过 main_window）
            main_win = self.window()
            if hasattr(main_win, '_append_log'):
                main_win._append_log("⚠️ 操作过快（<1s），已忽略。过快点击可能导致识图失败。")
            return
        
        # 自动插入 sleep：记录上一次操作到现在的等待时间
        elapsed_ms = self._get_recording_elapsed_ms()
        if elapsed_ms > 100 and self.last_record_time > 0:
            sleep_sec = round(elapsed_ms / 1000.0, 1)
            sleep_node = ActionNode(action_type="sleep", params={"seconds": sleep_sec})
            self.current_model.actions.append(sleep_node)
            from PyQt6.QtWidgets import QListWidgetItem
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, sleep_node.id)
            self.action_list.addItem(item)
        
        # 重置计时器
        self._record_timer.start()
        self._record_elapsed_before_pause = 0
        self.last_record_time = now
        
        # 启动后台线程执行 ADB 截图 + 点击
        worker = _RecordClickWorker(
            device_id, x, y,
            temp_dir=self.current_model.temp_dir,
            enable_snapshot=self._enable_snapshot,
            parent=self
        )
        worker.finished.connect(self._on_record_click_done)
        if not hasattr(self, '_record_workers'):
            self._record_workers = []
        self._record_workers.append(worker)
        worker.finished.connect(lambda: self._record_workers.remove(worker))
        worker.start()
        self._refresh_action_list_text()

    def on_recorded_swipe(self, device_id: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300):
        """录制滑动操作（duration_ms 来自实际拖拽时长）"""
        if self._recording_paused:
            return
        
        # 最小间隔保护 1 秒
        import time
        now = time.time()
        if self.last_record_time > 0 and (now - self.last_record_time) < 1.0:
            main_win = self.window()
            if hasattr(main_win, '_append_log'):
                main_win._append_log("⚠️ 操作过快（<1s），已忽略。")
            return
        
        # 自动插入 sleep
        elapsed_ms = self._get_recording_elapsed_ms()
        if elapsed_ms > 100 and self.last_record_time > 0:
            sleep_sec = round(elapsed_ms / 1000.0, 1)
            sleep_node = ActionNode(action_type="sleep", params={"seconds": sleep_sec})
            self.current_model.actions.append(sleep_node)
            from PyQt6.QtWidgets import QListWidgetItem
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, sleep_node.id)
            self.action_list.addItem(item)
        
        # 重置计时器
        self._record_timer.start()
        self._record_elapsed_before_pause = 0
        self.last_record_time = now
        
        # 创建 swipe 动作节点
        node = ActionNode(
            action_type="swipe",
            params={"x1": x1, "y1": y1, "x2": x2, "y2": y2, "duration": duration_ms}
        )
        self.current_model.actions.append(node)
        from PyQt6.QtWidgets import QListWidgetItem
        list_item = QListWidgetItem()
        list_item.setData(Qt.ItemDataRole.UserRole, node.id)
        self.action_list.addItem(list_item)
        self._refresh_action_list_text()
        
        # 后台执行 ADB swipe
        import threading
        def _do_swipe():
            from adb_utils import swipe as adb_swipe
            adb_swipe(device_id, x1, y1, x2, y2, duration_ms)
        threading.Thread(target=_do_swipe, daemon=True).start()

    def _on_new_clicked(self):
        """新建脚本项目：立即创建项目文件夹结构"""
        name, ok = QInputDialog.getText(self, "新建脚本", "请输入脚本项目名称:")
        if not ok or not name or not name.strip():
            return
        name = name.strip()
        project_dir = os.path.join(ScriptModel.SCRIPTS_ROOT, name)
        if os.path.exists(project_dir):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", f"项目「{name}」已存在，请换个名称。")
            return
        # 创建新模型并立即保存（创建目录结构）
        self.current_model = ScriptModel(name=name)
        self.current_model.project_dir = project_dir
        # 自动获取当前模拟器分辨率
        from config import get_resolution_tag
        self.current_model.config.resolution = get_resolution_tag()
        self.current_model.save()  # 自动创建 Temp/ 和 Pictures/
        self._reload_action_list_ui()
        self._refresh_script_combo(select=name)
            
    def _on_save_clicked(self):
        """保存当前脚本到项目文件夹"""
        if not self.current_model.project_dir:
            # 新脚本，弹出输入框让用户命名项目
            name, ok = QInputDialog.getText(self, "保存脚本", "请输入脚本项目名称:", text="新脚本")
            if not ok or not name:
                return
            project_dir = os.path.join(ScriptModel.SCRIPTS_ROOT, name.strip())
            self.current_model.project_dir = project_dir
            self.current_model.name = name.strip()
        self.current_model.save()
        # 刷新下拉框并选中当前项目
        project_name = os.path.basename(self.current_model.project_dir)
        self._refresh_script_combo(select=project_name)

    def _refresh_script_combo(self, select: str = None):
        """扫描 Scripts/ 目录下的所有脚本项目文件夹"""
        self.script_combo.blockSignals(True)
        current_text = select or self.script_combo.currentText()
        self.script_combo.clear()
        
        projects = ScriptModel.list_projects()
        if projects:
            for p in projects:
                self.script_combo.addItem(p)
        else:
            self.script_combo.addItem("(新建脚本)")
            
        idx = self.script_combo.findText(current_text)
        if idx >= 0:
            self.script_combo.setCurrentIndex(idx)
            
        self.script_combo.blockSignals(False)

    def _on_script_combo_changed(self, project_name: str):
        """切换下拉框时，从项目目录加载脚本"""
        if not project_name or project_name == "(新建脚本)":
            self.current_model = ScriptModel()
            self._reload_action_list_ui()
            return
        project_dir = os.path.join(ScriptModel.SCRIPTS_ROOT, project_name)
        if os.path.isdir(project_dir):
            self.current_model = ScriptModel.load_from_project(project_dir)
            self._reload_action_list_ui()

    def _reload_action_list_ui(self):
        """根据 current_model 重建中间动作列表的 UI"""
        from PyQt6.QtWidgets import QListWidgetItem
        self.action_list.clear()
        for node in self.current_model.actions:
            list_item = QListWidgetItem()
            list_item.setData(Qt.ItemDataRole.UserRole, node.id)
            self.action_list.addItem(list_item)
        self._refresh_action_list_text()
        # 同步配置状态（不再同步 guard_check，已移入脚本配置面板）
        # 默认显示脚本全局配置
        self._show_script_config()

    def _on_actions_reordered(self):
        """拖拽排序完成后，同步 model.actions 顺序"""
        # 按 QListWidget 中 item 的视觉顺序重排 model.actions
        id_order = []
        for i in range(self.action_list.count()):
            item = self.action_list.item(i)
            id_order.append(item.data(Qt.ItemDataRole.UserRole))
        
        id_to_node = {n.id: n for n in self.current_model.actions}
        self.current_model.actions = [id_to_node[nid] for nid in id_order if nid in id_to_node]
        self._refresh_action_list_text()  # 刷新编号

    def on_recorded_click(self, device_id: str, x: int, y: int):
        """主窗口拦截点击后，调用的录制钩子（异步执行，避免阻塞 UI）"""
        # 启动后台线程执行 ADB 截图 + 点击，截图保存到项目 Temp 目录
        worker = _RecordClickWorker(
            device_id, x, y,
            temp_dir=self.current_model.temp_dir,
            parent=self
        )
        worker.finished.connect(self._on_record_click_done)
        # 保持引用防止被 GC 回收
        if not hasattr(self, '_record_workers'):
            self._record_workers = []
        self._record_workers.append(worker)
        worker.finished.connect(lambda: self._record_workers.remove(worker))
        worker.start()
        
    def _on_record_click_done(self, snapshot_name: str, x: int, y: int, timestamp: float):
        """后台录制线程完成后的回调，在主线程安全地更新 UI"""
        # 1. 生成隐式等待（计算自上次点击的时间差）
        if self.last_record_time > 0:
            diff = round(timestamp - self.last_record_time, 1)
            if diff > 0.5:
                sleep_node = ActionNode("sleep", {"seconds": diff})
                self.current_model.add_action(sleep_node)
                self._add_node_to_ui_list(sleep_node)
                
        # 2. 生成点击指令，并绑定快照证据
        tap_node = ActionNode("tap", {"x": x, "y": y, "snapshot": snapshot_name})
        self.current_model.add_action(tap_node)
        self._add_node_to_ui_list(tap_node)
        
        self.last_record_time = timestamp

    def _refresh_action_list_text(self):
        """遍历动作列表，根据内部参数更新显示的文本"""
        for i in range(self.action_list.count()):
            item = self.action_list.item(i)
            node_id = item.data(Qt.ItemDataRole.UserRole)
            node = next((n for n in self.current_model.actions if n.id == node_id), None)
            if not node: continue
            
            # 显示文本生成规则
            text = "未知指令"
            if node.type == "tap":
                text = f"🖱 点击坐标 [X:{node.params.get('x',0)}, Y:{node.params.get('y',0)}]"
            elif node.type == "sleep":
                text = f"⏱ 等待 [{node.params.get('seconds',0.0)}] 秒"
            elif node.type == "find_and_tap":
                _raw = os.path.basename(node.params.get('template', ''))
                target = _raw.split('@')[0].rsplit('.', 1)[0] if _raw else '未选择'
                text = f"🔍 寻找图片并点击 [{target}]"
            elif node.type == "wait_image":
                _raw = os.path.basename(node.params.get('template', ''))
                target = _raw.split('@')[0].rsplit('.', 1)[0] if _raw else '未选择'
                timeout_sec = node.params.get('timeout', 0)
                text = f"🔍 等待图片出现 [{target}] 超时{timeout_sec}s"
            elif node.type == "swipe":
                x1, y1 = node.params.get('x1', 0), node.params.get('y1', 0)
                x2, y2 = node.params.get('x2', 0), node.params.get('y2', 0)
                text = f"👆 滑动 ({x1},{y1})→({x2},{y2})"
            elif node.type == "loop_start":
                text = f"🔄 循环开始"
            elif node.type == "loop_end":
                text = f"🔚 循环结束"
                
            item.setText(f"{i+1}. {text}")

    def _show_script_config(self):
        """在右侧属性面板展示脚本全局配置"""
        from PyQt6.QtWidgets import QFormLayout, QSpinBox, QLineEdit

        widget = QWidget()
        layout = QFormLayout(widget)
        layout.addRow(QLabel("📋 脚本全局配置"))

        # 防卡死开关
        guard_check = QCheckBox("开启防卡死 (自动关弹窗)")
        guard_check.setChecked(self.current_model.config.popup_guard)
        guard_check.toggled.connect(
            lambda v: setattr(self.current_model.config, 'popup_guard', v)
        )
        layout.addRow(guard_check)

        # 守卫图库目录
        edit_guard_dir = QLineEdit(self.current_model.config.guard_dir)
        edit_guard_dir.textChanged.connect(
            lambda v: setattr(self.current_model.config, 'guard_dir', v)
        )
        layout.addRow("守卫图库目录:", edit_guard_dir)

        # 连续失败多少次后触发守卫
        spin_fails = QSpinBox()
        spin_fails.setRange(1, 50)
        spin_fails.setValue(self.current_model.config.guard_trigger_fails)
        spin_fails.valueChanged.connect(
            lambda v: setattr(self.current_model.config, 'guard_trigger_fails', v)
        )
        layout.addRow("失败触发次数:", spin_fails)

        # 分辨率检测开关
        check_res = QCheckBox("启动时检测分辨率一致性")
        check_res.setChecked(self.current_model.config.check_resolution)
        check_res.toggled.connect(
            lambda v: setattr(self.current_model.config, 'check_resolution', v)
        )
        layout.addRow(check_res)

        # 分辨率（只读显示）
        res_label = QLabel(self.current_model.config.resolution or "未设置")
        layout.addRow("适配分辨率:", res_label)

        # 替换右侧面板
        while self.props_stack.count() > 1:
            w = self.props_stack.widget(1)
            self.props_stack.removeWidget(w)
            w.deleteLater()

        self.props_stack.addWidget(widget)
        self.props_stack.setCurrentIndex(1)

    def _on_action_selected(self, row: int):
        """选中某个流水线动作时，右侧属性面版切换为对应编辑器"""
        if row < 0:
            self._show_script_config()  # 无选中时显示脚本配置
            return
            
        item = self.action_list.item(row)
        node_id = item.data(Qt.ItemDataRole.UserRole)
        node = next((n for n in self.current_model.actions if n.id == node_id), None)
        
        if not node:
            return

        # 动态创建针对该节点的表单 UI
        props_widget = self._create_props_widget(node)
        
        # 清除之前的表单（除了第 0 个默认占位符）
        while self.props_stack.count() > 1:
            widget = self.props_stack.widget(1)
            self.props_stack.removeWidget(widget)
            widget.deleteLater()
            
        self.props_stack.addWidget(props_widget)
        self.props_stack.setCurrentIndex(1)

    def _create_props_widget(self, node) -> QWidget:
        """根据 ActionNode 类型动态生成参数配置面板"""
        from PyQt6.QtWidgets import QFormLayout, QSpinBox, QDoubleSpinBox, QLineEdit, QComboBox

        widget = QWidget()
        layout = QFormLayout(widget)
        
        # 内部更新回调，当 UI 控件值改变时更新数据模型并刷新列表名称
        def update_param(key, value):
            node.params[key] = value
            self._refresh_action_list_text()

        if node.type == "tap":
            spin_x = QSpinBox()
            spin_x.setRange(0, 4000)
            spin_x.setValue(node.params.get("x", 0))
            spin_x.valueChanged.connect(lambda v: update_param("x", v))
            
            spin_y = QSpinBox()
            spin_y.setRange(0, 4000)
            spin_y.setValue(node.params.get("y", 0))
            spin_y.valueChanged.connect(lambda v: update_param("y", v))
            
            layout.addRow("点击 X 坐标:", spin_x)
            layout.addRow("点击 Y 坐标:", spin_y)
            
            if "snapshot" in node.params:
                up_btn = QPushButton("✨ 升级为【找图并点击】")
                up_btn.setStyleSheet("color: white; background-color: #f39c12; font-weight: bold;")
                up_btn.clicked.connect(lambda: self._upgrade_to_find_and_tap(node))
                layout.addRow(up_btn)
            
            # 测试按钮：立即执行一次点击
            test_btn = QPushButton("🧪 测试点击")
            test_btn.setToolTip("在当前设备上执行一次点击")
            def _test_tap():
                import threading
                from adb_utils import tap as adb_tap
                main_win = self.window()
                device_id = main_win.device_combo.currentText() if hasattr(main_win, 'device_combo') else ''
                if device_id:
                    threading.Thread(target=adb_tap, args=(device_id, node.params.get('x',0), node.params.get('y',0)), daemon=True).start()
                    if hasattr(main_win, '_append_log'):
                        main_win._append_log(f"🧪 测试点击 ({node.params.get('x',0)}, {node.params.get('y',0)})")
            test_btn.clicked.connect(_test_tap)
            layout.addRow(test_btn)
            
        elif node.type == "sleep":
            spin_sec = QDoubleSpinBox()
            spin_sec.setRange(0.1, 3600.0)
            spin_sec.setSuffix(" 秒")
            spin_sec.setValue(node.params.get("seconds", 1.0))
            spin_sec.valueChanged.connect(lambda v: update_param("seconds", v))
            
            layout.addRow("等待时长:", spin_sec)
            
        elif node.type == "swipe":
            spin_x1 = QSpinBox(); spin_x1.setRange(0, 4000)
            spin_x1.setValue(node.params.get("x1", 0))
            spin_x1.valueChanged.connect(lambda v: update_param("x1", v))
            spin_y1 = QSpinBox(); spin_y1.setRange(0, 4000)
            spin_y1.setValue(node.params.get("y1", 0))
            spin_y1.valueChanged.connect(lambda v: update_param("y1", v))
            spin_x2 = QSpinBox(); spin_x2.setRange(0, 4000)
            spin_x2.setValue(node.params.get("x2", 0))
            spin_x2.valueChanged.connect(lambda v: update_param("x2", v))
            spin_y2 = QSpinBox(); spin_y2.setRange(0, 4000)
            spin_y2.setValue(node.params.get("y2", 0))
            spin_y2.valueChanged.connect(lambda v: update_param("y2", v))
            spin_dur = QSpinBox(); spin_dur.setRange(50, 5000)
            spin_dur.setSuffix(" ms")
            spin_dur.setValue(node.params.get("duration", 300))
            spin_dur.valueChanged.connect(lambda v: update_param("duration", v))
            
            layout.addRow("起点 X:", spin_x1)
            layout.addRow("起点 Y:", spin_y1)
            layout.addRow("终点 X:", spin_x2)
            layout.addRow("终点 Y:", spin_y2)
            layout.addRow("滑动时长:", spin_dur)

        elif node.type == "find_and_tap":
            import template_meta
            
            # 模板路径显示
            _raw_tpl = node.params.get("template", "")
            edit_template = QLineEdit(_raw_tpl)
            
            # 偏移量编辑（先创建控件，供模板变更回调引用）
            spin_ox = QSpinBox()
            spin_ox.setRange(-2000, 2000)
            spin_ox.setValue(node.params.get("offset_x", 0))
            spin_oy = QSpinBox()
            spin_oy.setRange(-2000, 2000)
            spin_oy.setValue(node.params.get("offset_y", 0))
            
            # 模板路径变更时自动从 meta.json 加载偏移量
            def _on_template_changed(text):
                update_param("template", text)
                tpl_name = os.path.basename(text)
                if tpl_name:
                    meta = template_meta.get(self.current_model.pictures_dir, tpl_name)
                    if meta:
                        # 用 meta.json 的值更新 spinbox（不触发写回）
                        spin_ox.blockSignals(True)
                        spin_oy.blockSignals(True)
                        spin_ox.setValue(meta.get("offset_x", 0))
                        spin_oy.setValue(meta.get("offset_y", 0))
                        update_param("offset_x", meta.get("offset_x", 0))
                        update_param("offset_y", meta.get("offset_y", 0))
                        spin_ox.blockSignals(False)
                        spin_oy.blockSignals(False)
            edit_template.textChanged.connect(_on_template_changed)
            
            # 偏移量变更时同步写回 meta.json
            def _on_offset_changed():
                update_param("offset_x", spin_ox.value())
                update_param("offset_y", spin_oy.value())
                tpl_name = os.path.basename(node.params.get("template", ""))
                if tpl_name:
                    template_meta.set_meta(
                        self.current_model.pictures_dir, tpl_name,
                        offset_x=spin_ox.value(), offset_y=spin_oy.value()
                    )
            spin_ox.valueChanged.connect(lambda v: _on_offset_changed())
            spin_oy.valueChanged.connect(lambda v: _on_offset_changed())
            
            # 浏览按钮
            browse_btn = QPushButton("📂 浏览")
            def _browse_template(et=edit_template):
                from PyQt6.QtWidgets import QFileDialog
                start_dir = self.current_model.pictures_dir
                if not os.path.isdir(start_dir):
                    from config import TARGETS_DIR
                    start_dir = TARGETS_DIR
                path, _ = QFileDialog.getOpenFileName(
                    self, "选择模板图片", start_dir, "图片文件 (*.png *.jpg *.bmp)"
                )
                if path:
                    et.setText(path)  # 触发 _on_template_changed 自动加载 meta
            browse_btn.clicked.connect(lambda _checked=False, et=edit_template: _browse_template(et))
            
            spin_thresh = QDoubleSpinBox()
            spin_thresh.setRange(0.5, 1.0)
            spin_thresh.setSingleStep(0.05)
            spin_thresh.setValue(node.params.get("threshold", 0.9))
            spin_thresh.valueChanged.connect(lambda v: update_param("threshold", v))
            
            spin_timeout = QDoubleSpinBox()
            spin_timeout.setRange(0.0, 300.0)
            spin_timeout.setSuffix(" 秒")
            spin_timeout.setValue(node.params.get("timeout", 3.0))
            spin_timeout.valueChanged.connect(lambda v: update_param("timeout", v))
            
            # 布局
            tpl_row = QHBoxLayout()
            tpl_row.addWidget(edit_template)
            tpl_row.addWidget(browse_btn)
            layout.addRow("目标图片:", tpl_row)
            layout.addRow("相似度阈值:", spin_thresh)
            layout.addRow("寻找超时:", spin_timeout)
            layout.addRow("点击偏移 X:", spin_ox)
            layout.addRow("点击偏移 Y:", spin_oy)
            
            # 测试按钮：执行一次找图并点击
            test_btn = QPushButton("🧪 测试找图点击")
            test_btn.setToolTip("截图一次并尝试匹配点击")
            def _test_find_and_tap():
                import threading
                main_win = self.window()
                device_id = main_win.device_combo.currentText() if hasattr(main_win, 'device_combo') else ''
                if not device_id:
                    return
                def _do_test():
                    from adb_utils import screencap_to_memory, tap as adb_tap
                    from PyQt6.QtCore import QMetaObject, Qt as _Qt, Q_ARG
                    import image_engine
                    
                    # 线程安全的日志输出
                    def _safe_log(msg):
                        from PyQt6.QtCore import QTimer
                        QTimer.singleShot(0, lambda: main_win._append_log(msg) if hasattr(main_win, '_append_log') else None)
                    
                    tpl = node.params.get('template', '')
                    if not tpl:
                        return
                    # 解析模板路径
                    tpl_path = tpl
                    if not os.path.exists(tpl_path):
                        tpl_path = os.path.join(self.current_model.pictures_dir, tpl)
                    tpl_dir = os.path.dirname(tpl_path) or '.'
                    loaded = image_engine.load_templates(tpl_dir)
                    target_name = os.path.splitext(os.path.basename(tpl_path))[0]
                    target = [t for t in loaded if t[0] == target_name]
                    if not target:
                        _safe_log(f"🧪 测试失败：未找到模板 [{tpl}]")
                        return
                    img = screencap_to_memory(device_id)
                    if img is None:
                        _safe_log("🧪 测试失败：截图失败")
                        return
                    th = node.params.get('threshold', 0.9)
                    matches = image_engine.match_all(img, target, th)
                    if matches:
                        name, cx, cy, score = matches[0]
                        ox = node.params.get('offset_x', 0)
                        oy = node.params.get('offset_y', 0)
                        final_x, final_y = cx + ox, cy + oy
                        adb_tap(device_id, final_x, final_y)
                        _safe_log(f"🧪 测试成功：匹配 {score:.2f}，点击 ({final_x}, {final_y})")
                    else:
                        _safe_log("🧪 测试失败：未匹配到图片")
                threading.Thread(target=_do_test, daemon=True).start()
            test_btn.clicked.connect(_test_find_and_tap)
            layout.addRow(test_btn)
            
        elif node.type == "wait_image":
            edit_template = QLineEdit(node.params.get("template", ""))
            edit_template.textChanged.connect(lambda text: update_param("template", text))
            
            # 浏览按钮
            browse_btn2 = QPushButton("📂 浏览")
            def _browse_wait_tpl(et=edit_template):
                from PyQt6.QtWidgets import QFileDialog
                start_dir = self.current_model.pictures_dir
                if not os.path.isdir(start_dir):
                    from config import TARGETS_DIR
                    start_dir = TARGETS_DIR
                path, _ = QFileDialog.getOpenFileName(
                    self, "选择模板图片", start_dir, "图片文件 (*.png *.jpg *.bmp)"
                )
                if path:
                    et.setText(path)
            browse_btn2.clicked.connect(lambda _checked=False, et=edit_template: _browse_wait_tpl(et))
            
            spin_timeout = QDoubleSpinBox()
            spin_timeout.setRange(0.0, 3600.0)
            spin_timeout.setSuffix(" 秒")
            spin_timeout.setValue(node.params.get("timeout", 30.0))
            spin_timeout.valueChanged.connect(lambda v: update_param("timeout", v))
            
            combo_fail = QComboBox()
            combo_fail.addItems(["abort", "continue"])
            combo_fail.setCurrentText(node.params.get("action_on_fail", "abort"))
            combo_fail.currentTextChanged.connect(lambda text: update_param("action_on_fail", text))
            
            tpl_row2 = QHBoxLayout()
            tpl_row2.addWidget(edit_template)
            tpl_row2.addWidget(browse_btn2)
            layout.addRow("目标图片:", tpl_row2)
            layout.addRow("超时判断时长:", spin_timeout)
            layout.addRow("超时后操作:", combo_fail)
            
        else:
            layout.addRow(QLabel("暂无参数属性"))

        # 下方可追加全局操作，比如删除该节点
        del_btn = QPushButton("🗑 删除此指令")
        del_btn.setObjectName("dangerBtn")
        del_btn.clicked.connect(lambda: self._delete_current_action(node.id))
        layout.addRow(del_btn)

        return widget
        
    def _upgrade_to_find_and_tap(self, node):
        """将 tap 升级为 find_and_tap，自动计算点击偏移量"""
        from PyQt6.QtWidgets import QMessageBox, QDialog, QVBoxLayout, QLabel
        from PyQt6.QtGui import QImage
        from gui.widgets import ScreenshotWidget
        
        snapshot_path = node.params.get("snapshot")
        if not snapshot_path or not os.path.exists(snapshot_path):
            QMessageBox.warning(self, "错误", "未找到该指令的历史快照图片，无法升级。")
            return
        
        # 原始点击坐标
        click_x = node.params.get("x", 0)
        click_y = node.params.get("y", 0)
        
        dlg = QDialog(self)
        dlg.setWindowTitle("框选找图目标区域（红色十字 = 原始点击位置）")
        dlg.resize(1000, 600)
        
        vl = QVBoxLayout(dlg)
        hint = QLabel("请在画面中拖拽框选特征目标区域。框选后保存，系统将自动计算点击偏移量。")
        hint.setStyleSheet("color: #aaa; padding: 4px;")
        vl.addWidget(hint)
        
        sw = ScreenshotWidget()
        sw.custom_save_dir = self.current_model.pictures_dir
        # 传入干净原图（裁切不含标记），十字准心仅在 paintEvent 中叠加
        sw.update_screenshot(QImage(snapshot_path))
        sw._click_marker = (click_x, click_y)  # paintEvent 会读取此属性绘制十字
        vl.addWidget(sw)
        
        # 捕获框选区域坐标，用于计算偏移量
        region_info = {}
        def on_region(rx, ry, rw, rh):
            region_info['rx'] = rx
            region_info['ry'] = ry
            region_info['rw'] = rw
            region_info['rh'] = rh
        sw.region_selected.connect(on_region)
        
        # 模板保存完成回调
        def on_template_saved(save_path):
            # 计算偏移量 = 原始点击位置 - 模板中心
            if region_info:
                center_x = region_info['rx'] + region_info['rw'] // 2
                center_y = region_info['ry'] + region_info['rh'] // 2
                offset_x = click_x - center_x
                offset_y = click_y - center_y
            else:
                offset_x, offset_y = 0, 0
            
            # 保存偏移量到 meta.json
            import template_meta
            tpl_filename = os.path.basename(save_path)
            template_meta.set_meta(
                self.current_model.pictures_dir, tpl_filename,
                offset_x=offset_x, offset_y=offset_y
            )
            
            node.type = "find_and_tap"
            node.params = {
                "template": save_path,
                "threshold": 0.9,
                "timeout": 3.0,
                "offset_x": offset_x,
                "offset_y": offset_y
            }
            self._refresh_action_list_text()
            
            current_row = self.action_list.currentRow()
            self._on_action_selected(current_row)
            dlg.accept()
            
        sw.template_saved.connect(on_template_saved)
        dlg.exec()

    def _delete_current_action(self, node_id: str):
        """删除当前选中的流水线任务"""
        self.current_model.remove_action(node_id)
        # 从 UI 列表移除
        for i in range(self.action_list.count()):
            item = self.action_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == node_id:
                self.action_list.takeItem(i)
                break
        # 刷新序号文本
        self._refresh_action_list_text()
        # 删除后如果列表仍有选中项，主动刷新右侧属性面板
        current_row = self.action_list.currentRow()
        if current_row >= 0:
            self._on_action_selected(current_row)
        else:
            self.props_stack.setCurrentIndex(0)

    # ================= 兼容层面方法 =================
    def get_runtime_config(self):
        """兼容层：返回空配置对象，已不再依赖 shop_bot 模块。"""
        return None

    def sync_to_runtime_config(self, config):
        pass
