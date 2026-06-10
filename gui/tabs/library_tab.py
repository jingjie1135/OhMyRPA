"""
图库管理页：展示 targets/ 下子目录中的模板图片缩略图网格。
支持多目录组织、多选找图测试、批量删除。
"""

import os
import re

import cv2
import numpy as np
from PyQt6.QtCore import Qt, QRect, QSize, QPoint
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLayout, QSizePolicy,
    QLabel, QPushButton, QScrollArea, QMessageBox,
    QCheckBox, QComboBox, QInputDialog,
)

from config import TARGETS_DIR
from gui.constants import COLOR_DANGER, COLOR_PRIMARY, create_font

# 缩略图固定尺寸（像素）
THUMB_SIZE = 70
# 卡片实际尺寸（包含边距）
CARD_W = THUMB_SIZE + 8
CARD_H = THUMB_SIZE + 28
CARD_SPACING = 2


class FlowLayout(QLayout):
    """
    流式布局：根据可用宽度自动换行，左上角对齐。
    适用于图库缩略图网格。
    """

    def __init__(self, parent=None, spacing=CARD_SPACING):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _do_layout(self, rect, test_only):
        """计算每个元素位置，返回所需总高度。"""
        x = rect.x()
        y = rect.y()
        row_height = 0

        for item in self._items:
            item_size = item.sizeHint()
            # 超过行宽则换行
            if x + item_size.width() > rect.right() + 1 and row_height > 0:
                x = rect.x()
                y += row_height + self._spacing
                row_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item_size))

            x += item_size.width() + self._spacing
            row_height = max(row_height, item_size.height())

        return y + row_height - rect.y()


def _display_name(filename):
    """
    从文件名提取显示名称：去掉扩展名和 @WxH 分辨率后缀。
    例: 'icon@1280x720.png' → 'icon'
    """
    name = os.path.splitext(filename)[0]
    name = re.sub(r'@\d+x\d+$', '', name)
    return name


