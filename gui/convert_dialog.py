"""
流水线 → 多模板匹配循环 两步式转换向导。

Step 1: 区域筛选
    - 左侧显示所有非 sleep 步骤列表
    - 选中步骤后右侧显示其录制快照
    - 用户在截图上框选矩形区域 → 筛选出点击坐标落在区域内的步骤

Step 2: 多区域批量抠图
    - 显示截图 + 被筛选步骤的点击位置标记
    - 用户框选多个矩形区域（每个区域 = 一个物品图标）
    - 程序自动判断每个步骤的点击坐标落在哪个区域
    - 自动裁切模板 + 计算偏移量
    - 图像相似度去重
"""

import os
import cv2
import numpy as np

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QImage, QIcon
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QLabel,
    QDialogButtonBox, QGroupBox, QMessageBox,
    QSplitter, QStackedWidget, QWidget,
)

from script_model import ScriptModel, ActionNode
from gui.multi_region_widget import MultiRegionWidget


def _qimage_to_cv(q_img: QImage):
    """QImage → OpenCV BGR numpy 数组"""
    if q_img is None or q_img.isNull():
        return None
    # 转 RGB888 格式
    q_img = q_img.convertToFormat(QImage.Format.Format_RGB888)
    w, h = q_img.width(), q_img.height()
    ptr = q_img.bits()
    ptr.setsize(q_img.sizeInBytes())
    arr = np.array(ptr).reshape(h, w, 3)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


# 去重扩边像素数（每边）
_DEDUP_PAD = 15


def _is_duplicate_template(crop, existing_padded, threshold=0.90):
    """
    使用 matchTemplate 判断 crop 是否与 existing 是同一物品。
    将 crop 作为模板在 existing 的扩边区域中滑动搜索，
    天然容忍手动框选导致的几像素位移偏差。
    
    Args:
        crop: 当前裁切的模板图（BGR）
        existing_padded: 已保存模板的扩边区域图（BGR，比 crop 每边多 _DEDUP_PAD 像素）
        threshold: 匹配阈值，≥ 此值判定为重复
    """
    # 确保模板不大于搜索区域
    if (crop.shape[0] > existing_padded.shape[0] or
        crop.shape[1] > existing_padded.shape[1]):
        # 反过来搜索
        crop, existing_padded = existing_padded, crop
        if (crop.shape[0] > existing_padded.shape[0] or
            crop.shape[1] > existing_padded.shape[1]):
            return False
    
    result = cv2.matchTemplate(existing_padded, crop, cv2.TM_CCOEFF_NORMED)
    max_val = result.max()
    return max_val >= threshold


