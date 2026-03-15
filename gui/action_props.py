"""
统一指令属性面板构建器。

提供两个核心功能：
1. ACTION_REGISTRY — 指令类型注册表（显示名、图标、分类）
2. build_props_* — 各指令类型的属性面板构建函数

两个 Tab（script_tab / loop_script_tab）共同调用，保证 UI 统一。
"""

import os
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFormLayout, QSpinBox, QDoubleSpinBox, QLineEdit, QLabel,
    QPushButton, QHBoxLayout, QFileDialog, QComboBox,
    QListWidget,
)

# =================== 指令注册表 ===================

ACTION_REGISTRY = {
    # type_key: (icon, display_name, category)
    "tap":           ("🖱", "点击坐标",   "基础动作"),
    "swipe":         ("👆", "滑动操作",   "基础动作"),
    "sleep":         ("⏱",  "延时等待",   "基础动作"),
    "find_and_tap":  ("🔍", "找图点击",   "图像识别"),
    "multi_match":   ("🎯", "多图点击",   "图像识别"),
    "wait_image":    ("⏳", "找图等待",   "图像识别"),
    "loop_start":    ("🔄", "循环开始",   "流程控制"),
    "loop_end":      ("🔚", "循环结束",   "流程控制"),
    "back":          ("◀", "返回键",     "系统按键"),
    "home":          ("⌂", "主页键",     "系统按键"),
    "app_switch":    ("⎕", "多任务键",   "系统按键"),
}


def action_display_name(action_type: str) -> str:
    """获取指令的显示名称（含图标）"""
    info = ACTION_REGISTRY.get(action_type)
    if info:
        return f"{info[0]} {info[1]}"
    return f"❓ {action_type}"


def format_action_text(node) -> str:
    """
    根据 ActionNode 生成步骤列表中的显示文本。
    两个 Tab 共用此逻辑，保证文案统一。
    """
    t = node.type
    p = node.params

    if t == "tap":
        return f"🖱 点击 ({p.get('x',0)}, {p.get('y',0)})"
    elif t == "sleep":
        return f"⏱ 等待 {p.get('seconds',0.0)}s"
    elif t == "find_and_tap":
        _raw = os.path.basename(p.get('template', ''))
        target = _raw.split('@')[0].rsplit('.', 1)[0] if _raw else '未选择'
        return f"🔍 找图点击 [{target}]"
    elif t == "wait_image":
        _raw = os.path.basename(p.get('template', ''))
        target = _raw.split('@')[0].rsplit('.', 1)[0] if _raw else '未选择'
        timeout_sec = p.get('timeout', 30)
        return f"⏳ 找图等待 [{target}] {timeout_sec}s"
    elif t == "multi_match":
        tpl_count = len(p.get('templates', []))
        return f"🎯 多图点击 ({tpl_count} 个模板)"
    elif t == "swipe":
        x1, y1 = p.get('x1', 0), p.get('y1', 0)
        x2, y2 = p.get('x2', 0), p.get('y2', 0)
        return f"👆 滑动 ({x1},{y1})→({x2},{y2})"
    elif t == "loop_start":
        return "🔄 循环开始"
    elif t == "loop_end":
        return "🔚 循环结束"
    elif t == "back":
        return "◀ 返回键"
    elif t == "home":
        return "⌂ 主页键"
    elif t == "app_switch":
        return "⎕ 多任务键"
    else:
        return f"❓ {t}"


# =================== 属性面板构建器 ===================


def build_tap_props(layout: QFormLayout, node, update_fn, context: dict = None):
    """点击坐标 — 属性面板"""
    spin_x = QSpinBox()
    spin_x.setRange(0, 4000)
    spin_x.setValue(node.params.get("x", 0))
    spin_x.valueChanged.connect(lambda v: update_fn("x", v))

    spin_y = QSpinBox()
    spin_y.setRange(0, 4000)
    spin_y.setValue(node.params.get("y", 0))
    spin_y.valueChanged.connect(lambda v: update_fn("y", v))

    layout.addRow("点击 X:", spin_x)
    layout.addRow("点击 Y:", spin_y)

    # 测试按钮
    _add_test_tap_btn(layout, node, context)