class _ImageCard(QWidget):
    """
    单张模板图片卡片：固定尺寸缩略图 + 左上角勾选框 + 底部名称。
    """

    def __init__(self, fpath, parent=None):
        super().__init__(parent)
        self.fpath = fpath
        self.setFixedSize(THUMB_SIZE + 4, THUMB_SIZE + 30)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(1)

        # 图片容器（用于叠加勾选框）
        img_container = QWidget()
        img_container.setFixedSize(THUMB_SIZE + 4, THUMB_SIZE + 4)
        img_container.setStyleSheet(
            "background: #2a2a3e; border-radius: 4px;"
        )

        # 缩略图
        thumb = QLabel(img_container)
        pix = QPixmap(fpath)
        if not pix.isNull():
            pix = pix.scaled(THUMB_SIZE, THUMB_SIZE,
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        thumb.setPixmap(pix)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setGeometry(2, 2, THUMB_SIZE, THUMB_SIZE)

        # 勾选框（叠加在图片左上角，白底确保暗背景上可见）
        self.checkbox = QCheckBox(img_container)
        self.checkbox.setGeometry(4, 4, 18, 18)
        self.checkbox.setStyleSheet("""
            QCheckBox::indicator {
                width: 15px; height: 15px;
                background: white;
                border: 1px solid #999;
            }
            QCheckBox::indicator:checked {
                image: url(none);
                background: #409eff;
                border-color: #409eff;
            }
        """)

        layout.addWidget(img_container, alignment=Qt.AlignmentFlag.AlignCenter)

        # 文件名（去掉分辨率后缀）
        fname = os.path.basename(fpath)
        name_label = QLabel(_display_name(fname))
        name_label.setFont(create_font(7))
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setWordWrap(True)
        name_label.setMaximumHeight(20)
        layout.addWidget(name_label)

    def mousePressEvent(self, event):
        """点击卡片任意区域切换勾选。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.checkbox.setChecked(not self.checkbox.isChecked())


class ImageLibraryTab(QWidget):
    """
    图库 Tab 页：支持 targets/ 下多目录管理。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards = []  # [_ImageCard, ...]
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # ===== 目录选择栏 =====
        dir_bar = QHBoxLayout()

        dir_label = QLabel("目录:")
        dir_label.setFont(create_font(9, bold=True))
        dir_bar.addWidget(dir_label)

        self.dir_combo = QComboBox()
        self.dir_combo.setFont(create_font())
        self.dir_combo.setMinimumWidth(100)
        self.dir_combo.currentIndexChanged.connect(self._load_images)
        dir_bar.addWidget(self.dir_combo, 1)

        self.new_dir_btn = QPushButton("＋ 新建")
        self.new_dir_btn.setFont(create_font())
        self.new_dir_btn.setFixedSize(70, 26)
        self.new_dir_btn.setToolTip("在 targets/ 下新建子目录")
        self.new_dir_btn.clicked.connect(self._on_new_dir)
        dir_bar.addWidget(self.new_dir_btn)

        layout.addLayout(dir_bar)

        # ===== 工具栏 =====
        toolbar = QHBoxLayout()

        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.setFont(create_font())
        self.refresh_btn.setFixedSize(80, 28)
        self.refresh_btn.clicked.connect(self._refresh_all)
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

        # 删除选中（放在工具栏最右边）
        self.delete_btn = QPushButton("🗑 删除选中")
        self.delete_btn.setFont(create_font())
        self.delete_btn.setFixedSize(100, 28)
        self.delete_btn.setToolTip("删除所有勾选的模板图片")
        self.delete_btn.setStyleSheet(
            f"color: {COLOR_DANGER}; border-color: {COLOR_DANGER};"
        )
        self.delete_btn.clicked.connect(self._on_delete_selected)
        toolbar.addWidget(self.delete_btn)

        layout.addLayout(toolbar)

        # ===== 滚动区域 → 流式布局（自适应列数，左上对齐） =====
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        self._grid_container = QWidget()
        self._flow_layout = FlowLayout(self._grid_container)
        scroll.setWidget(self._grid_container)
        layout.addWidget(scroll, 1)

        # 初始扫描
        self._refresh_dirs()

    # ==================== 目录管理 ====================

    def _refresh_dirs(self):
        """扫描 targets/ 下的子目录。"""
        os.makedirs(TARGETS_DIR, exist_ok=True)
        self.dir_combo.blockSignals(True)
        prev = self.dir_combo.currentText()
        self.dir_combo.clear()

        subdirs = sorted([
            d for d in os.listdir(TARGETS_DIR)
            if os.path.isdir(os.path.join(TARGETS_DIR, d))
        ])

        if not subdirs:
            os.makedirs(os.path.join(TARGETS_DIR, "default"), exist_ok=True)
            subdirs = ["default"]

        for d in subdirs:
            self.dir_combo.addItem(d)

        idx = self.dir_combo.findText(prev)
        if idx >= 0:
            self.dir_combo.setCurrentIndex(idx)

        self.dir_combo.blockSignals(False)
        self._load_images()

    def _on_new_dir(self):
        """新建子目录。"""
        name, ok = QInputDialog.getText(self, "新建图库目录", "请输入目录名称:")
        if not ok or not name.strip():
            return
        # 过滤路径分隔符与遍历片段，仅保留单层目录名
        dir_name = os.path.basename(name.strip().strip("/\\"))
        if not dir_name or dir_name == "..":
            QMessageBox.warning(self, "提示", "目录名称无效，请勿包含路径分隔符。")
            return
        dir_path = os.path.join(TARGETS_DIR, dir_name)
        # 路径前缀校验：确保最终目录仍在 TARGETS_DIR 内
        targets_abs = os.path.abspath(TARGETS_DIR)
        if not os.path.abspath(dir_path).startswith(targets_abs + os.sep):
            QMessageBox.warning(self, "提示", "目录名称无效。")
            return
        if os.path.exists(dir_path):
            QMessageBox.warning(self, "提示", f"目录 \"{dir_name}\" 已存在")
            return
        os.makedirs(dir_path, exist_ok=True)
        self._refresh_dirs()
        idx = self.dir_combo.findText(dir_name)
        if idx >= 0:
            self.dir_combo.setCurrentIndex(idx)

    def get_current_dir(self):
        """获取当前选中的完整目录路径。"""
        sub = self.dir_combo.currentText()
        if not sub:
            return TARGETS_DIR
        return os.path.join(TARGETS_DIR, sub)

    def get_all_dirs(self):
        """获取所有子目录名称列表。"""
        return [self.dir_combo.itemText(i) for i in range(self.dir_combo.count())]

    def _refresh_all(self):
        self._refresh_dirs()

    # ==================== 图片加载 ====================

    def _load_images(self):
        """扫描当前目录并生成固定尺寸的缩略图卡片（流式布局）。"""
        self._cards.clear()
        while self._flow_layout.count():
            item = self._flow_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        cur_dir = self.get_current_dir()
        if not os.path.isdir(cur_dir):
            self.count_label.setText("共 0 张模板")
            return

        exts = ('.png', '.jpg', '.jpeg', '.bmp')
        files = sorted([
            f for f in os.listdir(cur_dir)
            if f.lower().endswith(exts)
        ])

        self.count_label.setText(f"共 {len(files)} 张模板")

        for fname in files:
            fpath = os.path.join(cur_dir, fname)
            card = _ImageCard(fpath)
            self._cards.append(card)
            self._flow_layout.addWidget(card)

    # ==================== 选中操作 ====================

    def _get_selected_paths(self):
        """获取所有勾选的模板文件路径。"""
        return [c.fpath for c in self._cards if c.checkbox.isChecked()]

    def _on_delete_selected(self):
        """批量删除选中的模板图片。"""
        selected = self._get_selected_paths()
        if not selected:
            QMessageBox.information(self, "提示", "请先勾选要删除的图片")
            return

        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除选中的 {len(selected)} 张模板图片吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        for fpath in selected:
            try:
                os.remove(fpath)
            except OSError:
                pass

        from image_engine import clear_cache
        clear_cache()
        self._load_images()

    # ==================== 找图测试 ====================

    def _on_test_match(self):
        """对选中的模板在当前截图上执行找图匹配。"""
        selected = self._get_selected_paths()
        if not selected:
            QMessageBox.information(self, "提示", "请先勾选要测试的模板图片")
            return

        main_win = self.window()
        screenshot_widget = getattr(main_win, 'screenshot_widget', None)
        if screenshot_widget is None or screenshot_widget.get_source_image() is None:
            QMessageBox.information(self, "提示", "请先截图或开启实时同步")
            return

        # QImage → OpenCV BGR（注意 QImage 每行按 4 字节对齐，必须按 stride 裁切）
        q_img = screenshot_widget.get_source_image()
        q_img_rgb = q_img.convertToFormat(QImage.Format.Format_RGB888)
        w, h = q_img_rgb.width(), q_img_rgb.height()
        ptr = q_img_rgb.bits()
        ptr.setsize(q_img_rgb.sizeInBytes())
        stride = q_img_rgb.bytesPerLine()
        # .copy() 确保数组拥有独立缓冲，不悬挂引用 QImage 的内存
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, stride)[:, :w*3].reshape(h, w, 3).copy()
        screen_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

        # 加载选中的模板
        templates = []
        for fpath in selected:
            img_array = np.fromfile(fpath, dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if img is not None:
                name = _display_name(os.path.basename(fpath))
                templates.append((name, img))

        if not templates:
            QMessageBox.warning(self, "错误", "所选模板均无法读取")
            return

        from image_engine import match_all
        results = match_all(screen_bgr, templates)

        screenshot_widget.set_y_offset(0)
        screenshot_widget.update_matches(results)

        log_fn = getattr(main_win, '_append_log', None)
        if log_fn:
            if results:
                log_fn(f"找图测试: 匹配到 {len(results)} 个结果")
                for name, cx, cy, score in results:
                    log_fn(f"  ▸ {name} → ({cx}, {cy}) 匹配度: {score:.3f}")
            else:
                log_fn("找图测试: 未匹配到任何结果")
