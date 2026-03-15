import os
import time
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QPushButton, QWidget, QSpinBox, QFormLayout)
from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QPixmap

from gui.constants import create_font

class OffsetPreviewWidget(QWidget):
    """用于在这个组件中显示被框选区域及上下文，并可以点击确定偏移量"""
    offset_changed = pyqtSignal(int, int)

    def __init__(self, full_pixmap: QPixmap, crop_rect: tuple, parent=None):
        super().__init__(parent)
        self.full_pixmap = full_pixmap
        self.crop_x, self.crop_y, self.crop_w, self.crop_h = crop_rect
        self.cx = self.crop_x + self.crop_w / 2
        self.cy = self.crop_y + self.crop_h / 2
        
        # 默认没有偏移
        self.ox = 0
        self.oy = 0
        
        # 截取上下文区域用于显示（比如框选区域外扩 200 像素）
        pad = 200
        self.view_x1 = max(0, self.crop_x - pad)
        self.view_y1 = max(0, self.crop_y - pad)
        self.view_x2 = min(full_pixmap.width(), self.crop_x + self.crop_w + pad)
        self.view_y2 = min(full_pixmap.height(), self.crop_y + self.crop_h + pad)
        
        self.view_w = self.view_x2 - self.view_x1
        self.view_h = self.view_y2 - self.view_y1
        
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)
        
    def set_offset(self, ox, oy):
        self.ox = ox
        self.oy = oy
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._update_offset_from_mouse(event.pos())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._update_offset_from_mouse(event.pos())

    def _update_offset_from_mouse(self, pos):
        # 计算绘制区域的缩放和平移
        rect = self.rect()
        scale = min(rect.width() / self.view_w, rect.height() / self.view_h)
        dw = self.view_w * scale
        dh = self.view_h * scale
        dx = (rect.width() - dw) / 2
        dy = (rect.height() - dh) / 2
        
        # 鼠标点对应 view 中的坐标
        vx = (pos.x() - dx) / scale
        vy = (pos.y() - dy) / scale
        
        # 对应全图坐标
        fx = self.view_x1 + vx
        fy = self.view_y1 + vy
        
        # 限制不能超出全图
        fx = max(0, min(self.full_pixmap.width(), fx))
        fy = max(0, min(self.full_pixmap.height(), fy))
        
        # 计算偏移量（相对中心点）
        new_ox = int(fx - self.cx)
        new_oy = int(fy - self.cy)
        
        if new_ox != self.ox or new_oy != self.oy:
            self.ox = new_ox
            self.oy = new_oy
            self.offset_changed.emit(self.ox, self.oy)
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        painter.fillRect(self.rect(), QColor("#1a1a2e"))
        
        rect = self.rect()
        scale = min(rect.width() / self.view_w, rect.height() / self.view_h)
        if scale <= 0:
            return
            
        dw = self.view_w * scale
        dh = self.view_h * scale
        dx = (rect.width() - dw) / 2
        dy = (rect.height() - dh) / 2
        
        # 绘制上下文区域
        target_rect = QRectF(dx, dy, dw, dh)
        source_rect = QRectF(self.view_x1, self.view_y1, self.view_w, self.view_h)
        painter.drawPixmap(target_rect, self.full_pixmap, source_rect)
        
        # 绘制黑色的遮罩（暗化非框选区）
        painter.fillRect(target_rect, QColor(0, 0, 0, 150))
        
        # 抠出框选区高亮显示
        crop_target_x = dx + (self.crop_x - self.view_x1) * scale
        crop_target_y = dy + (self.crop_y - self.view_y1) * scale
        crop_target_w = self.crop_w * scale
        crop_target_h = self.crop_h * scale
        crop_target_rect = QRectF(crop_target_x, crop_target_y, crop_target_w, crop_target_h)
        
        crop_source_rect = QRectF(self.crop_x, self.crop_y, self.crop_w, self.crop_h)
        painter.drawPixmap(crop_target_rect, self.full_pixmap, crop_source_rect)
        
        # 绘制框选区边框（绿线）
        pen = QPen(QColor(0, 255, 0), 2)
        painter.setPen(pen)
        painter.drawRect(crop_target_rect)
        
        # 绘制中心准心（红线）
        center_x = dx + (self.cx - self.view_x1) * scale
        center_y = dy + (self.cy - self.view_y1) * scale
        painter.setPen(QPen(QColor(255, 50, 50), 2))
        painter.drawLine(int(center_x - 12), int(center_y), int(center_x + 12), int(center_y))
        painter.drawLine(int(center_x), int(center_y - 12), int(center_x), int(center_y + 12))
        
        # 绘制真实点击目标准心（蓝线）
        target_cx = dx + (self.cx + self.ox - self.view_x1) * scale
        target_cy = dy + (self.cy + self.oy - self.view_y1) * scale
        
        painter.setPen(QPen(QColor(50, 150, 255), 2))
        painter.drawLine(int(target_cx - 12), int(target_cy), int(target_cx + 12), int(target_cy))
        painter.drawLine(int(target_cx), int(target_cy - 12), int(target_cx), int(target_cy + 12))
        
        # 黄色虚线连接红蓝准心
        if self.ox != 0 or self.oy != 0:
            painter.setPen(QPen(QColor(255, 255, 100), 1, Qt.PenStyle.DotLine))
            painter.drawLine(int(center_x), int(center_y), int(target_cx), int(target_cy))

