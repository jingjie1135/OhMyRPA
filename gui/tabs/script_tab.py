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
    QSplitter, QListWidget, QTreeWidget, QTreeWidgetItem,
    QInputDialog
)

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
        from adb_utils import screencap_to_memory
        
        now = _time.time()
        snapshot_name = ""
        
        # 使用 ADB 无损截图保存到项目 Temp 目录（可选）
        if self.enable_snapshot:
            img = screencap_to_memory(self.device_id)
            if img is not None:
                os.makedirs(self.temp_dir, exist_ok=True)
                snapshot_name = os.path.join(self.temp_dir, f"step_{int(now)}.png")
                cv2.imencode('.png', img)[1].tofile(snapshot_name)
        
        # 注意：不再执行 tap()，因为用户在预览区的点击已通过 Scrcpy 实时送达设备
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
        # 外层用 QStackedWidget 支持图库页面切换
        from PyQt6.QtWidgets import QStackedWidget
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        self._page_stack = QStackedWidget()
        outer_layout.addWidget(self._page_stack)

        # 主编辑器页面
        editor_page = QWidget()
        main_layout = QVBoxLayout(editor_page)
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
        # 减少缩进量，避免文字被截断
        self.toolbox_tree.setIndentation(12)
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
        splitter.setSizes([230, 390, 250])
        
        main_layout.addWidget(splitter, stretch=1)

        # 将编辑器页面加入 page_stack
        self._page_stack.addWidget(editor_page)

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
        from gui.action_props import ACTION_REGISTRY
        # 按分类分组（脚本 Tab 不需要多图点击）
        categories = {}
        for type_key, (icon, display_name, category) in ACTION_REGISTRY.items():
            if type_key == "multi_match":
                continue
            if category not in categories:
                categories[category] = []
            categories[category].append((type_key, icon, display_name))
        for cat_name, items in categories.items():
            cat = QTreeWidgetItem(self.toolbox_tree, [cat_name])
            for type_key, icon, display_name in items:
                QTreeWidgetItem(cat, [f"{icon} {display_name}"]).setData(
                    0, Qt.ItemDataRole.UserRole, type_key)
        self.toolbox_tree.expandAll()

    def _on_toolbox_double_clicked(self, item: QTreeWidgetItem, column: int):
        """双击左侧工具箱中的项，将其添加到中间流水线列表中"""
        action_type = item.data(0, Qt.ItemDataRole.UserRole)
        if not action_type:
            return  # 点击的是分类项

        # 常见初始参数模板
        default_params = {
            "tap": {"x": 0, "y": 0},
            "sleep": {"seconds": 1.0},
            "swipe": {"x1": 0, "y1": 0, "x2": 0, "y2": 0, "duration": 300},
            "find_and_tap": {"template": "", "threshold": 0.9, "timeout": 3.0},
            "wait_image": {"template": "", "timeout": 30.0, "action_on_fail": "abort"},
        }.get(action_type, {})

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
        import time
        self.last_record_time = time.time()  # 录制起始时间戳，用于计算第一次操作前的等待
        
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
        # 写入最后等待时间（使用 time.time 与 last_record_time 做差，与 _on_record_click_done 保持统一）
        if not self._recording_paused and self.last_record_time > 0:
            import time
            diff = round(time.time() - self.last_record_time, 1)
            if diff > 0.5:
                sleep_node = ActionNode(action_type="sleep", params={"seconds": diff})
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
    def _check_recording_resolution(self, device_id: str) -> bool:
        """
        录制前分辨率门禁检查：比对当前预览设备分辨率与脚本绑定分辨率。
        返回 True 表示通过，False 表示不匹配并已弹窗拦截。
        """
        script_res = getattr(self.current_model.config, 'resolution', None)
        if not script_res or script_res == "unknown":
            return True  # 脚本没有绑定分辨率，不拦截
        
        try:
            from adb_utils import get_resolution
            w, h = get_resolution(device_id)
            if w <= 0 or h <= 0:
                return True  # 无法获取当前设备分辨率，放行
            current_res = f"{w}x{h}"
        except Exception:
            return True  # 获取失败，不影响录制
        
        if current_res != script_res:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "分辨率不匹配 — 拒绝录制",
                f"当前预览设备 [{device_id}] 的分辨率为：{current_res}\n"
                f"脚本「{self.current_model.name}」绑定分辨率为：{script_res}\n\n"
                f"分辨率不一致将导致找图失败，请切换到匹配的设备后再录制。"
            )
            return False
        return True

    def on_recorded_swipe(self, device_id: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300, path: list = None):
        """记录滑动动作：如果有完整轨迹则保留完整轨迹用于高精度重放"""
        if self._recording_paused:
            return
        
        # 分辨率门禁检查
        if not self._check_recording_resolution(device_id):
            return
        
        # 最小间隔保护 1 秒
        import time
        now = time.time()
        if self.last_record_time > 0 and (now - self.last_record_time) < 1.0:
            main_win = self.window()
            if hasattr(main_win, '_append_log'):
                main_win._append_log("⚠️ 操作过快（<1s），已忽略。")
            return
        
        # 自动插入 sleep（使用 time.time 做差，与点击录制保持统一）
        if self.last_record_time > 0:
            diff = round(now - self.last_record_time, 1)
            if diff > 0.5:
                sleep_node = ActionNode(action_type="sleep", params={"seconds": diff})
                self.current_model.actions.append(sleep_node)
                from PyQt6.QtWidgets import QListWidgetItem
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, sleep_node.id)
                self.action_list.addItem(item)
        
        # 更新时间戳
        self.last_record_time = now
        
        # 创建 swipe 动作节点
        params = {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "duration": duration_ms}
        if path:
            params["path"] = path
            
        node = ActionNode(
            action_type="swipe",
            params=params
        )
        self.current_model.actions.append(node)
        from PyQt6.QtWidgets import QListWidgetItem
        list_item = QListWidgetItem()
        list_item.setData(Qt.ItemDataRole.UserRole, node.id)
        self.action_list.addItem(list_item)
        self._refresh_action_list_text()
        # 注意：不再执行后台 ADB swipe，因为用户的滑动已通过 Scrcpy 实时送达设备

    def on_recorded_system_action(self, action_type: str):
        """主窗口触发系统按钮后，调用的录制钩子"""
        if self._recording_paused:
            return
            
        import time
        now = time.time()
        
        # 最小间隔保护 1 秒
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
            
        # 插入系统按键动作
        node = ActionNode(action_type=action_type, params={})
        self.current_model.actions.append(node)
        from PyQt6.QtWidgets import QListWidgetItem
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, node.id)
        self.action_list.addItem(item)
        
        self._refresh_action_list_text()
        
        # 更新计时和状态
        self.last_record_time = time.time()
        self._record_elapsed_before_pause = 0
        self._record_timer.start()

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

        # 从主窗口获取当前预览区所属设备的真实分辨率
        main_win = self.window()
        device_id = getattr(main_win, 'device_combo', None)
        device_id = device_id.currentText() if device_id else ""
        
        resolution_tag = "unknown"
        if device_id:
            try:
                from adb_utils import get_resolution
                w, h = get_resolution(device_id)
                if w > 0 and h > 0:
                    resolution_tag = f"{w}x{h}"
            except Exception:
                pass
        
        # 弹窗确认分辨率绑定
        from PyQt6.QtWidgets import QMessageBox
        if resolution_tag == "unknown":
            QMessageBox.warning(self, "无法获取分辨率",
                "未检测到有效设备分辨率，请先连接设备并在顶部选择。")
            return
        
        reply = QMessageBox.question(
            self, "确认脚本分辨率",
            f"当前预览设备 [{device_id}] 的分辨率为：\n\n"
            f"    📐  {resolution_tag}\n\n"
            f"是否基于此分辨率创建脚本项目「{name}」？\n\n"
            f"⚠️ 注意：后续脚本执行时，设备分辨率必须与此一致，\n"
            f"否则将无法正常运行。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # 创建新模型并立即保存（创建目录结构）
        self.current_model = ScriptModel(name=name)
        self.current_model.project_dir = project_dir
        self.current_model.config.resolution = resolution_tag
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
        from gui.action_props import format_action_text
        for i in range(self.action_list.count()):
            item = self.action_list.item(i)
            node_id = item.data(Qt.ItemDataRole.UserRole)
            node = next((n for n in self.current_model.actions if n.id == node_id), None)
            if not node:
                continue
            item.setText(f"{i+1}. {format_action_text(node)}")

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
        """根据 ActionNode 类型动态生成参数配置面板（统一调用 action_props）"""
        from PyQt6.QtWidgets import QFormLayout, QVBoxLayout
        from gui.action_props import build_action_props, append_comment_row

        wrapper = QWidget()
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        form_widget = QWidget()
        layout = QFormLayout(form_widget)
        
        def update_param(key, value):
            node.params[key] = value
            self._refresh_action_list_text()

        # 构建上下文
        main_win = self.window()
        ctx = {
            "main_win": main_win,
            "pictures_dir": self.current_model.pictures_dir if self.current_model else "",
            "internalize_fn": self.current_model.internalize_image if self.current_model else None,
            "on_open_gallery": self._open_gallery,
        }
        
        # 统一分派构建
        built = build_action_props(layout, node, update_param, ctx)
        
        # script_tab 特有：点击坐标升级为找图点击
        if node.type == "tap" and "snapshot" in node.params:
            up_btn = QPushButton("✨ 升级为【找图点击】")
            up_btn.setStyleSheet("color: white; background-color: #f39c12; font-weight: bold;")
            up_btn.clicked.connect(lambda: self._upgrade_to_find_and_tap(node))
            layout.addRow(up_btn)
        
        if not built:
            layout.addRow(QLabel("暂无参数属性"))

        # 通用备注行
        append_comment_row(layout, node)

        # 删除按钮
        del_btn = QPushButton("🗑 删除此指令")
        del_btn.setObjectName("dangerBtn")
        del_btn.clicked.connect(lambda: self._delete_current_action(node.id))
        layout.addRow(del_btn)

        outer.addWidget(form_widget)
        outer.addStretch(1)  # 将内容推到顶部，防止均匀拉伸
        return wrapper

    def _open_gallery(self, node, mode="single", param_key="template"):
        """统一图库入口：在整个 Tab 区域显示图库
        
        Args:
            node: 当前 ActionNode
            mode: "single" 单选 / "multi" 多选
            param_key: 写回参数的键名
        """
        if not self.current_model:
            return
        
        from gui.template_gallery_dialog import TemplateGalleryWidget
        
        pictures_dir = self.current_model.pictures_dir
        # 防御性创建：确保 Pictures 目录存在（用户可能新建脚本后立即操作图库）
        os.makedirs(pictures_dir, exist_ok=True)
        
        # 构造当前模板列表
        if mode == "single":
            tpl_val = node.params.get(param_key, "")
            current_templates = [{"template": tpl_val}] if tpl_val else []
        else:
            current_templates = node.params.get(param_key, [])
        
        gallery = TemplateGalleryWidget(pictures_dir, current_templates, mode=mode, parent=self)
        
        # 绑定 ScreenshotWidget
        main_win = self.window()
        sw = getattr(main_win, 'screenshot_widget', None)
        if sw:
            gallery.bind_screenshot_widget(sw)
        
        prev_row = self.action_list.currentRow()
        
        idx = self._page_stack.addWidget(gallery)
        self._page_stack.setCurrentIndex(idx)
        
        def _on_gallery_closed(updated_templates):
            self._page_stack.setCurrentIndex(0)
            self._page_stack.removeWidget(gallery)
            gallery.deleteLater()
            
            if mode == "single":
                new_val = updated_templates[0].get("template", "") if updated_templates else ""
                old_val = node.params.get(param_key, "")
                if new_val != old_val:
                    node.params[param_key] = new_val
                    self.current_model.save()
                    if hasattr(main_win, '_append_log'):
                        main_win._append_log(f"📂 已选择模板: {new_val}")
            else:
                old_templates = node.params.get(param_key, [])
                changed = (len(updated_templates) != len(old_templates) or
                           any(u.get("template") != o.get("template")
                               for u, o in zip(updated_templates, old_templates)))
                if changed:
                    node.params[param_key] = updated_templates
                    self.current_model.save()
            
            # 刷新列表文本并恢复选中行
            self._refresh_action_list_text()
            if prev_row >= 0 and prev_row < self.action_list.count():
                self.action_list.setCurrentRow(prev_row)
        
        gallery.closed.connect(_on_gallery_closed)
        
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
        os.makedirs(self.current_model.pictures_dir, exist_ok=True)
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
                "template": os.path.basename(save_path),  # 只存文件名，与其他指令保持一致
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
        return None

    def sync_to_runtime_config(self, config):
        pass
