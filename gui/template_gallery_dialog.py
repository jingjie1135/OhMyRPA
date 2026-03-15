"""
模板图库管理控件（嵌入式，非弹窗）。

嵌入到脚本 Tab 的属性面板中，复刻主图库的 FlowLayout 网格。
支持两种模式：
  - "multi" 多选模式（multi_match 指令用）
  - "single" 单选模式（find_and_tap / wait_image 指令用）
内置找图测试按钮，可直接在当前截图上匹配选中的模板。
"""

import os
import re

import cv2
import numpy as np

from PyQt6.QtCore import Qt, QRect, QSize, QPoint, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLayout, QSizePolicy,
    QLabel, QPushButton, QScrollArea, QMessageBox,
    QCheckBox, QFileDialog, QRadioButton,
)

from gui.constants import COLOR_DANGER, create_font

# 缩略图固定尺寸
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
    """单张模板图片卡片：缩略图 + 选择控件 + 名称。"""

    # 卡片被点击时发出信号（仅单选模式需要）
    clicked = pyqtSignal()

    def __init__(self, fpath, mode="multi", parent=None):
        super().__init__(parent)
        self.fpath = fpath
        self.filename = os.path.basename(fpath)
        self._mode = mode
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

        # 选择控件：多选用 QCheckBox，单选用 QRadioButton
        # 选择控件：多选用 QCheckBox，单选用 QRadioButton
        if mode == "single":
            self.selector = QRadioButton(img_container)
            self.selector.setGeometry(4, 4, 18, 18)
            self.selector.setStyleSheet("""
                QRadioButton::indicator {
                    width: 15px; height: 15px;
                    background: white;
                    border: 1px solid #999;
                    border-radius: 8px;
                }
                QRadioButton::indicator:checked {
                    background: #409eff;
                    border-color: #409eff;
                }
            """)
        else:
            self.selector = QCheckBox(img_container)
            self.selector.setGeometry(4, 4, 18, 18)
            self.selector.setStyleSheet("""
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

    def is_checked(self):
        """统一接口：获取是否选中"""
        if self._mode == "single":
            return self.selector.isChecked()
        return self.selector.isChecked()

    def set_checked(self, checked):
        """统一接口：设置选中状态"""
        self.selector.setChecked(checked)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._mode == "single":
                # 单选模式：通过信号让父级处理互斥
                self.clicked.emit()
            else:
                self.selector.setChecked(not self.selector.isChecked())


# =================== 嵌入式图库控件 ===================

class TemplateGalleryWidget(QWidget):
    """
    嵌入式模板图库控件，用于替换属性面板内容。

    mode:
        "multi" — 多选模式（checkbox），返回文件名列表
        "single" — 单选模式（radio），返回单元素列表

    信号:
        closed(list): 关闭时发出，携带更新后的模板列表
    """
    closed = pyqtSignal(list)

    def __init__(self, pictures_dir: str, current_templates: list,
                 mode: str = "multi", parent=None):
        super().__init__(parent)
        self.pictures_dir = pictures_dir
        self._original_templates = current_templates or []
        self._mode = mode
        self._cards = []
        # 保存关联的 ScreenshotWidget 引用
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

        if self._mode == "single":
            title_text = "📂 选择模板图片"
        else:
            title_text = "📂 模板图库管理"
        title = QLabel(title_text)
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
        hint_text = "📷 在左侧预览区框选区域可直接添加模板"
        if self._mode == "single":
            hint_text = "📷 点击选择一张模板，或在左侧预览区框选添加"
        hint = QLabel(hint_text)
        hint.setStyleSheet("color: #555; padding: 4px; background: #f0f4f8; border-radius: 4px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # ===== 工具栏 =====
        toolbar = QHBoxLayout()

        self.refresh_btn = QPushButton("🔄")
        self.refresh_btn.setFont(create_font())
        self.refresh_btn.setFixedSize(36, 28)
        self.refresh_btn.setToolTip("刷新图库")
        self.refresh_btn.clicked.connect(self._load_gallery)
        toolbar.addWidget(self.refresh_btn)

        self.count_label = QLabel("共 0 张")
        self.count_label.setFont(create_font())
        toolbar.addWidget(self.count_label)

        toolbar.addStretch()

        # 找图测试按钮（所有模式通用）
        test_btn = QPushButton("🧪 找图测试")
        test_btn.setFont(create_font())
        test_btn.setFixedSize(90, 28)
        test_btn.setToolTip("在当前截图上测试选中模板的匹配度")
        test_btn.clicked.connect(self._on_test_match)
        toolbar.addWidget(test_btn)

        # 添加图片
        add_btn = QPushButton("➕")
        add_btn.setFont(create_font())
        add_btn.setFixedSize(36, 28)
        add_btn.setToolTip("从文件系统添加图片")
        add_btn.clicked.connect(self._add_from_file)
        toolbar.addWidget(add_btn)

        # 删除选中
        del_btn = QPushButton("🗑")
        del_btn.setFont(create_font())
        del_btn.setFixedSize(36, 28)
        del_btn.setToolTip("删除选中的模板图片")
        del_btn.setStyleSheet(f"color: {COLOR_DANGER};")
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
            self.count_label.setText("共 0 张")
            return

        # 构建已有模板的文件名集合
        enabled_set = {t.get("template", "") for t in self._original_templates}

        exts = ('.png', '.jpg', '.jpeg', '.bmp')
        files = sorted([
            f for f in os.listdir(self.pictures_dir)
            if f.lower().endswith(exts)
        ])

        self.count_label.setText(f"共 {len(files)} 张")

        for fname in files:
            fpath = os.path.join(self.pictures_dir, fname)
            card = _ImageCard(fpath, mode=self._mode)

            if self._mode == "single":
                # 单选模式：默认选中当前模板
                if enabled_set:
                    card.set_checked(fname in enabled_set)
                # 点击时互斥选中
                card.clicked.connect(lambda c=card: self._on_single_select(c))
            else:
                # 多选模式：已有模板勾选
                if enabled_set:
                    card.set_checked(fname in enabled_set)
                else:
                    card.set_checked(True)

            self._cards.append(card)
            self._flow_layout.addWidget(card)

    def _on_single_select(self, selected_card):
        """单选模式：点击一个卡片，取消其他所有选中"""
        for card in self._cards:
            card.set_checked(card is selected_card)

    # ==================== 找图测试 ====================

    def _on_test_match(self):
        """对选中的模板在当前截图上执行找图匹配"""
        selected = self._get_selected_paths()
        if not selected:
            QMessageBox.information(self, "提示", "请先选中要测试的模板图片")
            return

        # 获取截图
        sw = self._screenshot_widget
        if sw is None or sw._source_image is None:
            QMessageBox.information(self, "提示", "请先截图或开启实时同步")
            return

        # QImage → OpenCV BGR
        q_img = sw._source_image
        q_img_rgb = q_img.convertToFormat(QImage.Format.Format_RGB888)
        w, h = q_img_rgb.width(), q_img_rgb.height()
        ptr = q_img_rgb.bits()
        ptr.setsize(h * w * 3)
        arr = np.array(ptr).reshape(h, w, 3)
        screen_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

        # 加载选中的模板（直接用 OpenCV 读取，保证零损失）
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

        sw.set_y_offset(0)
        sw.update_matches(results)

        # 输出日志
        main_win = self.window()
        log_fn = getattr(main_win, '_append_log', None)
        if log_fn:
            if results:
                log_fn(f"🧪 找图测试: 匹配到 {len(results)} 个结果")
                for name, cx, cy, score in results:
                    log_fn(f"  ▸ {name} → ({cx}, {cy}) 匹配度: {score:.3f}")
            else:
                log_fn("🧪 找图测试: 未匹配到任何结果")

    def _get_selected_paths(self):
        """获取选中卡片的文件路径列表"""
        return [c.fpath for c in self._cards if c.is_checked()]

    # ==================== 添加/删除 ====================

    def _add_from_file(self):
        """从文件系统选择图片添加"""
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择模板图片", "",
            "图片文件 (*.png *.jpg *.bmp);;所有文件 (*)"
        )
        if not files:
            return
        import shutil
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
        selected = [c for c in self._cards if c.is_checked()]
        if not selected:
            QMessageBox.information(self, "提示", "请先选中要删除的图片")
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
        """构建更新后的模板列表（仅包含选中的）"""
        orig_lookup = {t.get("template", ""): t for t in self._original_templates}
        templates = []
        for card in self._cards:
            if not card.is_checked():
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