def build_sleep_props(layout: QFormLayout, node, update_fn, context: dict = None):
    """延时等待 — 属性面板"""
    spin_sec = QDoubleSpinBox()
    spin_sec.setRange(0.1, 3600.0)
    spin_sec.setSuffix(" 秒")
    spin_sec.setValue(node.params.get("seconds", 1.0))
    spin_sec.valueChanged.connect(lambda v: update_fn("seconds", v))
    layout.addRow("等待时长:", spin_sec)


def build_swipe_props(layout: QFormLayout, node, update_fn, context: dict = None):
    """滑动操作 — 属性面板"""
    for label, key, default in [
        ("起点 X:", "x1", 0), ("起点 Y:", "y1", 0),
        ("终点 X:", "x2", 0), ("终点 Y:", "y2", 0),
    ]:
        spin = QSpinBox()
        spin.setRange(0, 4000)
        spin.setValue(node.params.get(key, default))
        spin.valueChanged.connect(lambda v, k=key: update_fn(k, v))
        layout.addRow(label, spin)

    spin_dur = QSpinBox()
    spin_dur.setRange(50, 5000)
    spin_dur.setSuffix(" ms")
    spin_dur.setValue(node.params.get("duration", 300))
    spin_dur.valueChanged.connect(lambda v: update_fn("duration", v))
    layout.addRow("滑动时长:", spin_dur)

    if "path" in node.params and node.params["path"]:
        path_len = len(node.params["path"])
        from PyQt6.QtWidgets import QLabel
        path_label = QLabel(f"ℹ️ 包含 {path_len} 个高精度轨迹序列点")
        path_label.setStyleSheet("color: #a6e3a1; font-size: 11px;")
        layout.addRow(path_label)

    # 测试按钮
    _add_test_swipe_btn(layout, node, context)


def build_find_and_tap_props(layout: QFormLayout, node, update_fn, context: dict = None):
    """找图点击 — 属性面板（使用图库选择模板）"""
    import template_meta
    ctx = context or {}
    pictures_dir = ctx.get("pictures_dir", "")

    _raw_tpl = node.params.get("template", "")

    # 当前模板显示 + 缩略图预览
    tpl_display = _raw_tpl if _raw_tpl else "未选择"
    tpl_label = QLabel(f"📄 {tpl_display}")
    tpl_label.setStyleSheet("font-weight: bold;")
    tpl_label.setWordWrap(True)
    layout.addRow("模板:", tpl_label)

    if _raw_tpl and pictures_dir:
        tpl_path = os.path.join(pictures_dir, _raw_tpl)
        if os.path.exists(tpl_path):
            pixmap = QPixmap(tpl_path)
            if not pixmap.isNull():
                preview = QLabel()
                preview.setPixmap(pixmap.scaled(
                    100, 60,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                ))
                layout.addRow(preview)

    # 📂 选择模板按钮（打开单选图库）
    gallery_fn = ctx.get("on_open_gallery")
    if gallery_fn:
        select_btn = QPushButton("📂 选择模板")
        select_btn.setFixedHeight(26)
        select_btn.clicked.connect(lambda: gallery_fn(node, "single", "template"))
        layout.addRow(select_btn)

    # 阈值
    spin_thresh = QDoubleSpinBox()
    spin_thresh.setRange(0.5, 1.0)
    spin_thresh.setSingleStep(0.05)
    spin_thresh.setValue(node.params.get("threshold", 0.9))
    spin_thresh.valueChanged.connect(lambda v: update_fn("threshold", v))
    layout.addRow("匹配阈值:", spin_thresh)

    # 偏移量
    spin_ox = QSpinBox()
    spin_ox.setRange(-2000, 2000)
    spin_oy = QSpinBox()
    spin_oy.setRange(-2000, 2000)

    if _raw_tpl and pictures_dir:
        meta = template_meta.get(pictures_dir, os.path.basename(_raw_tpl))
        spin_ox.setValue(meta.get("offset_x", 0))
        spin_oy.setValue(meta.get("offset_y", 0))

    def _on_offset_changed():
        tpl_name = os.path.basename(node.params.get("template", ""))
        if tpl_name and pictures_dir:
            template_meta.set_meta(
                pictures_dir, tpl_name,
                offset_x=spin_ox.value(), offset_y=spin_oy.value()
            )

    spin_ox.valueChanged.connect(lambda v: _on_offset_changed())
    spin_oy.valueChanged.connect(lambda v: _on_offset_changed())
    layout.addRow("偏移 X:", spin_ox)
    layout.addRow("偏移 Y:", spin_oy)


