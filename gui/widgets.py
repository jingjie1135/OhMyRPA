"""
截图预览控件：自绘方案，支持坐标拾取和区域截图。
"""

import os
import time

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
    
    # 模板保存完成信号：保存的绝对路径
    template_saved = pyqtSignal(str)

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
        
        # 可选：自定义保存目录，设置后 _save_region 直接保存到此目录，跳过图库目录选择
        self.custom_save_dir = None

        # ScrcpyAdapter 引用（由 main_window 在 adapter_ready 时注入）
        self._scrcpy_adapter = None
        # 录制模式完整轨迹点列表：[(x, y, timestamp_ms), ...]
        self._rec_path = []

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

    def get_source_image(self):
        """返回当前截图（QImage），未设置时为 None"""
        return self._source_image

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

            # 从 meta.json 读取该模板的偏移量，绘制蓝色准心（实际点击位置）
            try:
                import template_meta
                pictures_dir = getattr(self, 'custom_save_dir', None) or ""
                meta = template_meta.get(pictures_dir, name) if pictures_dir else {}
                meta_ox = meta.get("offset_x", 0)
                meta_oy = meta.get("offset_y", 0)
            except Exception:
                meta_ox, meta_oy = 0, 0

            if meta_ox != 0 or meta_oy != 0:
                click_sx = ox + (cx + meta_ox) * scale
                click_sy = oy + (cy + meta_oy) * scale
                pen_blue = QPen(QColor(50, 150, 255), 2)
                painter.setPen(pen_blue)
                painter.drawLine(int(click_sx - 12), int(click_sy), int(click_sx + 12), int(click_sy))
                painter.drawLine(int(click_sx), int(click_sy - 12), int(click_sx), int(click_sy + 12))

                # 虚线连接红色匹配位置和蓝色点击位置
                pen_link = QPen(QColor(255, 255, 100), 1, Qt.PenStyle.DotLine)
                painter.setPen(pen_link)
                painter.drawLine(int(sx), int(sy), int(click_sx), int(click_sy))

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

        # 鼠标位置十字准星（绿色虚线）— 拖拽中，或在仅实时操作模式（非录制）下，不显示
        hide_crosshair = self._is_dragging or (
            getattr(self, '_live_control_mode', False) and not getattr(self, '_recording_mode', False)
        )
        if self._mouse_pos is not None and not hide_crosshair:
            mx_orig, my_orig = self._mouse_pos
            smx = ox + mx_orig * scale
            smy = oy + my_orig * scale

            pen_green = QPen(QColor(COLOR_SUCCESS), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen_green)
            painter.drawLine(int(smx), int(oy), int(smx), int(oy + dh))
            painter.drawLine(int(ox), int(smy), int(ox + dw), int(smy))

        # 录制模式：绘制滑动轨迹箭头（绿色）
        _rs = getattr(self, '_rec_start', None)
        _re = getattr(self, '_rec_end', None)
        if getattr(self, '_recording_mode', False) and _rs and _re:
            sx1 = ox + _rs[0] * scale
            sy1 = oy + _rs[1] * scale
            sx2 = ox + _re[0] * scale
            sy2 = oy + _re[1] * scale
            # 绿色箭头线
            pen_swipe = QPen(QColor(0, 220, 80), 3)
            painter.setPen(pen_swipe)
            painter.drawLine(int(sx1), int(sy1), int(sx2), int(sy2))
            # 起点圆点
            painter.setBrush(QColor(0, 220, 80))
            painter.drawEllipse(int(sx1) - 4, int(sy1) - 4, 8, 8)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            # 终点箭头
            import math
            angle = math.atan2(sy2 - sy1, sx2 - sx1)
            arr_len = 14
            ax1 = sx2 - arr_len * math.cos(angle - 0.4)
            ay1 = sy2 - arr_len * math.sin(angle - 0.4)
            ax2 = sx2 - arr_len * math.cos(angle + 0.4)
            ay2 = sy2 - arr_len * math.sin(angle + 0.4)
            painter.drawLine(int(sx2), int(sy2), int(ax1), int(ay1))
            painter.drawLine(int(sx2), int(sy2), int(ax2), int(ay2))

        # 绘制点击位置标记（升级找图时用，纯视觉叠加不影响裁切）
        marker = getattr(self, '_click_marker', None)
        if marker and layout:
            mx, my = marker
            smx = ox + mx * scale
            smy = oy + my * scale
            pen_marker = QPen(QColor(255, 50, 50), 3)
            painter.setPen(pen_marker)
            painter.drawLine(int(smx - 15), int(smy), int(smx + 15), int(smy))
            painter.drawLine(int(smx), int(smy - 15), int(smx), int(smy + 15))
            # 标注文字
            painter.setPen(QColor(255, 50, 50))
            painter.setFont(create_font(9))
            painter.drawText(int(smx + 18), int(smy - 6), f"原点击 ({mx}, {my})")

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

    def mouseDoubleClickEvent(self, event):
        """鼠标双击：用来执行唤醒屏幕等无特定坐标的快捷操作"""
        if event.button() == Qt.MouseButton.LeftButton:
            # 在实时控制模式下，双击发送亮屏（back_or_screen_on）信号
            if getattr(self, '_live_control_mode', False) and self._scrcpy_adapter:
                self._scrcpy_adapter.back_or_screen_on()
                
            # 也可以记录双击的坐标，暂时我们只用来唤醒屏幕
            super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        """鼠标按下：录制模式下仅拾取坐标，否则记录拖拽起点。"""
        if event.button() != Qt.MouseButton.LeftButton:
            return
        result = self._widget_to_original(
            event.position().x(), event.position().y()
        )
        if result is None:
            return

        # 录制模式或实时操作模式：记录起点，等 release 判断是点击还是滑动
        if getattr(self, '_recording_mode', False) or getattr(self, '_live_control_mode', False):
            self._rec_start = result
            self._rec_dragging = True
            self._rec_press_time = time.time()  # 记录按下时间
            self._rec_path = [(result[0], result[1], int(time.time() * 1000))]  # 完整轨迹
            self._mouse_pos = result
            # 通过 scrcpy 控制通道实时发送 touch_down
            if self._scrcpy_adapter and self._scrcpy_adapter.supports_touch:
                self._scrcpy_adapter.touch_down(result[0], result[1])
            self.update()
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

        # 录制模式或实时操作模式：更新拖拽终点
        if getattr(self, '_rec_dragging', False) and (getattr(self, '_recording_mode', False) or getattr(self, '_live_control_mode', False)):
            self._rec_end = result
            # 记录轨迹点
            self._rec_path.append((result[0], result[1], int(time.time() * 1000)))
            # 通过 scrcpy 控制通道实时发送 touch_move
            if self._scrcpy_adapter and self._scrcpy_adapter.supports_touch:
                self._scrcpy_adapter.touch_move(result[0], result[1])
            self.update()

        if self._is_dragging:
            self._drag_end = result
            self.update()

        main_win = self.window()
        if hasattr(main_win, 'on_coord_hover'):
            main_win.on_coord_hover(result[0], result[1])

    def mouseReleaseEvent(self, event):
        """鼠标释放：判断是单击还是拖拽选区/滑动。"""
        if event.button() != Qt.MouseButton.LeftButton:
            return

        # 录制模式或实时操作模式：判断点击或滑动
        if getattr(self, '_rec_dragging', False) and (getattr(self, '_recording_mode', False) or getattr(self, '_live_control_mode', False)):
            self._rec_dragging = False
            result = self._widget_to_original(
                event.position().x(), event.position().y()
            )
            end = result if result else getattr(self, '_rec_end', self._rec_start)
            start = self._rec_start
            dist = ((end[0] - start[0])**2 + (end[1] - start[1])**2) ** 0.5
            # 通过 scrcpy 发送 touch_up
            if self._scrcpy_adapter and self._scrcpy_adapter.supports_touch:
                self._scrcpy_adapter.touch_up(end[0], end[1])
            
            # 如果仅仅是实时操作模式（非录制），则不再上报主窗口事件
            if not getattr(self, '_recording_mode', False):
                self._rec_start = None
                self._rec_end = None
                self.update()
                return

            main_win = self.window()
            if dist > 10:
                # 滑动操作：使用完整轨迹时长
                duration_ms = max(100, int((time.time() - getattr(self, '_rec_press_time', time.time())) * 1000))
                path = getattr(self, '_rec_path', [])
                if hasattr(main_win, 'on_swipe_picked'):
                    main_win.on_swipe_picked(start[0], start[1], end[0], end[1], duration_ms, path)
            else:
                # 单击操作
                if hasattr(main_win, 'on_coord_picked'):
                    main_win.on_coord_picked(start[0], start[1])
            # 保留箭头轨迹 300ms 后清除
            self._rec_end = end  # 确保终点已更新
            from PyQt6.QtCore import QTimer
            def _clear_swipe_trail():
                self._rec_start = None
                self._rec_end = None
                self.update()
            QTimer.singleShot(300, _clear_swipe_trail)
            self.update()
            return

        if not self._is_dragging:
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
        """弹出对话框保存裁切区域为模板图片。"""
        if self._source_image is None:
            return

        # 裁切原图
        cropped = self._source_image.copy(x, y, w, h)
        from config import get_resolution_tag
        from gui.template_save_dialog import TemplateSaveDialog
        from PyQt6.QtWidgets import QDialog, QMessageBox

        if self.custom_save_dir:
            # 简化流程：直接保存到指定目录，只要求输入名称
            save_dir = self.custom_save_dir
            os.makedirs(save_dir, exist_ok=True)
            res_tag = get_resolution_tag()
            saved = False
            while not saved:
                # 使用新的可视化配置窗
                dlg = TemplateSaveDialog(self._source_pixmap, (x, y, w, h), self)
                if dlg.exec() != QDialog.DialogCode.Accepted:
                    self._drag_start = None
                    self._drag_end = None
                    self.update()
                    return
                
                # custom_save_dir 流程中我们不需要选中的目录，因为它固定就是 self.custom_save_dir
                _, name, ox, oy = dlg.get_result()
                if not name:
                    QMessageBox.warning(self, "错误", "必须输入模板名称！")
                    continue

                base_name = name
                save_path = os.path.join(save_dir, f"{base_name}@{res_tag}.png")

                if os.path.exists(save_path):
                    reply = QMessageBox.question(
                        self, "文件已存在",
                        f"模板 \"{base_name}\" 已存在，是否覆盖？",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply != QMessageBox.StandardButton.Yes:
                        continue

                if not cropped.save(save_path, "PNG"):
                    QMessageBox.warning(self, "保存失败", f"无法写入文件：{save_path}")
                    continue  # 留在循环让用户重试

                # 保存偏移量到 meta.json
                import template_meta
                # custom_save_dir 流程，目录就是 save_dir
                template_meta.set_meta(save_dir, f"{base_name}@{res_tag}.png", offset_x=ox, offset_y=oy)
                
                # 清理图像匹配引擎缓存，使新模板立即生效
                import image_engine
                image_engine.clear_cache(save_dir)
                
                saved = True
                self.template_saved.emit(save_path)

            self._drag_start = None
            self._drag_end = None
            self.update()
            return

        # 默认流程：保存到图库目录，含目录选择
        from config import TARGETS_DIR
        main_win = self.window()
        library_tab = getattr(main_win, 'library_tab', None)
        dirs = library_tab.get_all_dirs() if library_tab else ["default"]
        current_dir = library_tab.dir_combo.currentText() if library_tab else dirs[0]

        saved = False
        while not saved:
            dlg = TemplateSaveDialog(self._source_pixmap, (x, y, w, h), self, dirs, current_dir)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                self._drag_start = None
                self._drag_end = None
                self.update()
                return
            
            selected_dir, name, ox, oy = dlg.get_result()
            if not name:
                QMessageBox.warning(self, "错误", "必须输入模板名称！")
                continue

            save_dir = os.path.join(TARGETS_DIR, selected_dir)
            os.makedirs(save_dir, exist_ok=True)
            res_tag = get_resolution_tag()
            base_name = name
            current_dir = selected_dir
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
                            base_name = f"{base_name}_{n}"
                            break
                        n += 1

            if not cropped.save(save_path, "PNG"):
                QMessageBox.warning(self, "保存失败", f"无法写入文件：{save_path}")
                continue  # 留在循环让用户重试

            # 保存偏移量到 meta.json
            import template_meta
            template_meta.set_meta(save_dir, f"{base_name}@{res_tag}.png", offset_x=ox, offset_y=oy)
            
            # 清理图像匹配引擎缓存，使新模板立即生效
            import image_engine
            image_engine.clear_cache(save_dir)
            
            saved = True
            
            self.template_saved.emit(save_path)

        # 清除选区
        self._drag_start = None
        self._drag_end = None
        self.update()

        # 通知主窗口
        if hasattr(main_win, '_append_log'):
            main_win._append_log(f"模板已保存: {save_path} ({w}×{h})")

        # 刷新图库
        if library_tab:
            library_tab.dir_combo.setCurrentText(current_dir)
            library_tab._load_images()
