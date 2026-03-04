"""
图库管理页：展示 targets 目录下的模板图片缩略图网格。
支持多选 + 找图测试。
"""

import os

import cv2
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QScrollArea, QMessageBox, QCheckBox,
)

from config import TARGETS_DIR, MATCH_THRESHOLD
from gui.constants import COLOR_DANGER, COLOR_PRIMARY, create_font


class ImageLibraryTab(QWidget):
    """
    图库 Tab 页：展示 targets 目录下的模板图片缩略图网格。
    支持刷新、多选找图测试、删除模板。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checkboxes = []   # [(QCheckBox, filepath), ...] 跟踪所有勾选框
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # 工具栏
        toolbar = QHBoxLayout()

        self.refresh_btn = QPushButton("🔄 刷新图库")
        self.refresh_btn.setFont(create_font())
        self.refresh_btn.setFixedSize(100, 28)
        self.refresh_btn.clicked.connect(self._load_images)
        toolbar.addWidget(self.refresh_btn)

        self.test_btn = QPushButton("🔍 找图测试")
        self.test_btn.setFont(create_font())
        self.test_btn.setFixedSize(100, 28)
        self.test_btn.setToolTip("对选中的模板在当前截图上执行找图匹配")
        self.test_btn.clicked.connect(self._on_test_match)
        toolbar.addWidget(self.test_btn)

        self.count_label = QLabel("共 0 张模板")
        self.count_label.setFont(create_font())
        toolbar.addWidget(self.count_label)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # 滚动区域 → 缩略图网格
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        self._grid_container = QWidget()
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setSpacing(8)
        scroll.setWidget(self._grid_container)
        layout.addWidget(scroll, 1)

        # 初始加载
        self._load_images()

    def _load_images(self):
        """扫描 targets 目录并生成缩略图网格（带勾选框）。"""
        # 清空
        self._checkboxes.clear()
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not os.path.isdir(TARGETS_DIR):
            self.count_label.setText("共 0 张模板")
            return

        exts = ('.png', '.jpg', '.jpeg', '.bmp')
        files = sorted([
            f for f in os.listdir(TARGETS_DIR)
            if f.lower().endswith(exts)
        ])

        self.count_label.setText(f"共 {len(files)} 张模板")

        cols = 3
        for idx, fname in enumerate(files):
            row, col = divmod(idx, cols)
            fpath = os.path.join(TARGETS_DIR, fname)

            # 卡片
            card = QWidget()
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(4, 4, 4, 4)
            card_layout.setSpacing(2)

            # 顶部：勾选框
            cb = QCheckBox()
            cb.setToolTip(f"选中 {fname} 用于找图测试")
            self._checkboxes.append((cb, fpath))
            card_layout.addWidget(cb, alignment=Qt.AlignmentFlag.AlignCenter)

            # 缩略图
            thumb = QLabel()
            pix = QPixmap(fpath)
            if not pix.isNull():
                pix = pix.scaled(100, 100,
                                 Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            thumb.setPixmap(pix)
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb.setStyleSheet("background: #2a2a3e; border-radius: 4px; padding: 2px;")
            # 点击缩略图也能切换勾选
            thumb.mousePressEvent = lambda _, _cb=cb: _cb.setChecked(not _cb.isChecked())
            card_layout.addWidget(thumb)

            # 文件名
            name_label = QLabel(os.path.splitext(fname)[0])
            name_label.setFont(create_font(8))
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_label.setWordWrap(True)
            card_layout.addWidget(name_label)

            # 删除按钮
            del_btn = QPushButton("✕")
            del_btn.setFixedSize(24, 24)
            del_btn.setToolTip(f"删除 {fname}")
            del_btn.setStyleSheet(
                f"background: {COLOR_DANGER}; color: white; "
                "border: none; border-radius: 12px; font-size: 12px;"
            )
            del_btn.clicked.connect(lambda _, p=fpath: self._delete_image(p))
            card_layout.addWidget(del_btn, alignment=Qt.AlignmentFlag.AlignCenter)

            self._grid_layout.addWidget(card, row, col)

    def _get_selected_paths(self):
        """获取所有勾选的模板文件路径。"""
        return [fpath for cb, fpath in self._checkboxes if cb.isChecked()]

    def _on_test_match(self):
        """对选中的模板在当前截图上执行找图匹配。"""
        selected = self._get_selected_paths()
        if not selected:
            QMessageBox.information(self, "提示", "请先勾选要测试的模板图片")
            return

        # 获取主窗口的截图控件
        main_win = self.window()
        screenshot_widget = getattr(main_win, 'screenshot_widget', None)
        if screenshot_widget is None or screenshot_widget._source_image is None:
            QMessageBox.information(self, "提示", "请先截图或开启实时同步")
            return

        # QImage → OpenCV BGR
        q_img = screenshot_widget._source_image
        q_img_rgb = q_img.convertToFormat(QImage.Format.Format_RGB888)
        w, h = q_img_rgb.width(), q_img_rgb.height()
        ptr = q_img_rgb.bits()
        ptr.setsize(h * w * 3)
        arr = np.array(ptr).reshape(h, w, 3)
        screen_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

        # 加载选中的模板
        templates = []
        for fpath in selected:
            img_array = np.fromfile(fpath, dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if img is not None:
                name = os.path.splitext(os.path.basename(fpath))[0]
                templates.append((name, img))

        if not templates:
            QMessageBox.warning(self, "错误", "所选模板均无法读取")
            return

        # 执行匹配
        from image_engine import match_all
        results = match_all(screen_bgr, templates)

        # 在预览区显示结果（清除 Y 偏移，找图测试不需要购买按钮准心）
        screenshot_widget.set_y_offset(0)
        screenshot_widget.update_matches(results)

        # 在日志区输出结果
        log_fn = getattr(main_win, '_append_log', None)
        if log_fn:
            if results:
                log_fn(f"找图测试: 匹配到 {len(results)} 个结果")
                for name, cx, cy, score in results:
                    log_fn(f"  ▸ {name} → ({cx}, {cy}) 匹配度: {score:.3f}")
            else:
                log_fn("找图测试: 未匹配到任何结果")

    def _delete_image(self, fpath):
        """删除模板图片。"""
        fname = os.path.basename(fpath)
        reply = QMessageBox.question(
            self, "确认删除", f"确定要删除模板 \"{fname}\" 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(fpath)
            except OSError:
                pass
            # 清除缓存后刷新
            from image_engine import clear_cache
            clear_cache(TARGETS_DIR)
            self._load_images()