def build_wait_image_props(layout: QFormLayout, node, update_fn, context: dict = None):
    """找图等待 — 属性面板（使用图库选择模板）"""
    ctx = context or {}
    pictures_dir = ctx.get("pictures_dir", "")

    _raw_tpl = node.params.get("template", "")

    # 当前模板显示 + 缩略图预览
    tpl_display = _raw_tpl if _raw_tpl else "未选择"
    tpl_label = QLabel(f"📄 {tpl_display}")
    tpl_label.setStyleSheet("font-weight: bold;")
    tpl_label.setWordWrap(True)
    layout.addRow("模板:", tpl_label)

    if _raw_tpl and pictures_dir:
        tpl_path = os.path.join(pictures_dir, _raw_tpl)
        if os.path.exists(tpl_path):
            pixmap = QPixmap(tpl_path)
            if not pixmap.isNull():
                preview = QLabel()
                preview.setPixmap(pixmap.scaled(
                    100, 60,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                ))
                layout.addRow(preview)

    # 📂 选择模板按钮（打开单选图库）
    gallery_fn = ctx.get("on_open_gallery")
    if gallery_fn:
        select_btn = QPushButton("📂 选择模板")
        select_btn.setFixedHeight(26)
        select_btn.clicked.connect(lambda: gallery_fn(node, "single", "template"))
        layout.addRow(select_btn)

    # 超时
    spin_timeout = QDoubleSpinBox()
    spin_timeout.setRange(0.0, 3600.0)
    spin_timeout.setSuffix(" 秒")
    spin_timeout.setValue(node.params.get("timeout", 30.0))
    spin_timeout.valueChanged.connect(lambda v: update_fn("timeout", v))
    layout.addRow("超时判断:", spin_timeout)

    # 超时后行为
    combo_fail = QComboBox()
    combo_fail.addItems(["abort", "continue"])
    combo_fail.setCurrentText(node.params.get("action_on_fail", "abort"))
    combo_fail.currentTextChanged.connect(lambda text: update_fn("action_on_fail", text))
    layout.addRow("超时后:", combo_fail)