class ConvertDialog(QDialog):
    """
    两步式转换向导。

    用法：
        dlg = ConvertDialog(source_model, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            result = dlg.get_result()
            # result = {'type': 'multi_match', 'templates': [...]}
    """

    def __init__(self, source_model: ScriptModel, target_pictures_dir: str, parent=None):
        super().__init__(parent)
        self.source_model = source_model
        self.target_pictures_dir = target_pictures_dir  # 模板保存目标目录
        self._result = None

        # 过滤出非 sleep 步骤（用于 Step 1）
        self._tap_steps = []
        for i, action in enumerate(source_model.actions):
            if action.type in ("tap", "find_and_tap", "swipe"):
                self._tap_steps.append((i, action))

        # Step 1 的筛选结果
        self._filter_region = None   # (x, y, w, h) 框选区域
        self._filtered_steps = []    # 筛选后的步骤

        self.setWindowTitle("流水线 → 多模板匹配 转换向导")
        self.setMinimumSize(1000, 650)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 使用 QStackedWidget 管理两个步骤的页面
        self.page_stack = QStackedWidget()
        layout.addWidget(self.page_stack, stretch=1)

        # Step 1 页面
        self._create_step1_page()

        # Step 2 页面
        self._create_step2_page()

        # 底部按钮
        btn_layout = QHBoxLayout()
        self.btn_back = QPushButton("← 上一步")
        self.btn_back.setEnabled(False)
        self.btn_back.clicked.connect(self._go_step1)
        btn_layout.addWidget(self.btn_back)

        btn_layout.addStretch()

        self.step_label = QLabel("步骤 1/2: 区域筛选")
        self.step_label.setStyleSheet("color: #888;")
        btn_layout.addWidget(self.step_label)

        btn_layout.addStretch()

        self.btn_next = QPushButton("下一步 →")
        self.btn_next.clicked.connect(self._go_step2)
        btn_layout.addWidget(self.btn_next)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

    # =================== Step 1: 区域筛选 ===================

    def _create_step1_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        # 说明
        info = QLabel(
            "📋 步骤 1：选择一个步骤查看截图，然后在截图上框选矩形区域。\n"
            "程序将筛选出所有点击坐标落在该区域内的步骤，用于后续模板截取。"
        )
        info.setStyleSheet("color: #555; padding: 8px; background: #f0f4f8; border-radius: 4px;")
        layout.addWidget(info)

        # 左右分栏
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧：步骤列表
        left_group = QGroupBox("步骤列表（非等待步骤）")
        left_layout = QVBoxLayout(left_group)

        self.step1_list = QListWidget()
        self.step1_list.setAlternatingRowColors(True)
        self.step1_list.currentRowChanged.connect(self._on_step1_selected)
        left_layout.addWidget(self.step1_list)

        # 填充步骤列表
        for orig_idx, action in self._tap_steps:
            item = QListWidgetItem()
            if action.type == "tap":
                x, y = action.params.get('x', 0), action.params.get('y', 0)
                item.setText(f"{orig_idx+1}. 🖱 点击 ({x}, {y})")
            elif action.type == "find_and_tap":
                tpl = os.path.basename(action.params.get('template', ''))
                item.setText(f"{orig_idx+1}. 🔍 找图 [{tpl}]")
            elif action.type == "swipe":
                x1, y1 = action.params.get('x1', 0), action.params.get('y1', 0)
                item.setText(f"{orig_idx+1}. 👆 滑动 ({x1},{y1})→...")
            self.step1_list.addItem(item)

        splitter.addWidget(left_group)

        # 右侧：截图预览 + 框选（使用 MultiRegionWidget 避免自动保存）
        right_group = QGroupBox("截图预览（框选筛选区域）")
        right_layout = QVBoxLayout(right_group)

        self.step1_screenshot = MultiRegionWidget()
        self.step1_screenshot.region_completed.connect(self._on_filter_region_selected)
        right_layout.addWidget(self.step1_screenshot)

        self.step1_info = QLabel("选中步骤以显示截图")
        self.step1_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.step1_info.setStyleSheet("color: #888;")
        right_layout.addWidget(self.step1_info)

        splitter.addWidget(right_group)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter)
        self.page_stack.addWidget(page)

    def _on_step1_selected(self, row):
        """Step 1：选中步骤后加载其快照截图，仅显示当前步骤的点击位置"""
        if row < 0 or row >= len(self._tap_steps):
            return

        orig_idx, action = self._tap_steps[row]
        snapshot_path = action.params.get("snapshot", "")

        if snapshot_path and os.path.exists(snapshot_path):
            q_img = QImage(snapshot_path)
            if not q_img.isNull():
                self.step1_screenshot.clear_regions()
                self._filter_region = None
                self.step1_screenshot.update_screenshot(q_img)
                
                # 只显示当前步骤的点击位置
                if action.type == "tap":
                    x = action.params.get('x', 0)
                    y = action.params.get('y', 0)
                    self.step1_screenshot.set_click_markers([(x, y, f"#{orig_idx+1}")])
                else:
                    self.step1_screenshot.set_click_markers([])
                
                self.step1_info.setText(f"当前截图来自步骤 {orig_idx+1}，框选区域以筛选步骤")
                return

        self.step1_info.setText("⚠️ 该步骤无录制快照")

    def _on_filter_region_selected(self, idx, x, y, w, h):
        """框选区域完成后保存（只保留最后一个区域）"""
        self._filter_region = (x, y, w, h)
        # 只保留最后一次框选（Step 1 只需一个筛选区域）
        regions = self.step1_screenshot.get_regions()
        if len(regions) > 1:
            self.step1_screenshot._regions = [regions[-1]]
            self.step1_screenshot.update()
        
        # 统计匹配步骤数
        count = 0
        for orig_idx, action in self._tap_steps:
            if action.type == "tap":
                ax, ay = action.params.get('x', 0), action.params.get('y', 0)
                if x <= ax <= x + w and y <= ay <= y + h:
                    count += 1
        self.step1_info.setText(
            f"✅ 已框选区域 ({x},{y}) {w}×{h}，匹配 {count} 个点击步骤"
        )

    # =================== Step 2: 多区域批量抠图 ===================

    def _create_step2_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        info = QLabel(
            "📋 步骤 2：左侧可取消勾选排除步骤，右侧在截图上框选多个物品图标区域。\n"
            "程序将自动判断每个步骤的点击坐标落在哪个区域，并裁切模板。\n"
            "完成后自动去重相似模板。右键点击区域可删除，Ctrl+Z 撤销。"
        )
        info.setStyleSheet("color: #555; padding: 8px; background: #f0f4f8; border-radius: 4px;")
        layout.addWidget(info)

        # 左右分栏：左侧可勾选步骤列表 + 右侧多区域框选
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧：筛选后的步骤列表（可勾选排除）
        left_group = QGroupBox("筛选步骤（取消勾选可排除）")
        left_layout = QVBoxLayout(left_group)
        self.step2_list = QListWidget()
        self.step2_list.setAlternatingRowColors(True)
        self.step2_list.itemChanged.connect(self._on_step2_check_changed)
        self.step2_list.currentRowChanged.connect(self._on_step2_row_selected)
        left_layout.addWidget(self.step2_list)
        splitter.addWidget(left_group)
        
        # 右侧：多区域框选截图
        right_group = QGroupBox("截图框选")
        right_layout = QVBoxLayout(right_group)
        self.step2_widget = MultiRegionWidget()
        self.step2_widget.region_completed.connect(self._on_crop_region_completed)
        right_layout.addWidget(self.step2_widget)
        splitter.addWidget(right_group)
        
        splitter.setSizes([200, 600])
        layout.addWidget(splitter, stretch=1)

        # 底部信息
        self.step2_info = QLabel("请在截图上框选物品图标区域")
        self.step2_info.setStyleSheet("color: #888; padding: 4px;")
        layout.addWidget(self.step2_info)

        self.page_stack.addWidget(page)
    
    def _on_step2_check_changed(self, item):
        """筛选步骤勾选变化时更新截图标记"""
        self._update_step2_markers()
    
    def _on_step2_row_selected(self, row):
        """选中步骤时切换截图快照"""
        if row < 0:
            return
        item = self.step2_list.item(row)
        if item is None:
            return
        orig_idx = item.data(Qt.ItemDataRole.UserRole)
        action = next((a for oi, a in self._filtered_steps if oi == orig_idx), None)
        if action is None:
            return
        snapshot_path = action.params.get("snapshot", "")
        if snapshot_path and os.path.exists(snapshot_path):
            q_img = QImage(snapshot_path)
            if not q_img.isNull():
                # 保留已有区域和标记，仅更换背景截图
                self.step2_widget.update_screenshot(q_img)
                self.step2_info.setText(f"当前截图来自步骤 #{orig_idx+1}")
    
    def _update_step2_markers(self):
        """根据当前勾选状态更新截图上的点击标记"""
        markers = []
        for i in range(self.step2_list.count()):
            item = self.step2_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                orig_idx = item.data(Qt.ItemDataRole.UserRole)
                action = next((a for oi, a in self._filtered_steps if oi == orig_idx), None)
                if action and action.type == "tap":
                    ax = action.params.get('x', 0)
                    ay = action.params.get('y', 0)
                    markers.append((ax, ay, f"#{orig_idx+1}"))
        self.step2_widget.set_click_markers(markers)
    
    def _get_active_filtered_steps(self):
        """返回当前勾选的（未排除的）筛选步骤"""
        active = []
        for i in range(self.step2_list.count()):
            item = self.step2_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                orig_idx = item.data(Qt.ItemDataRole.UserRole)
                action = next((a for oi, a in self._filtered_steps if oi == orig_idx), None)
                if action:
                    active.append((orig_idx, action))
        return active

    def _on_crop_region_completed(self, idx, x, y, w, h):
        """Step 2：每完成一个框选区域，统计匹配的步骤数"""
        active_steps = self._get_active_filtered_steps()
        matched = 0
        for orig_idx, action in active_steps:
            if action.type == "tap":
                ax, ay = action.params.get('x', 0), action.params.get('y', 0)
                if x <= ax <= x + w and y <= ay <= y + h:
                    matched += 1

        total_regions = len(self.step2_widget.get_regions())
        self.step2_info.setText(
            f"已框选 {total_regions} 个区域 | "
            f"区域 #{idx+1}: {w}×{h}, 匹配 {matched} 个步骤"
        )

    # =================== 页面导航 ===================

    def _go_step1(self):
        """返回 Step 1"""
        self.page_stack.setCurrentIndex(0)
        self.btn_back.setEnabled(False)
        self.btn_next.setText("下一步 →")
        self.btn_next.clicked.disconnect()
        self.btn_next.clicked.connect(self._go_step2)
        self.step_label.setText("步骤 1/2: 区域筛选")

    def _go_step2(self):
        """进入 Step 2"""
        if self._filter_region is None:
            QMessageBox.warning(self, "提示", "请先在截图上框选一个筛选区域。")
            return

        # 筛选步骤
        x, y, w, h = self._filter_region
        self._filtered_steps = []
        for orig_idx, action in self._tap_steps:
            if action.type == "tap":
                ax, ay = action.params.get('x', 0), action.params.get('y', 0)
                if x <= ax <= x + w and y <= ay <= y + h:
                    self._filtered_steps.append((orig_idx, action))

        if not self._filtered_steps:
            QMessageBox.warning(
                self, "提示",
                "框选区域内没有任何点击步骤，请重新框选。"
            )
            return

        # 加载截图到 Step 2（使用第一个步骤的快照）
        first_action = self._filtered_steps[0][1]
        snapshot_path = first_action.params.get("snapshot", "")
        if snapshot_path and os.path.exists(snapshot_path):
            q_img = QImage(snapshot_path)
            self.step2_widget.update_screenshot(q_img)
        else:
            # 回退：使用 Step 1 的截图
            if self.step1_screenshot._source_image:
                self.step2_widget.update_screenshot(self.step1_screenshot._source_image)

        # 填充 Step 2 左侧可勾选步骤列表
        self.step2_list.clear()
        for orig_idx, action in self._filtered_steps:
            x_pos = action.params.get('x', 0)
            y_pos = action.params.get('y', 0)
            item = QListWidgetItem(f"#{orig_idx+1}  ({x_pos}, {y_pos})")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, orig_idx)
            self.step2_list.addItem(item)

        # 设置点击位置标记（通过勾选状态动态更新）
        self._update_step2_markers()

        # 切换页面
        self.page_stack.setCurrentIndex(1)
        self.btn_back.setEnabled(True)
        self.btn_next.setText("✨ 完成转换")
        self.btn_next.clicked.disconnect()
        self.btn_next.clicked.connect(self._on_finish)
        self.step_label.setText(f"步骤 2/2: 批量抠图（{len(self._filtered_steps)} 个步骤）")

    def _on_finish(self):
        """完成转换：以步骤为主体裁切模板 + 去重 + 生成 multi_match 结果"""
        regions = self.step2_widget.get_regions()
        if not regions:
            QMessageBox.warning(self, "提示", "请至少框选一个模板区域。")
            return

        active_steps = self._get_active_filtered_steps()
        if not active_steps:
            QMessageBox.warning(self, "提示", "没有活跃步骤，无法转换。")
            return

        # 确保目标 Pictures 目录存在
        pictures_dir = self.target_pictures_dir
        os.makedirs(pictures_dir, exist_ok=True)

        from config import get_resolution_tag
        res_tag = get_resolution_tag()

        # ===== 区域尺寸归一化 =====
        # 手动框选的区域大小不一致，统一为中位数宽高（保持各区域中心不变）
        # 这样所有裁切图的尺寸完全一致，去重比较更可靠
        widths = [rw for _, _, rw, _ in regions]
        heights = [rh for _, _, _, rh in regions]
        norm_w = int(np.median(widths))
        norm_h = int(np.median(heights))
        
        normalized_regions = []
        for rx, ry, rw, rh in regions:
            # 保持中心不变，调整为统一尺寸
            cx = rx + rw // 2
            cy = ry + rh // 2
            new_rx = max(0, cx - norm_w // 2)
            new_ry = max(0, cy - norm_h // 2)
            normalized_regions.append((new_rx, new_ry, norm_w, norm_h))

        # 核心逻辑：遍历每个步骤，找到该步骤点击坐标所在的区域，
        # 从该步骤自己的截图中裁切该区域，作为该步骤的模板
        templates = []
        tpl_counter = 0

        for orig_idx, action in active_steps:
            ax = action.params.get('x', 0)
            ay = action.params.get('y', 0)

            # 找到包含该步骤点击坐标的归一化区域
            matched_region = None
            for rx, ry, rw, rh in normalized_regions:
                if rx <= ax <= rx + rw and ry <= ay <= ry + rh:
                    matched_region = (rx, ry, rw, rh)
                    break

            if matched_region is None:
                continue

            rx, ry, rw, rh = matched_region

            # 加载该步骤自己的截图快照
            snapshot_path = action.params.get("snapshot", "")
            if not snapshot_path or not os.path.exists(snapshot_path):
                continue
            # 直接用 OpenCV 读取快照（避免 QImage 格式转换导致颜色精度损失）
            img_array = np.fromfile(snapshot_path, dtype=np.uint8)
            cv_img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if cv_img is None:
                continue

            # 从该步骤的截图中裁切归一化区域（所有裁切图尺寸一致）
            img_h, img_w = cv_img.shape[:2]
            crop_x2 = min(rx + rw, img_w)
            crop_y2 = min(ry + rh, img_h)
            crop = cv_img[ry:crop_y2, rx:crop_x2]
            if crop.size == 0:
                continue
            
            # 同时裁切扩边区域（每边多 _DEDUP_PAD 像素），用于去重比较
            pad = _DEDUP_PAD
            pad_x1 = max(0, rx - pad)
            pad_y1 = max(0, ry - pad)
            pad_x2 = min(img_w, rx + rw + pad)
            pad_y2 = min(img_h, ry + rh + pad)
            crop_padded = cv_img[pad_y1:pad_y2, pad_x1:pad_x2]

            # 使用 matchTemplate 检查是否与已有模板重复（位移容忍）
            is_dup = False
            for existing in templates:
                if _is_duplicate_template(crop, existing['_padded']):
                    is_dup = True
                    break
            if is_dup:
                continue

            # 保存模板文件
            tpl_counter += 1
            name = f"模板{tpl_counter}"
            if res_tag:
                filename = f"{name}@{res_tag}.png"
            else:
                filename = f"{name}.png"

            save_path = os.path.join(pictures_dir, filename)
            cv2.imencode('.png', crop)[1].tofile(save_path)

            # 计算偏移量 = 点击坐标 - 区域中心
            region_center_x = rx + rw // 2
            region_center_y = ry + rh // 2
            offset_x = ax - region_center_x
            offset_y = ay - region_center_y

            # 保存偏移量到 meta.json
            try:
                import template_meta
                template_meta.set_meta(
                    pictures_dir, filename,
                    offset_x=offset_x, offset_y=offset_y
                )
            except Exception:
                pass

            templates.append({
                'template': filename,
                'threshold': 0.9,
                '_padded': crop_padded,  # 临时字段，用于后续去重比较
            })

        if not templates:
            QMessageBox.warning(self, "提示", "所有模板均为重复，没有有效模板生成。")
            return

        # 清理临时字段（不序列化到结果中）
        for t in templates:
            t.pop('_padded', None)

        self._result = {
            'type': 'multi_match',
            'templates': templates,
        }
        
        # 批量保存结束后，清理一下该目录的图像匹配缓存
        try:
            import image_engine
            image_engine.clear_cache(pictures_dir)
        except Exception:
            pass

        QMessageBox.information(
            self, "转换完成",
            f"成功生成 {len(templates)} 个去重模板。\n"
            f"点击确定后将创建 multi_match 指令。"
        )
        self.accept()

    def get_result(self):
        """获取转换结果"""
        return self._result