class TemplateSaveDialog(QDialog):
    def __init__(self, full_pixmap: QPixmap, crop_rect: tuple, parent=None, dirs=None, current_dir=None):
        super().__init__(parent)
        self.setWindowTitle("保存模板与设置点击偏移")
        self.resize(700, 550)
        self.crop_rect = crop_rect
        self.dirs = dirs
        self.current_dir = current_dir
        
        self.ox = 0
        self.oy = 0
        
        self._init_ui(full_pixmap)
        
    def _init_ui(self, full_pixmap):
        from PyQt6.QtWidgets import QComboBox
        layout = QVBoxLayout(self)
        
        # ...
        info_label = QLabel("预览区：直接在图片上【点击/拖动】即可设置实际点击的偏移坐标！\n🔴 红准心：模板匹配中心； 🔵 蓝准心：实际点击位置。")
        info_label.setStyleSheet("color: #ccc; font-size: 13px; padding: 5px;")
        layout.addWidget(info_label)
        
        self.preview = OffsetPreviewWidget(full_pixmap, self.crop_rect)
        self.preview.offset_changed.connect(self._on_preview_offset_changed)
        layout.addWidget(self.preview, stretch=1)
        
        bottom_layout = QHBoxLayout()
        form_layout = QFormLayout()
        
        self.dir_combo = None
        if self.dirs:
            self.dir_combo = QComboBox()
            self.dir_combo.addItems(self.dirs)
            if self.current_dir:
                idx = self.dir_combo.findText(self.current_dir)
                if idx >= 0:
                    self.dir_combo.setCurrentIndex(idx)
            form_layout.addRow("保存目录:", self.dir_combo)
        
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("请输入模板名称")
        self.name_edit.setMinimumWidth(200)
        self.name_edit.setFixedHeight(30)
        self.name_edit.setFont(create_font(11))
        x, y, w, h = self.crop_rect
        form_layout.addRow(f"模板名称 ({w}×{h}):", self.name_edit)
        
        offset_layout = QHBoxLayout()
        self.ox_spin = QSpinBox()
        self.ox_spin.setRange(-3000, 3000)
        self.ox_spin.valueChanged.connect(self._on_spin_changed)
        self.oy_spin = QSpinBox()
        self.oy_spin.setRange(-3000, 3000)
        self.oy_spin.valueChanged.connect(self._on_spin_changed)
        
        offset_layout.addWidget(QLabel("X:"))
        offset_layout.addWidget(self.ox_spin)
        offset_layout.addWidget(QLabel(" Y:"))
        offset_layout.addWidget(self.oy_spin)
        
        reset_btn = QPushButton("重置偏移为 0")
        reset_btn.setToolTip("清空偏移量，红蓝准心重叠")
        reset_btn.clicked.connect(lambda: (self.ox_spin.setValue(0), self.oy_spin.setValue(0)))
        offset_layout.addWidget(reset_btn)
        offset_layout.addStretch()
        
        form_layout.addRow("点击偏移:", offset_layout)
        bottom_layout.addLayout(form_layout)
        
        btn_layout = QVBoxLayout()
        ok_btn = QPushButton("保存模板 (Save)")
        ok_btn.setStyleSheet("background-color: #2b5c8f; color: white; font-weight: bold; padding: 10px; border-radius: 4px;")
        ok_btn.clicked.connect(self.accept)
        
        cancel_btn = QPushButton("取消 (Cancel)")
        cancel_btn.setStyleSheet("padding: 8px;")
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        
        bottom_layout.addStretch()
        bottom_layout.addLayout(btn_layout)
        layout.addLayout(bottom_layout)
        
        self.name_edit.setFocus()

    def _on_preview_offset_changed(self, ox, oy):
        self.ox_spin.blockSignals(True)
        self.oy_spin.blockSignals(True)
        self.ox_spin.setValue(ox)
        self.oy_spin.setValue(oy)
        self.ox_spin.blockSignals(False)
        self.oy_spin.blockSignals(False)
        self.ox = ox
        self.oy = oy

    def _on_spin_changed(self):
        self.ox = self.ox_spin.value()
        self.oy = self.oy_spin.value()
        self.preview.set_offset(self.ox, self.oy)

    def get_result(self):
        selected_dir = self.dir_combo.currentText() if self.dir_combo else None
        return selected_dir, self.name_edit.text().strip(), self.ox, self.oy
