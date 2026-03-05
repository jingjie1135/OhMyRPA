"""
多区域框选控件：基于 ScreenshotWidget 设计，支持累积多区域框选。
用于转换流程 Step 2 的批量抠图。

特性：
- 显示截图 + 叠加点击位置标记（小圆点）
- 拖拽框选多个矩形区域，每个区域独立保存
- 每次框选完成后触发 region_completed 信号
- 支持撤销最近一次框选 (Ctrl+Z)
- 右键点击区域可删除该区域
"""

import os
from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QImage, QPixmap
from PyQt6.QtWidgets import QWidget, QSizePolicy

from gui.constants import COLOR_SUCCESS, COLOR_DISABLED, create_font


# 区域颜色池（循环使用）
_REGION_COLORS = [
    QColor(64, 158, 255, 60),   # 蓝
    QColor(255, 165, 0, 60),    # 橙
    QColor(50, 205, 50, 60),    # 绿
    QColor(255, 80, 80, 60),    # 红
    QColor(180, 80, 255, 60),   # 紫
    QColor(0, 200, 200, 60),    # 青
]

_REGION_BORDER_COLORS = [
    QColor(64, 158, 255),
    QColor(255, 165, 0),
    QColor(50, 205, 50),
    QColor(255, 80, 80),
    QColor(180, 80, 255),
    QColor(0, 200, 200),
]


