"""
截图预览控件：自绘方案，支持坐标拾取和区域截图。
"""

import os

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QImage
from PyQt6.QtWidgets import QWidget, QSizePolicy, QInputDialog

from config import Y_OFFSET, TARGETS_DIR
from gui.constants import COLOR_SUCCESS, COLOR_DISABLED, create_font


class ScreenshotWidget(QWidget):
    """
    截图预览区域：完全自绘方案（paintEvent）。
    支持：
    - 鼠标移动：实时显示坐标
    - 左键单击：拾取坐标
    - 左键拖拽：区域选取 → 裁切保存为模板图片
    """

    # 区域选取完成信号：原图坐标 (x, y, w, h)
    region_selected = pyqtSignal(int, int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_image = None   # 原始 QImage
        self._matches = []          # 匹配结果列表
        self._y_offset = Y_OFFSET   # 当前 Y 偏移量
        self._mouse_pos = None      # 鼠标坐标（原图坐标系）

        self._source_pixmap = None  # 用于硬件加速的高效绘图对象

        # 区域选取状态
        self._drag_start = None     # 拖拽起始点（原图坐标）
        self._drag_end = None       # 拖拽结束点（原图坐标）
        self._is_dragging = False   # 是否正在拖拽

        self.setMinimumSize(300, 400)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    def update_screenshot(self, q_image):
        """
        更新截图内容。

        Args:
            q_image (QImage): Qt 格式截图
        """
        if q_image is None or q_image.isNull():
            return
        self._source_image = q_image
        
        # 将内存中的 QImage 转换为显存中的 QPixmap 对象，利用 GPU 加速平滑缩放渲染
        from PyQt6.QtGui import QPixmap 
        self._source_pixmap = QPixmap.fromImage(q_image)

        self.update()  # 触发 paintEvent 重绘

    def update_matches(self, matches):
        """更新匹配结果列表，触发重绘。"""
        self._matches = matches
        self.update()

    def set_y_offset(self, offset):
        """更新 Y 偏移量，触发重绘。"""
        self._y_offset = offset
        self.update()

    def _calc_layout(self):
        """
        计算图片在控件中的显示布局（核心方法）。
        绘制和鼠标事件共用此方法，保证坐标严格一致。

        Returns:
            dict or None: {
                'offset_x': 图片左上角 X 偏移,
                'offset_y': 图片左上角 Y 偏移,
                'display_w': 图片显示宽度,
                'display_h': 图片显示高度,
                'scale': 缩放比例 (显示/原图),
                'img_w': 原图宽度,
                'img_h': 原图高度,
            }
        """
        if self._source_image is None:
            return None

        img_w = self._source_image.width()
        img_h = self._source_image.height()
        if img_w <= 0 or img_h <= 0:
            return None

        widget_w = self.width()
        widget_h = self.height()

        # 保持宽高比缩放，留 4px 边距
        scale = min((widget_w - 4) / img_w, (widget_h - 4) / img_h)
        display_w = img_w * scale
        display_h = img_h * scale

        # 居中
        offset_x = (widget_w - display_w) / 2.0
        offset_y = (widget_h - display_h) / 2.0

        return {
            'offset_x': offset_x,
            'offset_y': offset_y,
            'display_w': display_w,
            'display_h': display_h,
            'scale': scale,
            'img_w': img_w,
            'img_h': img_h,
        }

    def paintEvent(self, event):
        """
        完全自绘：背景 → 截图 → 匹配标记 → 选区矩形 → 鼠标准心。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # 绘制深色背景
        painter.fillRect(self.rect(), QColor("#1a1a2e"))

        layout = self._calc_layout()
        if layout is None:
            # 无截图时绘制提示文字
            painter.setPen(QColor(COLOR_DISABLED))
            painter.setFont(create_font(12))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "等待截图...")
            painter.end()
            return

        ox = layout['offset_x']
        oy = layout['offset_y']
        dw = layout['display_w']
        dh = layout['display_h']
        scale = layout['scale']

        # 绘制截图 (使用硬件加速的 QPixmap 结合平滑插值，降低 CPU 负担)
        target_rect = QRectF(ox, oy, dw, dh)
        source_rect = QRectF(0, 0, layout['img_w'], layout['img_h'])
        if self._source_pixmap and not self._source_pixmap.isNull():
            painter.drawPixmap(target_rect, self._source_pixmap, source_rect)

        # 绘制匹配位置标记
        for name, cx, cy, score in self._matches:
            sx = ox + cx * scale
            sy = oy + cy * scale

            # 红色十字 = 匹配位置
            pen_red = QPen(QColor(255, 50, 50), 2)
            painter.setPen(pen_red)
            painter.drawLine(int(sx - 12), int(sy), int(sx + 12), int(sy))
            painter.drawLine(int(sx), int(sy - 12), int(sx), int(sy + 12))

            # Y 偏移 > 0 时才绘制蓝色准心（购买按钮位置）和连线
            if self._y_offset > 0:
                buy_sy = oy + (cy + self._y_offset) * scale
                pen_blue = QPen(QColor(50, 150, 255), 2)
                painter.setPen(pen_blue)
                painter.drawLine(int(sx - 12), int(buy_sy), int(sx + 12), int(buy_sy))
                painter.drawLine(int(sx), int(buy_sy - 12), int(sx), int(buy_sy + 12))

                # 虚线连接
                pen_link = QPen(QColor(255, 255, 100), 1, Qt.PenStyle.DotLine)
                painter.setPen(pen_link)
                painter.drawLine(int(sx), int(sy), int(sx), int(buy_sy))

            # 标签文字（绿色）
            painter.setPen(QColor(0, 220, 80))
            painter.setFont(create_font(8))
            painter.drawText(int(sx + 14), int(sy - 4), f"{name} ({score:.2f})")

        # 绘制拖拽选区矩形（蓝色半透明）
        if self._drag_start is not None and self._drag_end is not None:
            x1, y1 = self._drag_start
            x2, y2 = self._drag_end
            sx1 = ox + x1 * scale
            sy1 = oy + y1 * scale
            sx2 = ox + x2 * scale
            sy2 = oy + y2 * scale

            rect = QRectF(min(sx1, sx2), min(sy1, sy2),
                          abs(sx2 - sx1), abs(sy2 - sy1))
            painter.setBrush(QColor(64, 158, 255, 50))
            painter.setPen(QPen(QColor(64, 158, 255), 2, Qt.PenStyle.DashLine))
            painter.drawRect(rect)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            # 选区尺寸标注
            rw = abs(x2 - x1)
            rh = abs(y2 - y1)
            if rw > 5 and rh > 5:
                painter.setPen(QColor(255, 255, 255))
                painter.setFont(create_font(8))
                painter.drawText(int(min(sx1, sx2)), int(min(sy1, sy2) - 4),
                                 f"{rw}×{rh}")

        # 鼠标位置十字准星（绿色虚线）— 拖拽中不显示
        if self._mouse_pos is not None and not self._is_dragging:
            mx_orig, my_orig = self._mouse_pos
            smx = ox + mx_orig * scale
            smy = oy + my_orig * scale

            pen_green = QPen(QColor(COLOR_SUCCESS), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen_green)
            painter.drawLine(int(smx), int(oy), int(smx), int(oy + dh))
            painter.drawLine(int(ox), int(smy), int(ox + dw), int(smy))

        painter.end()

    def _widget_to_original(self, wx, wy):
        """将控件坐标转换为原图坐标。"""
        layout = self._calc_layout()
        if layout is None:
            return None

        rel_x = wx - layout['offset_x']
        rel_y = wy - layout['offset_y']

        if rel_x < 0 or rel_y < 0 or rel_x > layout['display_w'] or rel_y > layout['display_h']:
            return None

        orig_x = int(rel_x / layout['scale'])
        orig_y = int(rel_y / layout['scale'])
        return orig_x, orig_y

    def mousePressEvent(self, event):
        """鼠标按下：记录拖拽起点。"""
        if event.button() != Qt.MouseButton.LeftButton:
            return
        result = self._widget_to_original(
            event.position().x(), event.position().y()
        )
        if result is None:
            return

        self._drag_start = result
        self._drag_end = result
        self._is_dragging = True
        self._mouse_pos = result
        self.update()

    def mouseMoveEvent(self, event):
        """鼠标移动：更新拖拽终点或状态栏坐标。"""
        result = self._widget_to_original(
            event.position().x(), event.position().y()
        )
        if result is None:
            return

        if self._is_dragging:
            self._drag_end = result
            self.update()

        main_win = self.window()
        if hasattr(main_win, 'on_coord_hover'):
            main_win.on_coord_hover(result[0], result[1])

    def mouseReleaseEvent(self, event):
        """鼠标释放：判断是单击拾取还是拖拽选区。"""
        if event.button() != Qt.MouseButton.LeftButton or not self._is_dragging:
            return

        self._is_dragging = False
        result = self._widget_to_original(
            event.position().x(), event.position().y()
        )
        if result is not None:
            self._drag_end = result

        if self._drag_start and self._drag_end:
            x1, y1 = self._drag_start
            x2, y2 = self._drag_end
            rw = abs(x2 - x1)
            rh = abs(y2 - y1)

            if rw > 10 and rh > 10:
                rx = min(x1, x2)
                ry = min(y1, y2)
                self.region_selected.emit(rx, ry, rw, rh)
                self._save_region(rx, ry, rw, rh)
            else:
                self._mouse_pos = self._drag_end
                self._drag_start = None
                self._drag_end = None
                main_win = self.window()
                if hasattr(main_win, 'on_coord_picked'):
                    main_win.on_coord_picked(result[0], result[1])

        self.update()

    def _save_region(self, x, y, w, h):
        """弹出对话框保存裁切区域为模板图片（可选择目录）。"""
        if self._source_image is None:
            return

        # 裁切原图
        cropped = self._source_image.copy(x, y, w, h)

        # 获取可用子目录列表
        from config import TARGETS_DIR, get_resolution_tag
        main_win = self.window()
        library_tab = getattr(main_win, 'library_tab', None)
        dirs = library_tab.get_all_dirs() if library_tab else ["default"]
        current_dir = library_tab.dir_combo.currentText() if library_tab else dirs[0]

        # 循环：取消覆盖时重新回到输入对话框
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QComboBox, QMessageBox
        saved = False
        while not saved:
            dlg = QDialog(self)
            dlg.setWindowTitle("保存模板图片")
            form = QFormLayout(dlg)

            # 目录选择
            dir_combo = QComboBox()
            dir_combo.addItems(dirs)
            idx = dir_combo.findText(current_dir)
            if idx >= 0:
                dir_combo.setCurrentIndex(idx)
            form.addRow("保存目录:", dir_combo)

            # 名称输入
            name_edit = QLineEdit()
            name_edit.setPlaceholderText("请输入模板名称")
            name_edit.setMinimumHeight(32)
            form.addRow(f"名称 ({w}×{h}):", name_edit)
            name_edit.setFocus()

            # 确认按钮
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.accepted.connect(dlg.accept)
            buttons.rejected.connect(dlg.reject)
            form.addRow(buttons)

            if dlg.exec() != QDialog.DialogCode.Accepted or not name_edit.text().strip():
                # 用户关闭对话框，彻底取消
                self._drag_start = None
                self._drag_end = None
                self.update()
                return

            # 构建保存路径
            save_dir = os.path.join(TARGETS_DIR, dir_combo.currentText())
            os.makedirs(save_dir, exist_ok=True)
            res_tag = get_resolution_tag()
            base_name = name_edit.text().strip()
            current_dir = dir_combo.currentText()  # 记住目录选择
            save_path = os.path.join(save_dir, f"{base_name}@{res_tag}.png")

            # 同名文件检测
            if os.path.exists(save_path):
                reply = QMessageBox.question(
                    self, "文件已存在",
                    f"模板 \"{base_name}\" 已存在，是否覆盖？\n选择\"否\"将自动添加编号。",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Cancel
                )
                if reply == QMessageBox.StandardButton.Cancel:
                    continue  # 回到输入对话框
                if reply == QMessageBox.StandardButton.No:
                    n = 1
                    while True:
                        save_path = os.path.join(
                            save_dir, f"{base_name}_{n}@{res_tag}.png"
                        )
                        if not os.path.exists(save_path):
                            break
                        n += 1

            cropped.save(save_path, "PNG")
            saved = True

        # 清除选区
        self._drag_start = None
        self._drag_end = None
        self.update()

        # 通知主窗口
        if hasattr(main_win, '_append_log'):
            main_win._append_log(f"模板已保存: {save_path} ({w}×{h})")

        # 刷新图库
        if library_tab:
            library_tab.dir_combo.setCurrentText(dir_combo.currentText())
            library_tab._load_images()
