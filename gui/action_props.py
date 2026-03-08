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
    """找图点击 — 属性面板"""
    import template_meta
    ctx = context or {}
    pictures_dir = ctx.get("pictures_dir", "")

    # 模板路径
    _raw_tpl = node.params.get("template", "")
    edit_template = QLineEdit(_raw_tpl)
    edit_template.setPlaceholderText("模板图片文件名")

    # 偏移量控件（先创建，供模板变更回调引用）
    spin_ox = QSpinBox()
    spin_ox.setRange(-2000, 2000)
    spin_oy = QSpinBox()
    spin_oy.setRange(-2000, 2000)

    # 从 meta.json 初始化偏移值
    if _raw_tpl and pictures_dir:
        meta = template_meta.get(pictures_dir, os.path.basename(_raw_tpl))
        spin_ox.setValue(meta.get("offset_x", 0))
        spin_oy.setValue(meta.get("offset_y", 0))

    # 模板变更时自动加载 meta.json 偏移量
    def _on_template_changed(text):
        update_fn("template", text)
        tpl_name = os.path.basename(text)
        if tpl_name and pictures_dir:
            meta = template_meta.get(pictures_dir, tpl_name)
            if meta:
                spin_ox.blockSignals(True)
                spin_oy.blockSignals(True)
                spin_ox.setValue(meta.get("offset_x", 0))
                spin_oy.setValue(meta.get("offset_y", 0))
                spin_ox.blockSignals(False)
                spin_oy.blockSignals(False)

    edit_template.textChanged.connect(_on_template_changed)

    # 偏移量变更时写回 meta.json
    def _on_offset_changed():
        tpl_name = os.path.basename(node.params.get("template", ""))
        if tpl_name and pictures_dir:
            template_meta.set_meta(
                pictures_dir, tpl_name,
                offset_x=spin_ox.value(), offset_y=spin_oy.value()
            )

    spin_ox.valueChanged.connect(lambda v: _on_offset_changed())
    spin_oy.valueChanged.connect(lambda v: _on_offset_changed())

    # 浏览按钮
    browse_btn = QPushButton("📂 选择图片")
    def _browse_template():
        start_dir = pictures_dir if os.path.isdir(pictures_dir) else ""
        path, _ = QFileDialog.getOpenFileName(
            None, "选择模板图片", start_dir, "图片 (*.png *.jpg *.bmp)"
        )
        if path:
            # 自动内化到项目 Pictures/
            internalize_fn = ctx.get("internalize_fn")
            if internalize_fn:
                filename = internalize_fn(path)
            else:
                filename = os.path.basename(path)
            edit_template.setText(filename)

    browse_btn.clicked.connect(_browse_template)

    # 阈值
    spin_thresh = QDoubleSpinBox()
    spin_thresh.setRange(0.5, 1.0)
    spin_thresh.setSingleStep(0.05)
    spin_thresh.setValue(node.params.get("threshold", 0.9))
    spin_thresh.valueChanged.connect(lambda v: update_fn("threshold", v))

    # 布局
    tpl_row = QHBoxLayout()
    tpl_row.addWidget(edit_template)
    tpl_row.addWidget(browse_btn)
    layout.addRow("模板图片:", tpl_row)
    layout.addRow("匹配阈值:", spin_thresh)
    layout.addRow("偏移 X:", spin_ox)
    layout.addRow("偏移 Y:", spin_oy)

    # 模板预览
    if _raw_tpl and pictures_dir:
        tpl_path = os.path.join(pictures_dir, _raw_tpl)
        if os.path.exists(tpl_path):
            pixmap = QPixmap(tpl_path)
            if not pixmap.isNull():
                preview = QLabel()
                preview.setPixmap(pixmap.scaled(
                    120, 120,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                ))
                layout.addRow("预览:", preview)

    # 测试按钮
    _add_test_find_btn(layout, node, context)


def build_wait_image_props(layout: QFormLayout, node, update_fn, context: dict = None):
    """找图等待 — 属性面板"""
    ctx = context or {}
    pictures_dir = ctx.get("pictures_dir", "")

    edit_template = QLineEdit(node.params.get("template", ""))
    edit_template.setPlaceholderText("模板图片文件名")
    edit_template.textChanged.connect(lambda text: update_fn("template", text))

    browse_btn = QPushButton("📂 选择图片")
    def _browse():
        start_dir = pictures_dir if os.path.isdir(pictures_dir) else ""
        path, _ = QFileDialog.getOpenFileName(
            None, "选择模板图片", start_dir, "图片 (*.png *.jpg *.bmp)"
        )
        if path:
            internalize_fn = ctx.get("internalize_fn")
            if internalize_fn:
                filename = internalize_fn(path)
            else:
                filename = os.path.basename(path)
            edit_template.setText(filename)

    browse_btn.clicked.connect(_browse)

    spin_timeout = QDoubleSpinBox()
    spin_timeout.setRange(0.0, 3600.0)
    spin_timeout.setSuffix(" 秒")
    spin_timeout.setValue(node.params.get("timeout", 30.0))
    spin_timeout.valueChanged.connect(lambda v: update_fn("timeout", v))

    combo_fail = QComboBox()
    combo_fail.addItems(["abort", "continue"])
    combo_fail.setCurrentText(node.params.get("action_on_fail", "abort"))
    combo_fail.currentTextChanged.connect(lambda text: update_fn("action_on_fail", text))

    tpl_row = QHBoxLayout()
    tpl_row.addWidget(edit_template)
    tpl_row.addWidget(browse_btn)
    layout.addRow("模板图片:", tpl_row)
    layout.addRow("超时判断:", spin_timeout)
    layout.addRow("超时后:", combo_fail)