class MultiRegionWidget(QWidget):
    """
    多区域框选截图控件。
    
    Signals:
        region_completed(int, int, int, int, int):
            区域框选完成 — (region_index, x, y, w, h) 原图坐标
    """
    
    # 区域完成信号：(区域索引, x, y, w, h)
    region_completed = pyqtSignal(int, int, int, int, int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_image = None    # 原始 QImage
        self._source_pixmap = None   # QPixmap 缓存
        
        # 已完成的区域列表：[(x, y, w, h), ...]
        self._regions = []
        
        # 点击位置标记列表：[(x, y, label), ...]
        self._click_markers = []
        
        # 拖拽状态
        self._drag_start = None
        self._drag_end = None
        self._is_dragging = False
        
        # 鼠标位置（原图坐标，用于准心显示）
        self._mouse_pos = None
        
        self.setMinimumSize(300, 400)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
    
    # =================== 公共 API ===================
    
    def update_screenshot(self, q_image):
        """设置截图"""
        if q_image is None or q_image.isNull():
            return
        self._source_image = q_image
        self._source_pixmap = QPixmap.fromImage(q_image)
        self.update()
    
    def set_click_markers(self, markers: list):
        """
        设置点击位置标记。
        
        Args:
            markers: [(x, y, label), ...] 原图坐标
        """
        self._click_markers = markers
        self.update()
    
    def get_regions(self) -> list:
        """返回所有已框选区域列表：[(x, y, w, h), ...]"""
        return list(self._regions)
    
    def clear_regions(self):
        """清空所有框选区域"""
        self._regions.clear()
        self.update()
    
    def undo_last_region(self):
        """撤销最后一个框选区域"""
        if self._regions:
            self._regions.pop()
            self.update()
    
    def get_region_at_point(self, orig_x: int, orig_y: int) -> int:
        """
        查找包含指定原图坐标点的区域索引。
        
        Returns:
            int: 区域索引，未找到返回 -1
        """
        for i, (rx, ry, rw, rh) in enumerate(self._regions):
            if rx <= orig_x <= rx + rw and ry <= orig_y <= ry + rh:
                return i
        return -1
    
    # =================== 布局计算 ===================
    
    def _calc_layout(self):
        """计算图片在控件中的显示布局（复用 ScreenshotWidget 逻辑）"""
        if self._source_image is None:
            return None
        
        img_w = self._source_image.width()
        img_h = self._source_image.height()
        if img_w <= 0 or img_h <= 0:
            return None
        
        widget_w = self.width()
        widget_h = self.height()
        
        scale = min((widget_w - 4) / img_w, (widget_h - 4) / img_h)
        display_w = img_w * scale
        display_h = img_h * scale
        
        offset_x = (widget_w - display_w) / 2.0
        offset_y = (widget_h - display_h) / 2.0
        
        return {
            'offset_x': offset_x, 'offset_y': offset_y,
            'display_w': display_w, 'display_h': display_h,
            'scale': scale, 'img_w': img_w, 'img_h': img_h,
        }
    
    def _widget_to_original(self, wx, wy):
        """控件坐标 → 原图坐标"""
        layout = self._calc_layout()
        if layout is None:
            return None
        
        rel_x = wx - layout['offset_x']
        rel_y = wy - layout['offset_y']
        
        if rel_x < 0 or rel_y < 0 or rel_x > layout['display_w'] or rel_y > layout['display_h']:
            return None
        
        return int(rel_x / layout['scale']), int(rel_y / layout['scale'])
    
    # =================== 绘制 ===================
    
    def paintEvent(self, event):
        """绘制：背景 → 截图 → 已完成区域 → 当前拖拽区域 → 点击标记 → 准心"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        # 深色背景
        painter.fillRect(self.rect(), QColor("#1a1a2e"))
        
        layout = self._calc_layout()
        if layout is None:
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
        
        # 绘制截图
        target_rect = QRectF(ox, oy, dw, dh)
        source_rect = QRectF(0, 0, layout['img_w'], layout['img_h'])
        if self._source_pixmap and not self._source_pixmap.isNull():
            painter.drawPixmap(target_rect, self._source_pixmap, source_rect)
        
        # 绘制已完成的区域（带颜色编号）
        for i, (rx, ry, rw, rh) in enumerate(self._regions):
            color_idx = i % len(_REGION_COLORS)
            
            sx = ox + rx * scale
            sy = oy + ry * scale
            sw = rw * scale
            sh = rh * scale
            
            rect = QRectF(sx, sy, sw, sh)
            painter.setBrush(_REGION_COLORS[color_idx])
            painter.setPen(QPen(_REGION_BORDER_COLORS[color_idx], 2))
            painter.drawRect(rect)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            
            # 区域编号标签
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(create_font(10, bold=True))
            painter.drawText(int(sx + 4), int(sy + 16), f"#{i+1}")
            
            # 尺寸标注
            painter.setFont(create_font(8))
            painter.drawText(int(sx + 4), int(sy + sh - 4), f"{rw}×{rh}")
        
        # 绘制当前拖拽中的区域（蓝色虚线）
        if self._is_dragging and self._drag_start and self._drag_end:
            x1, y1 = self._drag_start
            x2, y2 = self._drag_end
            sx1 = ox + x1 * scale
            sy1 = oy + y1 * scale
            sx2 = ox + x2 * scale
            sy2 = oy + y2 * scale
            
            rect = QRectF(min(sx1, sx2), min(sy1, sy2),
                          abs(sx2 - sx1), abs(sy2 - sy1))
            painter.setBrush(QColor(64, 158, 255, 40))
            painter.setPen(QPen(QColor(64, 158, 255), 2, Qt.PenStyle.DashLine))
            painter.drawRect(rect)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            
            rw = abs(x2 - x1)
            rh = abs(y2 - y1)
            if rw > 5 and rh > 5:
                painter.setPen(QColor(255, 255, 255))
                painter.setFont(create_font(8))
                painter.drawText(int(min(sx1, sx2)), int(min(sy1, sy2) - 4),
                                 f"{rw}×{rh}")
        
        # 绘制点击位置标记（小圆点 + 标签）
        for mx, my, label in self._click_markers:
            smx = ox + mx * scale
            smy = oy + my * scale
            
            # 判断该标记是否在某个已框选区域内
            region_idx = self.get_region_at_point(mx, my)
            if region_idx >= 0:
                # 已匹配：使用对应区域颜色
                color_idx = region_idx % len(_REGION_BORDER_COLORS)
                dot_color = _REGION_BORDER_COLORS[color_idx]
            else:
                # 未匹配：白色
                dot_color = QColor(255, 255, 255)
            
            # 圆点
            painter.setBrush(dot_color)
            painter.setPen(QPen(QColor(0, 0, 0), 1))
            painter.drawEllipse(int(smx) - 4, int(smy) - 4, 8, 8)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            
            # 标签
            painter.setPen(dot_color)
            painter.setFont(create_font(7))
            painter.drawText(int(smx + 6), int(smy + 3), label)
        
        # 鼠标准心（非拖拽时）
        if self._mouse_pos and not self._is_dragging:
            mx_o, my_o = self._mouse_pos
            smx = ox + mx_o * scale
            smy = oy + my_o * scale
            
            pen_green = QPen(QColor(COLOR_SUCCESS), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen_green)
            painter.drawLine(int(smx), int(oy), int(smx), int(oy + dh))
            painter.drawLine(int(ox), int(smy), int(ox + dw), int(smy))
        
        painter.end()
    
    # =================== 鼠标事件 ===================
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            # 右键删除区域
            result = self._widget_to_original(event.position().x(), event.position().y())
            if result:
                idx = self.get_region_at_point(result[0], result[1])
                if idx >= 0:
                    self._regions.pop(idx)
                    self.update()
            return
        
        if event.button() != Qt.MouseButton.LeftButton:
            return
        result = self._widget_to_original(event.position().x(), event.position().y())
        if result is None:
            return
        
        self._drag_start = result
        self._drag_end = result
        self._is_dragging = True
        self._mouse_pos = result
        self.update()
    
    def mouseMoveEvent(self, event):
        result = self._widget_to_original(event.position().x(), event.position().y())
        if result is None:
            return
        
        self._mouse_pos = result
        if self._is_dragging:
            self._drag_end = result
        self.update()
    
    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self._is_dragging:
            return
        
        self._is_dragging = False
        result = self._widget_to_original(event.position().x(), event.position().y())
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
                idx = len(self._regions)
                self._regions.append((rx, ry, rw, rh))
                self.region_completed.emit(idx, rx, ry, rw, rh)
        
        # 清除拖拽状态（区域已保存到列表）
        self._drag_start = None
        self._drag_end = None
        self.update()
    
    def keyPressEvent(self, event):
        """Ctrl+Z 撤销最后一个区域"""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Z:
            self.undo_last_region()
