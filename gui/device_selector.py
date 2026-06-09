"""
设备批次选择器（嵌入式全屏组件）。

与 TemplateGalleryWidget 同模式：通过 QStackedWidget 切换，
覆盖整个 Tab 区域。用户在此配置多个设备批次，返回时
通过 closed 信号传回批次列表。
"""

import os
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QGroupBox, QCheckBox, QLineEdit,
    QMessageBox, QFrame, QSizePolicy, QButtonGroup,
)

from gui.constants import COLOR_DANGER, COLOR_SUCCESS, create_font
from emulator_manager import EmulatorManager, DeviceInfo


class _DeviceScanWorker(QThread):
    """后台扫描所有模拟器/真机设备，避免在 GUI 主线程同步阻塞。"""
    done = pyqtSignal(object)  # list[DeviceInfo]

    def run(self):
        try:
            devices = EmulatorManager.scan_all()
        except Exception:
            import logging
            logging.getLogger(__name__).debug("设备扫描失败", exc_info=True)
            devices = []
        self.done.emit(devices)


class DeviceSelectorWidget(QWidget):
    """
    设备批次管理全屏组件。

    信号:
        closed(list): 关闭时发出，携带更新后的批次列表。
            批次格式: [{"name": "批次1", "devices": [DeviceInfo.to_dict(), ...], "auto_close": True}, ...]
    """
    closed = pyqtSignal(list)

    def __init__(self, current_batches: list = None, parent=None):
        super().__init__(parent)
        self._batches = []  # 内部批次数据: [{"name": str, "devices": [DeviceInfo], "auto_close": bool}]
        self._available_devices: list[DeviceInfo] = []  # 扫描到的所有可用设备
        self._device_checkboxes: dict[str, QCheckBox] = {}  # key -> checkbox 映射
        self._selected_batch_index = -1  # 当前操作的目标批次

        # 从外部传入的已有批次配置
        if current_batches:
            for b in current_batches:
                devices = [DeviceInfo.from_dict(d) if isinstance(d, dict) else d
                           for d in b.get("devices", [])]
                self._batches.append({
                    "name": b.get("name", f"批次{len(self._batches)+1}"),
                    "devices": devices,
                    "auto_close": b.get("auto_close", True),
                })

        self._init_ui()
        # 延迟自动刷新设备列表
        QTimer.singleShot(200, self._refresh_devices)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 8, 8, 8)

        # 只有返回按钮的极简顶部（保留以便退出），因为确认保存已移至右侧
        top_bar = QHBoxLayout()
        title = QLabel("📱 设备批次管理")
        title.setFont(create_font(11, bold=True))
        top_bar.addWidget(title)
        top_bar.addStretch()
        back_btn = QPushButton("← 返回")
        back_btn.setFixedSize(70, 28)
        back_btn.clicked.connect(self._on_close)
        top_bar.addWidget(back_btn)
        layout.addLayout(top_bar)

        # 主内容区域：左右两栏
        main_hlayout = QHBoxLayout()
        
        # ==================== 左侧：可用设备池 ====================
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # 左侧顶部：筛选与刷新
        left_top_bar = QHBoxLayout()
        filter_label = QLabel("筛选:")
        left_top_bar.addWidget(filter_label)
        
        self.filter_btn_group = QButtonGroup(self)
        
        btn_all = QPushButton("全部")
        btn_all.setCheckable(True)
        btn_all.setChecked(True)
        btn_all.setFixedHeight(26)
        self.filter_btn_group.addButton(btn_all, 0)
        left_top_bar.addWidget(btn_all)
        
        btn_mumu = QPushButton("MuMu")
        btn_mumu.setCheckable(True)
        btn_mumu.setFixedHeight(26)
        self.filter_btn_group.addButton(btn_mumu, 1)
        left_top_bar.addWidget(btn_mumu)
        
        btn_ld = QPushButton("雷电")
        btn_ld.setCheckable(True)
        btn_ld.setFixedHeight(26)
        self.filter_btn_group.addButton(btn_ld, 2)
        left_top_bar.addWidget(btn_ld)
        
        btn_phone = QPushButton("手机")
        btn_phone.setCheckable(True)
        btn_phone.setFixedHeight(26)
        self.filter_btn_group.addButton(btn_phone, 3)
        left_top_bar.addWidget(btn_phone)
        
        self.filter_btn_group.buttonClicked.connect(lambda _: self._rebuild_devices_ui())
        left_top_bar.addStretch()
        
        refresh_btn = QPushButton("🔄")
        refresh_btn.setToolTip("刷新设备")
        refresh_btn.setFixedSize(30, 26)
        refresh_btn.clicked.connect(self._refresh_devices)
        left_top_bar.addWidget(refresh_btn)
        
        left_layout.addLayout(left_top_bar)
        
        # 左侧列表滚动区域
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setStyleSheet("QScrollArea { border: 1px solid #ddd; border-radius: 4px; background: transparent; }")
        
        left_scroll_content = QWidget()
        self._devices_container = QVBoxLayout(left_scroll_content)
        self._devices_container.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._devices_container.setSpacing(6)
        left_scroll.setWidget(left_scroll_content)
        
        hint = QLabel("💡 提示：选中右侧的某个批次后，从列表勾选设备。")
        hint.setStyleSheet("color: #666; font-size: 11px;")
        hint.setWordWrap(True)
        left_layout.addWidget(hint)
        left_layout.addWidget(left_scroll)
        
        main_hlayout.addWidget(left_widget, stretch=10)

        # ==================== 右侧：批次信息 ====================
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # 右侧顶部：添加、保存
        right_top_bar = QHBoxLayout()
        add_batch_btn = QPushButton("+ 添加批次")
        add_batch_btn.setFixedHeight(28)
        add_batch_btn.clicked.connect(self._add_batch)
        right_top_bar.addWidget(add_batch_btn)
        
        right_top_bar.addStretch()
        
        confirm_btn = QPushButton("✓ 确认保存")
        confirm_btn.setFixedHeight(28)
        confirm_btn.setFixedWidth(100)
        confirm_btn.setStyleSheet(f"background: {COLOR_SUCCESS}; color: white; border: none; border-radius: 4px;")
        confirm_btn.clicked.connect(self._on_close)
        right_top_bar.addWidget(confirm_btn)
        
        right_layout.addLayout(right_top_bar)
        
        # 右侧批次滚动区域
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setStyleSheet("QScrollArea { border: 1px solid #ddd; border-radius: 4px; background: transparent; }")
        
        right_scroll_content = QWidget()
        self._batches_container = QVBoxLayout(right_scroll_content)
        self._batches_container.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._batches_container.setSpacing(8)
        right_scroll.setWidget(right_scroll_content)
        right_layout.addWidget(right_scroll)
        
        main_hlayout.addWidget(right_widget, stretch=12)

        layout.addLayout(main_hlayout)

        # 初始渲染
        self._rebuild_batches_ui()

    # =================== 批次管理 ===================

    def _add_batch(self):
        """添加新批次"""
        name = f"批次{len(self._batches) + 1}"
        self._batches.append({"name": name, "devices": [], "auto_close": True})
        self._selected_batch_index = len(self._batches) - 1
        self._rebuild_batches_ui()

    def _remove_batch(self, index):
        """删除指定批次"""
        if 0 <= index < len(self._batches):
            self._batches.pop(index)
            if self._selected_batch_index >= len(self._batches):
                self._selected_batch_index = len(self._batches) - 1
            self._rebuild_batches_ui()

    def _select_batch(self, index):
        """选中批次（用于将设备添加到此批次）"""
        self._selected_batch_index = index
        self._rebuild_batches_ui()

    def _rebuild_batches_ui(self):
        """重建批次区域 UI"""
        # 清空
        while self._batches_container.count():
            item = self._batches_container.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not self._batches:
            empty = QLabel("暂无批次，请点击下方「+ 添加批次」创建")
            empty.setStyleSheet("color: #888; padding: 12px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._batches_container.addWidget(empty)
            return

        for i, batch in enumerate(self._batches):
            is_selected = (i == self._selected_batch_index)
            group = self._create_batch_widget(i, batch, is_selected)
            self._batches_container.addWidget(group)

        # 同步更新设备池中的勾选状态
        self._update_device_pool_checks()

    def _create_batch_widget(self, index, batch, is_selected):
        """创建单个批次的 UI 组件"""
        border_color = COLOR_SUCCESS if is_selected else "#444"
        group = QGroupBox()
        group.setStyleSheet(f"""
            QGroupBox {{
                border: 2px solid {border_color};
                border-radius: 6px;
                margin-top: 0px;
                padding: 8px;
            }}
        """)
        group.setCursor(Qt.CursorShape.PointingHandCursor)
        # 点击选中此批次
        group.mousePressEvent = lambda e, idx=index: self._select_batch(idx)

        v_layout = QVBoxLayout(group)
        v_layout.setSpacing(4)

        # 标题行
        title_row = QHBoxLayout()

        # 批次名称（可编辑）
        name_edit = QLineEdit(batch["name"])
        name_edit.setFont(create_font(9, bold=True))
        name_edit.setMaximumWidth(150)
        name_edit.setStyleSheet("border: 1px solid #555; border-radius: 3px; padding: 2px 4px;")
        name_edit.textChanged.connect(lambda t, idx=index: self._on_batch_name_changed(idx, t))
        title_row.addWidget(name_edit)

        device_count = len(batch["devices"])
        count_label = QLabel(f"（{device_count} 台设备）")
        count_label.setStyleSheet("color: #888;")
        title_row.addWidget(count_label)

        if is_selected:
            sel_label = QLabel("◉ 当前操作目标")
            sel_label.setStyleSheet(f"color: {COLOR_SUCCESS}; font-weight: bold; font-size: 11px;")
            title_row.addWidget(sel_label)

        title_row.addStretch()

        # 自动关闭选项
        auto_close_cb = QCheckBox("执行后关闭")
        auto_close_cb.setChecked(batch.get("auto_close", True))
        auto_close_cb.setToolTip("批次执行完毕后自动关闭这些模拟器实例")
        auto_close_cb.toggled.connect(lambda v, idx=index: self._on_auto_close_changed(idx, v))
        title_row.addWidget(auto_close_cb)

        # 删除按钮
        del_btn = QPushButton("🗑")
        del_btn.setFixedSize(28, 28)
        del_btn.setToolTip("删除此批次")
        del_btn.setStyleSheet(f"color: {COLOR_DANGER};")
        del_btn.clicked.connect(lambda _, idx=index: self._remove_batch(idx))
        title_row.addWidget(del_btn)

        v_layout.addLayout(title_row)

        # 设备列表
        if batch["devices"]:
            for j, dev in enumerate(batch["devices"]):
                dev_row = QHBoxLayout()
                icon = "🟢" if dev.running else "🔴"
                type_icon = {"ldplayer": "📱", "mumu": "📱", "phone": "📲"}.get(dev.device_type, "❓")
                dev_label = QLabel(f"  {type_icon} {icon} {dev.name}")
                dev_label.setStyleSheet("font-size: 12px;")
                dev_row.addWidget(dev_label)

                if dev.device_id:
                    addr_label = QLabel(dev.device_id)
                    addr_label.setStyleSheet("color: #666; font-size: 11px;")
                    dev_row.addWidget(addr_label)

                dev_row.addStretch()

                # 移除按钮
                rm_btn = QPushButton("✕")
                rm_btn.setFixedSize(22, 22)
                rm_btn.setStyleSheet(f"color: {COLOR_DANGER}; font-size: 10px;")
                rm_btn.setToolTip("从批次中移除")
                rm_btn.clicked.connect(lambda _, bi=index, di=j: self._remove_device_from_batch(bi, di))
                dev_row.addWidget(rm_btn)

                v_layout.addLayout(dev_row)
        else:
            empty = QLabel("  （空批次，请从下方设备池勾选添加）")
            empty.setStyleSheet("color: #777; font-size: 11px;")
            v_layout.addWidget(empty)

        return group

    def _on_batch_name_changed(self, index, name):
        if 0 <= index < len(self._batches):
            self._batches[index]["name"] = name

    def _on_auto_close_changed(self, index, value):
        if 0 <= index < len(self._batches):
            self._batches[index]["auto_close"] = value

    def _remove_device_from_batch(self, batch_index, device_index):
        """从批次中移除设备"""
        if 0 <= batch_index < len(self._batches):
            devices = self._batches[batch_index]["devices"]
            if 0 <= device_index < len(devices):
                devices.pop(device_index)
                self._rebuild_batches_ui()

    # =================== 设备池 ===================

    def _refresh_devices(self):
        """后台刷新设备列表（扫描在 QThread 中执行，不阻塞 UI）。"""
        worker = getattr(self, '_scan_worker', None)
        if worker is not None:
            try:
                if worker.isRunning():
                    return  # 已有扫描进行中，忽略重复触发
            except RuntimeError:
                self._scan_worker = None

        # 占位提示
        while self._devices_container.count():
            item = self._devices_container.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._device_checkboxes.clear()
        scanning = QLabel("正在扫描设备...")
        scanning.setStyleSheet("color: #888; padding: 8px;")
        self._devices_container.addWidget(scanning)

        worker = _DeviceScanWorker(parent=self)
        worker.done.connect(self._on_devices_scanned)
        worker.finished.connect(lambda: setattr(self, '_scan_worker', None))
        worker.finished.connect(worker.deleteLater)
        self._scan_worker = worker
        worker.start()

    def _on_devices_scanned(self, devices):
        """扫描完成回调（主线程）：更新设备池并重建 UI。"""
        self._available_devices = devices or []
        self._rebuild_devices_ui()

    def _rebuild_devices_ui(self):
        """重建可用设备池 UI"""
        # 清空
        while self._devices_container.count():
            item = self._devices_container.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        self._device_checkboxes.clear()

        if not self._available_devices:
            empty = QLabel("未发现任何设备。请确保模拟器已安装或手机已连接。")
            empty.setStyleSheet("color: #888; padding: 8px;")
            self._devices_container.addWidget(empty)
            return

        # 获取筛选条件
        filter_id = self.filter_btn_group.checkedId()
        filter_type = None
        if filter_id == 1:
            filter_type = "mumu"
        elif filter_id == 2:
            filter_type = "ldplayer"
        elif filter_id == 3:
            filter_type = "phone"

        # 按设备类型分组
        groups = {}
        for dev in self._available_devices:
            if filter_type and dev.device_type != filter_type:
                continue

            group_name = {
                "ldplayer": "🎮 雷电模拟器",
                "mumu": "🎮 MuMu模拟器",
                "phone": "📲 手机设备",
            }.get(dev.device_type, "❓ 其他")
            groups.setdefault(group_name, []).append(dev)

        for group_name, devices in groups.items():
            # 分组标题
            group_label = QLabel(f"── {group_name} ──")
            group_label.setFont(create_font(9, bold=True))
            group_label.setStyleSheet("color: #aaa; margin-top: 4px;")
            self._devices_container.addWidget(group_label)

            for dev in devices:
                self._add_device_checkbox(dev)

        self._update_device_pool_checks()

    def _add_device_checkbox(self, dev: DeviceInfo):
        """为单个设备创建勾选行"""
        row = QHBoxLayout()
        row_widget = QWidget()
        row_widget.setLayout(row)

        # 生成唯一 key
        key = f"{dev.device_type}_{dev.index}_{dev.name}"

        cb = QCheckBox()
        cb.setChecked(False)
        cb.toggled.connect(lambda checked, d=dev: self._on_device_toggled(d, checked))
        self._device_checkboxes[key] = cb
        row.addWidget(cb)

        icon = "🟢" if dev.running else "🔴"
        label = QLabel(f"{icon} {dev.name}")
        label.setFont(create_font())
        row.addWidget(label)

        if dev.device_id:
            addr = QLabel(f"  {dev.device_id}")
            addr.setStyleSheet("color: #666; font-size: 11px;")
            row.addWidget(addr)

        row.addStretch()
        self._devices_container.addWidget(row_widget)

    def _on_device_toggled(self, dev: DeviceInfo, checked: bool):
        """设备池中勾选/取消勾选设备"""
        if self._selected_batch_index < 0 or self._selected_batch_index >= len(self._batches):
            if checked:
                QMessageBox.information(self, "提示", "请先选中一个批次（点击批次区域），再勾选设备添加。")
                # 取消勾选
                key = f"{dev.device_type}_{dev.index}_{dev.name}"
                cb = self._device_checkboxes.get(key)
                if cb:
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)
            return

        batch = self._batches[self._selected_batch_index]
        if checked:
            # 检测是否已在当前批次
            if not any(d.name == dev.name and d.device_type == dev.device_type for d in batch["devices"]):
                batch["devices"].append(dev)
        else:
            batch["devices"] = [d for d in batch["devices"]
                                if not (d.name == dev.name and d.device_type == dev.device_type)]

        self._rebuild_batches_ui()

    def _update_device_pool_checks(self):
        """根据当前选中批次的设备列表，同步设备池中的勾选状态"""
        # 收集当前选中批次中的设备 key 集合
        selected_keys = set()
        if 0 <= self._selected_batch_index < len(self._batches):
            for dev in self._batches[self._selected_batch_index]["devices"]:
                key = f"{dev.device_type}_{dev.index}_{dev.name}"
                selected_keys.add(key)

        for key, cb in self._device_checkboxes.items():
            cb.blockSignals(True)
            cb.setChecked(key in selected_keys)
            cb.blockSignals(False)

    # =================== 关闭/返回 ===================

    def _on_close(self):
        """构建批次列表并发出 closed 信号"""
        result = []
        for batch in self._batches:
            result.append({
                "name": batch["name"],
                "devices": [d.to_dict() for d in batch["devices"]],
                "auto_close": batch.get("auto_close", True),
            })
        self.closed.emit(result)
