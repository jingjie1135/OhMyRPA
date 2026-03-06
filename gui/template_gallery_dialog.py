"""
模板图库管理控件（嵌入式，非弹窗）。

嵌入到循环脚本 Tab 的属性面板中，复刻主图库的 FlowLayout 网格。
利用主窗口已有的 ScreenshotWidget 进行截图框选添加模板。
"""

import os
import re
import shutil

from PyQt6.QtCore import Qt, QRect, QSize, QPoint, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLayout, QSizePolicy,
    QLabel, QPushButton, QScrollArea, QMessageBox,
    QCheckBox, QFileDialog,
)

from gui.constants import COLOR_DANGER, create_font

# 缩略图固定尺寸（与主图库一致）
THUMB_SIZE = 70
CARD_SPACING = 2


# =================== FlowLayout ===================

class _FlowLayout(QLayout):
    """流式布局：根据可用宽度自动换行，左上角对齐。"""

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
        x = rect.x()
        y = rect.y()
        row_height = 0
        for item in self._items:
            item_size = item.sizeHint()
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
    """去掉扩展名和 @WxH 分辨率后缀。"""
    name = os.path.splitext(filename)[0]
    name = re.sub(r'@\d+x\d+$', '', name)
    return name


# =================== ImageCard ===================

class _ImageCard(QWidget):
    """单张模板图片卡片：缩略图 + 勾选框 + 名称。"""

    def __init__(self, fpath, parent=None):
        super().__init__(parent)
        self.fpath = fpath
        self.filename = os.path.basename(fpath)
        self.setFixedSize(THUMB_SIZE + 4, THUMB_SIZE + 30)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(1)

        # 图片容器
        img_container = QWidget()
        img_container.setFixedSize(THUMB_SIZE + 4, THUMB_SIZE + 4)
        img_container.setStyleSheet("background: #2a2a3e; border-radius: 4px;")

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

        # 勾选框
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

        # 名称标签
        name_label = QLabel(_display_name(self.filename))
        name_label.setFont(create_font(7))
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setWordWrap(True)
        name_label.setMaximumHeight(20)
        layout.addWidget(name_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.checkbox.setChecked(not self.checkbox.isChecked())


# =================== 嵌入式图库控件 ===================

class TemplateGalleryWidget(QWidget):
    """
    嵌入式模板图库控件，用于替换属性面板内容。

    信号:
        closed(list): 关闭时发出，携带更新后的模板列表
    """
    closed = pyqtSignal(list)

    def __init__(self, pictures_dir: str, current_templates: list, parent=None):
        super().__init__(parent)
        self.pictures_dir = pictures_dir
        self._original_templates = current_templates or []
        self._cards = []
        # 保存关联的 ScreenshotWidget 引用（用于恢复 custom_save_dir）
        self._screenshot_widget = None
        self._prev_save_dir = None

        self._init_ui()
        self._load_gallery()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(4, 4, 4, 4)

        # ===== 顶部：标题 + 返回按钮 =====
        top_bar = QHBoxLayout()

        title = QLabel("📂 模板图库管理")
        title.setFont(create_font(10, bold=True))
        top_bar.addWidget(title)
        top_bar.addStretch()

        back_btn = QPushButton("← 返回")
        back_btn.setFont(create_font())
        back_btn.setFixedSize(70, 28)
        back_btn.setToolTip("返回属性面板")
        back_btn.clicked.connect(self._on_close)
        top_bar.addWidget(back_btn)

        layout.addLayout(top_bar)

        # ===== 提示 =====
        hint = QLabel("📷 在左侧预览区框选区域可直接添加模板")
        hint.setStyleSheet("color: #555; padding: 4px; background: #f0f4f8; border-radius: 4px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # ===== 工具栏 =====
        toolbar = QHBoxLayout()

        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.setFont(create_font())
        self.refresh_btn.setFixedSize(70, 28)
        self.refresh_btn.clicked.connect(self._load_gallery)
        toolbar.addWidget(self.refresh_btn)

        self.count_label = QLabel("共 0 张模板")
        self.count_label.setFont(create_font())
        toolbar.addWidget(self.count_label)

        toolbar.addStretch()

        # 添加图片
        add_btn = QPushButton("➕ 添加")
        add_btn.setFont(create_font())
        add_btn.setFixedSize(70, 28)
        add_btn.setToolTip("从文件系统选择图片添加")
        add_btn.clicked.connect(self._add_from_file)
        toolbar.addWidget(add_btn)

        # 删除选中
        del_btn = QPushButton("🗑 删除")
        del_btn.setFont(create_font())
        del_btn.setFixedSize(70, 28)
        del_btn.setStyleSheet(f"color: {COLOR_DANGER}; border-color: {COLOR_DANGER};")
        del_btn.clicked.connect(self._delete_selected)
        toolbar.addWidget(del_btn)

        layout.addLayout(toolbar)

        # ===== 滚动区域 → 流式布局 =====
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        self._grid_container = QWidget()
        self._flow_layout = _FlowLayout(self._grid_container)
        scroll.setWidget(self._grid_container)
        layout.addWidget(scroll, 1)

    def bind_screenshot_widget(self, sw):
        """绑定主窗口的 ScreenshotWidget，设置截图保存目录"""
        self._screenshot_widget = sw
        self._prev_save_dir = sw.custom_save_dir
        sw.custom_save_dir = self.pictures_dir
        sw.template_saved.connect(self._on_template_saved)

    def _unbind_screenshot_widget(self):
        """恢复 ScreenshotWidget 的原始保存目录"""
        if self._screenshot_widget:
            try:
                self._screenshot_widget.template_saved.disconnect(self._on_template_saved)
            except Exception:
                pass
            self._screenshot_widget.custom_save_dir = self._prev_save_dir
            self._screenshot_widget = None

    def _on_template_saved(self, save_path):
        """截图保存后自动刷新图库"""
        self._load_gallery()

    # ==================== 图库加载 ====================

    def _load_gallery(self):
        """扫描 Pictures/ 目录，生成缩略图卡片"""
        self._cards.clear()
        while self._flow_layout.count():
            item = self._flow_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not os.path.isdir(self.pictures_dir):
            self.count_label.setText("共 0 张模板")
            return

        # 构建已有模板的文件名集合
        enabled_set = {t.get("template", "") for t in self._original_templates}

        exts = ('.png', '.jpg', '.jpeg', '.bmp')
        files = sorted([
            f for f in os.listdir(self.pictures_dir)
            if f.lower().endswith(exts)
        ])

        self.count_label.setText(f"共 {len(files)} 张模板")

        for fname in files:
            fpath = os.path.join(self.pictures_dir, fname)
            card = _ImageCard(fpath)
            # 在原模板列表中的勾选，新添加的也默认勾选
            if enabled_set:
                card.checkbox.setChecked(fname in enabled_set)
            else:
                card.checkbox.setChecked(True)
            self._cards.append(card)
            self._flow_layout.addWidget(card)

    # ==================== 添加/删除 ====================

    def _add_from_file(self):
        """从文件系统选择图片添加"""
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择模板图片", "",
            "图片文件 (*.png *.jpg *.bmp);;所有文件 (*)"
        )
        if not files:
            return
        os.makedirs(self.pictures_dir, exist_ok=True)
        added = 0
        for src in files:
            filename = os.path.basename(src)
            if not filename.lower().endswith(".png"):
                filename = os.path.splitext(filename)[0] + ".png"
            dst = os.path.join(self.pictures_dir, filename)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
                added += 1
        if added > 0:
            self._load_gallery()

    def _delete_selected(self):
        """删除勾选的模板图片"""
        selected = [c for c in self._cards if c.checkbox.isChecked()]
        if not selected:
            QMessageBox.information(self, "提示", "请先勾选要删除的图片")
            return
        ret = QMessageBox.question(
            self, "确认删除",
            f"确定删除 {len(selected)} 张模板图片？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        for card in selected:
            try:
                os.remove(card.fpath)
            except OSError:
                pass
        from image_engine import clear_cache
        clear_cache()
        self._load_gallery()

    # ==================== 关闭/返回 ====================

    def _on_close(self):
        """返回按钮：构建模板列表并发出 closed 信号"""
        self._unbind_screenshot_widget()
        templates = self._build_template_list()
        self.closed.emit(templates)

    def _build_template_list(self):
        """构建更新后的模板列表（仅包含勾选的）"""
        orig_lookup = {t.get("template", ""): t for t in self._original_templates}
        templates = []
        for card in self._cards:
            if not card.checkbox.isChecked():
                continue
            fname = card.filename
            if fname in orig_lookup:
                # 保留原有配置（含偏移量）
                templates.append(orig_lookup[fname].copy())
            else:
                # 尝试从 meta.json 恢复偏移量
                ox, oy = 0, 0
                try:
                    import template_meta
                    meta = template_meta.get(self.pictures_dir, fname)
                    if meta.get("offset_x") is not None:
                        ox = meta["offset_x"]
                    if meta.get("offset_y") is not None:
                        oy = meta["offset_y"]
                except Exception:
                    pass
                templates.append({
                    "template": fname,
                    "threshold": 0.9,
                    "offset_x": ox,
                    "offset_y": oy,
                })
        return templates