def build_multi_match_props(layout: QFormLayout, node, update_fn, context: dict = None):
    """多图点击 — 属性面板（含子动作管理）"""
    from gui.constants import COLOR_DANGER
    ctx = context or {}

    templates = node.params.get('templates', [])
    layout.addRow(QLabel(f"🎯 多图点击（{len(templates)} 个模板）"))

    # 模板管理按钮
    gallery_fn = ctx.get("on_template_gallery")
    if gallery_fn:
        manage_btn = QPushButton("📂 模板管理")
        manage_btn.setToolTip("打开图库界面管理模板")
        manage_btn.clicked.connect(lambda: gallery_fn(node))
        layout.addRow(manage_btn)

    # ---- 子动作管理 ----
    layout.addRow(QLabel(""))
    sub_label = QLabel("📋 匹配后执行的子动作:")
    sub_label.setStyleSheet("font-weight: bold;")
    layout.addRow(sub_label)

    sub_actions = node.params.setdefault("sub_actions", [])
    sub_list = QListWidget()
    sub_list.setMaximumHeight(120)
    sub_list.setAlternatingRowColors(True)
    for i, sa in enumerate(sub_actions):
        text = _format_sub_action(sa)
        sub_list.addItem(f"{i+1}. {text}")
    layout.addRow(sub_list)

    # 添加子动作按钮
    sub_btns = QHBoxLayout()
    add_fn = ctx.get("on_sub_action_add")
    del_fn = ctx.get("on_sub_action_del")

    for btn_label, action_dict in [
        ("+ 等待", {"type": "sleep", "params": {"seconds": 1.0}}),
        ("+ 点击", {"type": "tap", "params": {"x": 0, "y": 0}}),
        ("+ 找图点击", {"type": "find_and_tap", "params": {"template": "", "threshold": 0.9}}),
        ("+ 找图等待", {"type": "wait_image", "params": {"template": "", "timeout": 30.0, "action_on_fail": "abort"}}),
    ]:
        btn = QPushButton(btn_label)
        btn.setFixedHeight(26)
        if add_fn:
            btn.clicked.connect(lambda checked=False, ad=action_dict: add_fn(node, ad))
        sub_btns.addWidget(btn)

    del_btn = QPushButton("删除")
    del_btn.setFixedHeight(26)
    del_btn.setStyleSheet(f"color: {COLOR_DANGER};")
    if del_fn:
        del_btn.clicked.connect(lambda: del_fn(node, sub_list.currentRow()))
    sub_btns.addWidget(del_btn)

    layout.addRow(sub_btns)


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
        import threading
        def _do_test():
            from adb_utils import screencap_to_memory, tap as adb_tap
            import image_engine
            import template_meta

            def _safe_log(msg):
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, lambda: main_win._append_log(msg) if hasattr(main_win, '_append_log') else None)

            device_id = main_win.device_combo.currentText() if hasattr(main_win, 'device_combo') else ''
            if not device_id:
                return
            tpl = node.params.get('template', '')
            if not tpl:
                return
            tpl_path = tpl
            if not os.path.exists(tpl_path):
                tpl_path = os.path.join(pictures_dir, tpl)
            tpl_dir = os.path.dirname(tpl_path) or '.'
            loaded = image_engine.load_templates(tpl_dir)
            target_name = os.path.splitext(os.path.basename(tpl_path))[0]
            target = [t for t in loaded if t[0] == target_name]
            if not target:
                _safe_log(f"🧪 测试失败：未找到模板 [{tpl}]")
                return
            img = screencap_to_memory(device_id)
            if img is None:
                _safe_log("🧪 测试失败：截图失败")
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
                _safe_log(f"🧪 测试成功：匹配 {score:.2f}，点击 ({final_x}, {final_y})")
            else:
                _safe_log("🧪 测试失败：未匹配到图片")
        threading.Thread(target=_do_test, daemon=True).start()
    test_btn.clicked.connect(_test_find_and_tap)
    layout.addRow(test_btn)