def build_multi_match_props(layout: QFormLayout, node, update_fn, context: dict = None):
    """多图点击 — 属性面板（含子动作管理与内联编辑）"""
    from PyQt6.QtWidgets import QGridLayout, QWidget, QVBoxLayout, QFrame
    from gui.constants import COLOR_DANGER
    ctx = context or {}

    templates = node.params.get('templates', [])
    layout.addRow(QLabel(f"🎯 多图点击（{len(templates)} 个模板）"))

    # 模板管理按钮（独占一行）
    gallery_fn = ctx.get("on_open_gallery")
    if gallery_fn:
        manage_btn = QPushButton("📂 管理模板")
        manage_btn.setFixedHeight(26)
        manage_btn.setToolTip("打开图库界面管理模板")
        manage_btn.clicked.connect(lambda: gallery_fn(node, "multi", "templates"))
        layout.addRow(manage_btn)

    # ---- 子动作管理 ----
    sub_label = QLabel("📋 匹配后的子动作:")
    sub_label.setStyleSheet("font-weight: bold; margin-top: 4px;")
    layout.addRow(sub_label)

    sub_actions = node.params.setdefault("sub_actions", [])
    sub_list = QListWidget()
    # 根据条目数动态设置高度，最少 2 行，最多 5 行
    row_h = 22
    visible_rows = max(2, min(len(sub_actions) + 1, 5))
    sub_list.setFixedHeight(visible_rows * row_h + 4)
    sub_list.setAlternatingRowColors(True)
    for i, sa in enumerate(sub_actions):
        text = _format_sub_action(sa)
        sub_list.addItem(f"{i+1}. {text}")
    layout.addRow(sub_list)

    # ---- 子动作内联编辑区 ----
    editor_frame = QFrame()
    editor_frame.setStyleSheet(
        "QFrame { border: 1px solid #555; border-radius: 4px; padding: 4px; }"
    )
    editor_outer = QVBoxLayout(editor_frame)
    editor_outer.setContentsMargins(4, 4, 4, 4)
    editor_outer.setSpacing(2)

    # 编辑区提示占位
    editor_hint = QLabel("← 选中子动作以编辑参数")
    editor_hint.setStyleSheet("color: #888; border: none;")
    editor_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
    editor_outer.addWidget(editor_hint)

    layout.addRow(editor_frame)

    def _on_sub_selected(row):
        """选中子动作时动态构建编辑面板"""
        # 清空编辑区
        while editor_outer.count():
            child = editor_outer.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

        if row < 0 or row >= len(sub_actions):
            hint = QLabel("← 选中子动作以编辑参数")
            hint.setStyleSheet("color: #888; border: none;")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            editor_outer.addWidget(hint)
            return

        sa = sub_actions[row]
        sa_type = sa.get("type", "")
        sa_params = sa.setdefault("params", {})

        # 标题
        title = QLabel(f"✏️ 编辑 #{row + 1}: {_format_sub_action(sa)}")
        title.setStyleSheet("font-weight: bold; color: #4fc3f7; border: none;")
        editor_outer.addWidget(title)

        # 使用 _SubActionProxy 适配字典为 builder 可接受的对象
        proxy = _SubActionProxy(sa_type, sa_params)

        form_widget = QWidget()
        form_widget.setStyleSheet("border: none;")  # 继承的边框去掉
        form_layout = QFormLayout(form_widget)
        form_layout.setContentsMargins(0, 0, 0, 0)

        def _update_sub_param(key, value):
            """修改子动作参数并刷新列表文本"""
            sa_params[key] = value
            # 刷新列表中的显示文本
            item = sub_list.item(row)
            if item:
                item.setText(f"{row + 1}. {_format_sub_action(sa)}")

        # 根据类型复用对应的 builder（不含测试按钮）
        builder = _SUB_BUILDERS.get(sa_type)
        if builder:
            builder(form_layout, proxy, _update_sub_param, ctx)
        else:
            form_layout.addRow(QLabel("此类型暂无可编辑参数"))

        editor_outer.addWidget(form_widget)

    sub_list.currentRowChanged.connect(_on_sub_selected)

    # ---- 添加子动作按钮 — 2×2 网格 + 独立删除按钮 ----
    add_fn = ctx.get("on_sub_action_add")
    del_fn = ctx.get("on_sub_action_del")

    btn_container = QWidget()
    grid = QGridLayout(btn_container)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(3)

    btn_defs = [
        ("+ 等待",     {"type": "sleep", "params": {"seconds": 1.0}}),
        ("+ 点击",     {"type": "tap", "params": {"x": 0, "y": 0}}),
        ("+ 找图点击",  {"type": "find_and_tap", "params": {"template": "", "threshold": 0.9}}),
        ("+ 找图等待",  {"type": "wait_image", "params": {"template": "", "timeout": 30.0, "action_on_fail": "abort"}}),
    ]
    # 2×2 网格
    for idx, (label, ad) in enumerate(btn_defs):
        btn = QPushButton(label)
        btn.setFixedHeight(24)
        if add_fn:
            btn.clicked.connect(lambda checked=False, a=ad: add_fn(node, a))
        grid.addWidget(btn, idx // 2, idx % 2)

    # 删除按钮独占一行
    del_btn = QPushButton("🗑 删除选中子动作")
    del_btn.setFixedHeight(24)
    del_btn.setStyleSheet(f"color: {COLOR_DANGER};")
    if del_fn:
        del_btn.clicked.connect(lambda: del_fn(node, sub_list.currentRow()))
    grid.addWidget(del_btn, 2, 0, 1, 2)  # 跨两列

    layout.addRow(btn_container)


def append_comment_row(layout: QFormLayout, node):
    """添加通用的备注输入行"""
    comment_edit = QLineEdit(node.comment if hasattr(node, 'comment') else "")
    comment_edit.setPlaceholderText("可选备注")
    comment_edit.textChanged.connect(lambda v: setattr(node, 'comment', v))
    layout.addRow("备注:", comment_edit)


def build_system_key_props(layout: QFormLayout, node, update_fn, context: dict = None):
    """系统按键 — 属性面板（无特定参数）"""
    layout.addRow(QLabel("此操作没有可配置的参数。"))


# =================== 统一分派 ===================

# 各指令类型对应的构建函数
_BUILDERS = {
    "tap": build_tap_props,
    "sleep": build_sleep_props,
    "swipe": build_swipe_props,
    "find_and_tap": build_find_and_tap_props,
    "wait_image": build_wait_image_props,
    "multi_match": build_multi_match_props,
    "back": build_system_key_props,
    "home": build_system_key_props,
    "app_switch": build_system_key_props,
}


def build_action_props(layout: QFormLayout, node, update_fn, context: dict = None):
    """
    统一入口：根据 node.type 分派到对应的构建函数。
    返回 True 表示成功构建，False 表示未知类型。
    """
    builder = _BUILDERS.get(node.type)
    if builder:
        builder(layout, node, update_fn, context)
        return True
    return False


# =================== 子动作编辑辅助 ===================


class _SubActionProxy:
    """将子动作字典适配为 builder 函数可接受的节点对象。"""
    def __init__(self, sa_type: str, sa_params: dict):
        self.type = sa_type
        self.params = sa_params


def _build_sub_tap(layout, proxy, update_fn, ctx=None):
    """子动作：点击坐标编辑（精简版，无测试按钮）"""
    spin_x = QSpinBox()
    spin_x.setRange(0, 4000)
    spin_x.setValue(proxy.params.get("x", 0))
    spin_x.valueChanged.connect(lambda v: update_fn("x", v))
    layout.addRow("X:", spin_x)

    spin_y = QSpinBox()
    spin_y.setRange(0, 4000)
    spin_y.setValue(proxy.params.get("y", 0))
    spin_y.valueChanged.connect(lambda v: update_fn("y", v))
    layout.addRow("Y:", spin_y)


def _build_sub_sleep(layout, proxy, update_fn, ctx=None):
    """子动作：等待时间编辑"""
    spin_sec = QDoubleSpinBox()
    spin_sec.setRange(0.1, 3600.0)
    spin_sec.setSuffix(" 秒")
    spin_sec.setValue(proxy.params.get("seconds", 1.0))
    spin_sec.valueChanged.connect(lambda v: update_fn("seconds", v))
    layout.addRow("等待:", spin_sec)


def _build_sub_find_and_tap(layout, proxy, update_fn, ctx=None):
    """子动作：找图点击编辑（精简版）"""
    ctx = ctx or {}
    pictures_dir = ctx.get("pictures_dir", "")

    edit_tpl = QLineEdit(proxy.params.get("template", ""))
    edit_tpl.setPlaceholderText("模板图片文件名")
    edit_tpl.textChanged.connect(lambda t: update_fn("template", t))

    browse_btn = QPushButton("📂")
    browse_btn.setFixedWidth(30)
    def _browse():
        start = pictures_dir if os.path.isdir(pictures_dir) else ""
        path, _ = QFileDialog.getOpenFileName(None, "选择模板", start, "图片 (*.png *.jpg *.bmp)")
        if path:
            internalize_fn = ctx.get("internalize_fn")
            if internalize_fn:
                filename = internalize_fn(path)
            else:
                filename = os.path.basename(path)
            edit_tpl.setText(filename)
    browse_btn.clicked.connect(_browse)

    tpl_row = QHBoxLayout()
    tpl_row.addWidget(edit_tpl)
    tpl_row.addWidget(browse_btn)
    layout.addRow("模板:", tpl_row)

    spin_th = QDoubleSpinBox()
    spin_th.setRange(0.5, 1.0)
    spin_th.setSingleStep(0.05)
    spin_th.setValue(proxy.params.get("threshold", 0.9))
    spin_th.valueChanged.connect(lambda v: update_fn("threshold", v))
    layout.addRow("阈值:", spin_th)


def _build_sub_wait_image(layout, proxy, update_fn, ctx=None):
    """子动作：找图等待编辑（精简版）"""
    ctx = ctx or {}
    pictures_dir = ctx.get("pictures_dir", "")

    edit_tpl = QLineEdit(proxy.params.get("template", ""))
    edit_tpl.setPlaceholderText("模板图片文件名")
    edit_tpl.textChanged.connect(lambda t: update_fn("template", t))

    browse_btn = QPushButton("📂")
    browse_btn.setFixedWidth(30)
    def _browse():
        start = pictures_dir if os.path.isdir(pictures_dir) else ""
        path, _ = QFileDialog.getOpenFileName(None, "选择模板", start, "图片 (*.png *.jpg *.bmp)")
        if path:
            internalize_fn = ctx.get("internalize_fn")
            if internalize_fn:
                filename = internalize_fn(path)
            else:
                filename = os.path.basename(path)
            edit_tpl.setText(filename)
    browse_btn.clicked.connect(_browse)

    tpl_row = QHBoxLayout()
    tpl_row.addWidget(edit_tpl)
    tpl_row.addWidget(browse_btn)
    layout.addRow("模板:", tpl_row)

    spin_timeout = QDoubleSpinBox()
    spin_timeout.setRange(0.0, 3600.0)
    spin_timeout.setSuffix(" 秒")
    spin_timeout.setValue(proxy.params.get("timeout", 30.0))
    spin_timeout.valueChanged.connect(lambda v: update_fn("timeout", v))
    layout.addRow("超时:", spin_timeout)

    combo_fail = QComboBox()
    combo_fail.addItems(["abort", "continue"])
    combo_fail.setCurrentText(proxy.params.get("action_on_fail", "abort"))
    combo_fail.currentTextChanged.connect(lambda t: update_fn("action_on_fail", t))
    layout.addRow("超时后:", combo_fail)


# 子动作类型 → 精简 builder 映射（不含测试按钮）
_SUB_BUILDERS = {
    "tap": _build_sub_tap,
    "sleep": _build_sub_sleep,
    "find_and_tap": _build_sub_find_and_tap,
    "wait_image": _build_sub_wait_image,
}


# =================== 辅助函数 ===================

def _format_sub_action(sa: dict) -> str:
    """格式化子动作的显示文本"""
    sa_type = sa.get("type", "")
    sa_params = sa.get("params", {})
    if sa_type == "sleep":
        return f"⏱ 等待 {sa_params.get('seconds', 1.0)}s"
    elif sa_type == "tap":
        return f"🖱 点击 ({sa_params.get('x', 0)}, {sa_params.get('y', 0)})"
    elif sa_type == "swipe":
        return f"👆 滑动 ({sa_params.get('x1',0)},{sa_params.get('y1',0)})→({sa_params.get('x2',0)},{sa_params.get('y2',0)})"
    elif sa_type == "find_and_tap":
        _raw = os.path.basename(sa_params.get('template', ''))
        target = _raw.split('@')[0].rsplit('.', 1)[0] if _raw else '未设置'
        return f"🔍 找图点击 [{target}]"
    elif sa_type == "wait_image":
        _raw = os.path.basename(sa_params.get('template', ''))
        target = _raw.split('@')[0].rsplit('.', 1)[0] if _raw else '未设置'
        return f"⏳ 找图等待 [{target}]"
    return f"❓ {sa_type}"


def _add_test_tap_btn(layout, node, context):
    """添加「测试点击」按钮"""
    ctx = context or {}
    main_win = ctx.get("main_win")
    if not main_win:
        return

    test_btn = QPushButton("🧪 测试点击")
    test_btn.setToolTip("在当前设备上执行一次点击")
    def _test_tap():
        import threading
        from adb_utils import tap as adb_tap
        device_id = main_win.device_combo.currentText() if hasattr(main_win, 'device_combo') else ''
        if device_id:
            x, y = node.params.get('x', 0), node.params.get('y', 0)
            threading.Thread(target=adb_tap, args=(device_id, x, y), daemon=True).start()
            if hasattr(main_win, '_append_log'):
                main_win._append_log(f"🧪 测试点击 ({x}, {y})")
    test_btn.clicked.connect(_test_tap)
    layout.addRow(test_btn)


def _add_test_swipe_btn(layout, node, context):
    """添加「测试滑动」按钮"""
    ctx = context or {}
    main_win = ctx.get("main_win")
    if not main_win:
        return

    test_btn = QPushButton("🧪 测试滑动")
    test_btn.setToolTip("在当前设备上执行一次滑动")
    def _test_swipe():
        import threading
        device_id = main_win.device_combo.currentText() if hasattr(main_win, 'device_combo') else ''
        if not device_id:
            return

        path = node.params.get('path')
        if path:
            adapter = main_win._get_active_adapter()
            if adapter and getattr(adapter, 'supports_touch', False):
                threading.Thread(target=adapter.swipe_path, args=(path,), daemon=True).start()
                if hasattr(main_win, '_append_log'):
                    main_win._append_log(f"🧪 测试高级轨迹滑动 (共 {len(path)} 个控制点)")
                return

        from adb_utils import swipe as adb_swipe
        x1, y1 = node.params.get('x1', 0), node.params.get('y1', 0)
        x2, y2 = node.params.get('x2', 0), node.params.get('y2', 0)
        dur = node.params.get('duration', 300)
        threading.Thread(target=adb_swipe, args=(device_id, x1, y1, x2, y2, dur), daemon=True).start()
        if hasattr(main_win, '_append_log'):
            main_win._append_log(f"🧪 测试直线滑动 ({x1}, {y1}) → ({x2}, {y2}) {dur}ms")
    test_btn.clicked.connect(_test_swipe)
    layout.addRow(test_btn)


def _add_test_find_btn(layout, node, context):
    """添加「测试找图点击」按钮"""
    ctx = context or {}
    main_win = ctx.get("main_win")
    pictures_dir = ctx.get("pictures_dir", "")
    if not main_win:
        return

    test_btn = QPushButton("🧪 测试找图点击")
    test_btn.setToolTip("截图一次并尝试匹配点击")
    def _test_find_and_tap():
        # ------- 主线程：参数校验 -------
        def _log(msg):
            if hasattr(main_win, '_append_log'):
                main_win._append_log(msg)

        device_id = main_win.device_combo.currentText() if hasattr(main_win, 'device_combo') else ''
        if not device_id:
            _log("🧪 测试失败：请先选择设备")
            return
        tpl = node.params.get('template', '')
        if not tpl:
            _log("🧪 测试失败：请先设置模板图片")
            return
        tpl_path = tpl
        if not os.path.exists(tpl_path):
            tpl_path = os.path.join(pictures_dir, tpl)
        if not os.path.exists(tpl_path):
            _log(f"🧪 测试失败：模板文件不存在 [{tpl_path}]")
            return

        _log(f"🧪 正在截图并匹配 [{os.path.basename(tpl_path)}]...")

        # ------- 后台线程：阻塞 ADB 截图 + 匹配 -------
        import threading
        def _do_test():
            try:
                from adb_utils import screencap_to_memory, tap as adb_tap
                import image_engine
                import template_meta

                tpl_dir = os.path.dirname(tpl_path) or '.'
                # 测试时强制清除缓存，确保新增模板能被加载
                image_engine.clear_cache(tpl_dir)
                loaded = image_engine.load_templates(tpl_dir)
                target_name = os.path.splitext(os.path.basename(tpl_path))[0]
                target = [t for t in loaded if t[0] == target_name]
                if not target:
                    print(f"[测试找图] 模板加载失败: {tpl}")
                    return

                img = screencap_to_memory(device_id)
                if img is None:
                    print("[测试找图] ADB 截图返回 None")
                    return

                th = node.params.get('threshold', 0.9)
                matches = image_engine.match_all(img, target, th)
                if matches:
                    name, cx, cy, score = matches[0]
                    meta = template_meta.get(pictures_dir, os.path.basename(tpl))
                    ox = meta.get('offset_x', 0)
                    oy = meta.get('offset_y', 0)
                    final_x, final_y = cx + ox, cy + oy
                    adb_tap(device_id, final_x, final_y)
                    print(f"[测试找图] 匹配成功 {score:.2f}，已点击 ({final_x}, {final_y})")
                else:
                    print("[测试找图] 未匹配到图片")
            except Exception as e:
                import traceback
                traceback.print_exc()
        threading.Thread(target=_do_test, daemon=True).start()
    test_btn.clicked.connect(_test_find_and_tap)
    layout.addRow(test_btn)
