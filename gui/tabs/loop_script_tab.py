"""
循环脚本 Tab：三栏式布局，与脚本 Tab 结构一致。
支持两种循环类型：普通循环（顺序脚本+循环次数）、多模板匹配循环。

布局：
  ┌─ 顶部工具栏 ──────────────────────────────────────────────┐
  │ [导入▼] [外部导入] [🔄] │ 类型:[▼] 循环次数/间隔/默认坐标 │
  ├─ 左侧 ────────┬─ 中间 ──────────────┬─ 右侧 ─────────────┤
  │ 指令工具箱     │ 步骤列表            │ 参数属性面板        │
  │ (双击添加)     │ (拖拽排序/勾选)     │ (模板/坐标/阈值)   │
  └────────────────┴─────────────────────┴─────────────────────┘
"""

import os
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QListWidget, QListWidgetItem, QPushButton, QComboBox,
    QSpinBox, QDoubleSpinBox, QLabel, QGroupBox,
    QSplitter, QCheckBox, QMessageBox, QFileDialog, QDialog,
    QTreeWidget, QTreeWidgetItem, QStackedWidget, QLineEdit,
    QScrollArea,
)

from script_model import ScriptModel, ActionNode
from gui.constants import create_font, COLOR_DANGER


class LoopScriptTab(QWidget):
    """循环脚本管理 Tab — 三栏式布局"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_model = None       # 当前加载的 ScriptModel
        self._enabled_templates = set() # 启用的模板文件名集合
        self._init_ui()
    
    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        
        # 顶层页面栈：page0=编辑器, page1=图库（全覆盖）
        self._page_stack = QStackedWidget()
        outer.addWidget(self._page_stack)
        
        # ===== Page 0: 编辑器主体 =====
        editor_page = QWidget()
        root = QVBoxLayout(editor_page)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)
        
        # =================== 顶部工具栏 ===================
        toolbar = QHBoxLayout()
        
        # 项目选择（选中后自动加载）
        toolbar.addWidget(QLabel("📂 脚本:"))
        self.project_combo = QComboBox()
        self.project_combo.setMinimumWidth(150)
        self.project_combo.currentTextChanged.connect(self._on_project_changed)
        toolbar.addWidget(self.project_combo)
        
        import_ext_btn = QPushButton("📁 外部导入")
        import_ext_btn.setToolTip("从外部文件夹导入脚本项目（自动复制并内化图片）")
        import_ext_btn.clicked.connect(self._on_import_external)
        toolbar.addWidget(import_ext_btn)
        
        refresh_btn = QPushButton("🔄")
        refresh_btn.setToolTip("刷新项目列表")
        refresh_btn.setFixedWidth(30)
        refresh_btn.clicked.connect(self._refresh_projects)
        toolbar.addWidget(refresh_btn)
        
        convert_btn = QPushButton("✨ 转换")
        convert_btn.setToolTip("将当前流水线脚本转换为多模板匹配循环")
        convert_btn.setObjectName("warningBtn")
        convert_btn.clicked.connect(self._on_convert)
        toolbar.addWidget(convert_btn)
        
        toolbar.addStretch()
        
        # 当前脚本名称标签
        self.model_label = QLabel("未加载脚本")
        self.model_label.setStyleSheet("color: #888; font-style: italic;")
        toolbar.addWidget(self.model_label)
        
        root.addLayout(toolbar)
        
        # =================== 主区域：三栏式编辑器 ===================
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # ================= 左侧：指令工具箱 =================
        left_widget = QGroupBox("指令工具箱")
        left_layout = QVBoxLayout(left_widget)
        self.toolbox_tree = QTreeWidget()
        self.toolbox_tree.setHeaderHidden(True)
        # 减少缩进量，避免文字被截断
        self.toolbox_tree.setIndentation(12)
        self._populate_toolbox()
        left_layout.addWidget(self.toolbox_tree)
        
        # ================= 中间：步骤列表 =================
        center_widget = QGroupBox("步骤列表")
        center_layout = QVBoxLayout(center_widget)
        
        self.action_list = QListWidget()
        self.action_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.action_list.setAlternatingRowColors(True)
        self.action_list.setStyleSheet("""
            QListWidget::item:selected {
                background-color: #e3f2fd;
                color: #1a1a2e;
            }
            QListWidget::item:hover {
                background-color: #f0f4f8;
            }
        """)
        center_layout.addWidget(self.action_list)
        
        # 步骤操作按钮
        step_btns = QHBoxLayout()
        self.delete_btn = QPushButton("🗑 删除")
        self.delete_btn.clicked.connect(self._on_delete_action)
        step_btns.addWidget(self.delete_btn)
        
        self.save_btn = QPushButton("💾 保存")
        self.save_btn.clicked.connect(self.save_config)
        step_btns.addWidget(self.save_btn)
        step_btns.addStretch()
        center_layout.addLayout(step_btns)
        
        right_widget = QGroupBox("参数属性")
        right_widget.setMinimumWidth(220)
        right_layout = QVBoxLayout(right_widget)
        
        # 用 QScrollArea 包裹属性面板，防止内容溢出撑大整个 Tab
        props_scroll = QScrollArea()
        props_scroll.setWidgetResizable(True)
        props_scroll.setStyleSheet("QScrollArea { border: none; }")
        
        self.props_stack = QStackedWidget()
        
        # 默认无选中时的提示
        empty_prop = QLabel("选中步骤以编辑参数\n或点击左侧工具箱添加新步骤")
        empty_prop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_prop.setStyleSheet("color: #888;")
        self.props_stack.addWidget(empty_prop)
        
        props_scroll.setWidget(self.props_stack)
        right_layout.addWidget(props_scroll)
        
        # 加入分割器并设置比例 1 : 2 : 1.5
        splitter.addWidget(left_widget)
        splitter.addWidget(center_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([190, 340, 250])
        
        root.addWidget(splitter, stretch=1)
        
        self._page_stack.addWidget(editor_page)  # page 0 = 编辑器
        
        # ================= 信号连接 =================
        self.toolbox_tree.itemDoubleClicked.connect(self._on_toolbox_double_clicked)
        self.action_list.currentRowChanged.connect(self._on_action_selected)
        self.action_list.model().rowsMoved.connect(self._on_actions_reordered)
        
        # 初始化项目列表
        self._refresh_projects()
    
    # =================== 左侧工具箱 ===================
    
    def _populate_toolbox(self):
        """填充左侧指令工具箱"""
        from gui.action_props import ACTION_REGISTRY
        categories = {}
        for type_key, (icon, display_name, category) in ACTION_REGISTRY.items():
            if category == "流程控制":
                continue
            if category not in categories:
                categories[category] = []
            categories[category].append((type_key, icon, display_name))
        for cat_name, items in categories.items():
            cat = QTreeWidgetItem(self.toolbox_tree, [cat_name])
            for type_key, icon, display_name in items:
                QTreeWidgetItem(cat, [f"{icon} {display_name}"]).setData(
                    0, Qt.ItemDataRole.UserRole, type_key)
        self.toolbox_tree.expandAll()
    
    def _on_toolbox_double_clicked(self, item: QTreeWidgetItem, column: int):
        """双击工具箱项，添加新步骤到中间列表"""
        action_type = item.data(0, Qt.ItemDataRole.UserRole)
        if not action_type or not self.current_model:
            return
        
        # 默认参数模板
        default_params = {
            "tap": {"x": 0, "y": 0},
            "sleep": {"seconds": 1.0},
            "swipe": {"x1": 0, "y1": 0, "x2": 0, "y2": 0, "duration": 300},
            "find_and_tap": {"template": "", "threshold": 0.9, "timeout": 3.0},
            "multi_match": {"templates": [], "sub_actions": []},
            "wait_image": {"template": "", "timeout": 30.0, "action_on_fail": "abort"},
        }.get(action_type, {})
        
        node = ActionNode(action_type=action_type, params=default_params)
        self.current_model.add_action(node)
        self._add_node_to_ui_list(node)
    
    def _add_node_to_ui_list(self, node):
        """将节点添加到中间步骤列表 UI"""
        list_item = QListWidgetItem()
        list_item.setData(Qt.ItemDataRole.UserRole, node.id)
        
        # find_and_tap 类型支持勾选（启用/禁用）
        if node.type == "find_and_tap":
            list_item.setFlags(list_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            list_item.setCheckState(Qt.CheckState.Checked)
            tpl = node.params.get("template", "")
            if tpl:
                self._enabled_templates.add(os.path.basename(tpl))
        
        self.action_list.addItem(list_item)
        self._refresh_action_list_text()
    
    # =================== 项目管理 ===================
    
    def _refresh_projects(self):
        """刷新可导入的脚本项目列表"""
        self.project_combo.blockSignals(True)
        current = self.project_combo.currentText()
        self.project_combo.clear()
        projects = ScriptModel.list_projects()
        self.project_combo.addItems(projects)
        idx = self.project_combo.findText(current)
        if idx >= 0:
            self.project_combo.setCurrentIndex(idx)
        self.project_combo.blockSignals(False)
    
    def _on_project_changed(self, project_name: str):
        """下拉框选中脚本后自动加载"""
        if not project_name:
            return
        project_dir = os.path.join(ScriptModel.SCRIPTS_ROOT, project_name)
        if os.path.isdir(project_dir):
            model = ScriptModel.load_from_project(project_dir)
            self._load_model(model)
    
    def _on_import_external(self):
        """从外部文件夹导入脚本项目（copytree + 图片内化）"""
        folder = QFileDialog.getExistingDirectory(
            self, "选择脚本项目文件夹", "",
            QFileDialog.Option.ShowDirsOnly
        )
        if not folder:
            return
        
        script_file = os.path.join(folder, ScriptModel.SCRIPT_FILENAME)
        if not os.path.exists(script_file):
            QMessageBox.warning(
                self, "无效项目",
                f"选中的文件夹不包含 {ScriptModel.SCRIPT_FILENAME}，\n"
                "请选择一个有效的脚本项目文件夹。"
            )
            return
        
        try:
            model = ScriptModel.import_project(folder)
            self._refresh_projects()
            idx = self.project_combo.findText(os.path.basename(model.project_dir))
            if idx >= 0:
                self.project_combo.blockSignals(True)
                self.project_combo.setCurrentIndex(idx)
                self.project_combo.blockSignals(False)
            self._load_model(model)
            
            QMessageBox.information(
                self, "导入成功",
                f"项目 \"{model.name}\" 已成功导入。\n"
                f"所有外部图片引用已自动内化到项目 Pictures/ 目录。"
            )
        except Exception as e:
            QMessageBox.critical(
                self, "导入失败",
                f"导入项目时发生错误：\n{str(e)}"
            )
    
    def _load_model(self, model: ScriptModel):
        """加载模型到 UI（公共逻辑）"""
        self.current_model = model
        
        # 更新顶部标签
        self.model_label.setText(f"🔄 {model.name}")
        self.model_label.setStyleSheet("color: #4fc3f7; font-weight: bold;")
        
        # 重建步骤列表（会自动显示配置面板）
        self._reload_action_list_ui()
    
    # =================== 中间步骤列表 ===================
    
    def _reload_action_list_ui(self):
        """根据 current_model 重建中间步骤列表"""
        self.action_list.clear()
        self._enabled_templates.clear()
        
        if not self.current_model:
            return
        
        # 阻塞 itemChanged 信号，避免加载时反复触发
        self.action_list.blockSignals(True)
        
        for node in self.current_model.actions:
            list_item = QListWidgetItem()
            list_item.setData(Qt.ItemDataRole.UserRole, node.id)
            
            # find_and_tap 支持勾选启用/禁用
            if node.type == "find_and_tap":
                list_item.setFlags(list_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                list_item.setCheckState(Qt.CheckState.Checked)
                tpl = node.params.get("template", "")
                if tpl:
                    self._enabled_templates.add(os.path.basename(tpl))
            
            self.action_list.addItem(list_item)
        
        self.action_list.blockSignals(False)
        
        # 连接勾选信号
        self.action_list.itemChanged.connect(self._on_item_check_changed)
        
        self._refresh_action_list_text()
        
        # 默认显示循环配置
        self._show_loop_config()
    
    def _refresh_action_list_text(self):
        """刷新步骤列表的显示文本"""
        from gui.action_props import format_action_text
        if not self.current_model:
            return
        for i in range(self.action_list.count()):
            item = self.action_list.item(i)
            node_id = item.data(Qt.ItemDataRole.UserRole)
            node = next((n for n in self.current_model.actions if n.id == node_id), None)
            if not node:
                continue
            item.setText(f"{i+1}. {format_action_text(node)}")
    
    def _on_item_check_changed(self, item):
        """模板勾选状态改变时更新启用集合"""
        node_id = item.data(Qt.ItemDataRole.UserRole)
        if not self.current_model:
            return
        node = next((n for n in self.current_model.actions if n.id == node_id), None)
        if not node or node.type != "find_and_tap":
            return
        
        tpl = os.path.basename(node.params.get("template", ""))
        if not tpl:
            return
        
        if item.checkState() == Qt.CheckState.Checked:
            self._enabled_templates.add(tpl)
        else:
            self._enabled_templates.discard(tpl)
    
    def _on_actions_reordered(self):
        """拖拽排序后同步 model.actions 顺序"""
        if not self.current_model:
            return
        id_order = []
        for i in range(self.action_list.count()):
            item = self.action_list.item(i)
            id_order.append(item.data(Qt.ItemDataRole.UserRole))
        
        id_to_node = {n.id: n for n in self.current_model.actions}
        self.current_model.actions = [id_to_node[nid] for nid in id_order if nid in id_to_node]
        self._refresh_action_list_text()
    
    def _on_delete_action(self):
        """删除当前选中的步骤"""
        row = self.action_list.currentRow()
        if row < 0 or not self.current_model:
            return
        
        item = self.action_list.item(row)
        node_id = item.data(Qt.ItemDataRole.UserRole)
        self.current_model.remove_action(node_id)
        self.action_list.takeItem(row)
        self._refresh_action_list_text()
    
    # =================== 右侧属性面板 ===================
    
    def _on_action_selected(self, row: int):
        """选中步骤时切换右侧属性面板"""
        if row < 0:
            self._show_loop_config()
            return
        
        item = self.action_list.item(row)
        node_id = item.data(Qt.ItemDataRole.UserRole)
        if not self.current_model:
            return
        node = next((n for n in self.current_model.actions if n.id == node_id), None)
        if not node:
            return
        
        props_widget = self._create_props_widget(node)
        self._set_props_widget(props_widget)
    
    def _set_props_widget(self, widget):
        """替换右侧属性面板内容"""
        while self.props_stack.count() > 1:
            w = self.props_stack.widget(1)
            self.props_stack.removeWidget(w)
            w.deleteLater()
        self.props_stack.addWidget(widget)
        self.props_stack.setCurrentIndex(1)
    
    def _show_loop_config(self):
        """在右侧属性面板显示可编辑的循环配置"""
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.addRow(QLabel("📋 脚本配置"))
        
        if not self.current_model:
            layout.addRow(QLabel("请先在上方选择脚本项目"))
            self._set_props_widget(widget)
            return
        
        cfg = self.current_model.config
        
        # 脚本信息（只读）
        layout.addRow("脚本名称:", QLabel(self.current_model.name))
        layout.addRow("适配分辨率:", QLabel(cfg.resolution or "未设置"))
        
        # --- 可编辑参数 ---
        layout.addRow(QLabel(""))  # 分隔
        layout.addRow(QLabel("⚙️ 循环参数"))
        

        
        # 循环次数
        spin_max_loops = QSpinBox()
        spin_max_loops.setRange(0, 99999)
        spin_max_loops.setSpecialValueText("无限")
        spin_max_loops.setToolTip("0 = 无限循环")
        spin_max_loops.setValue(cfg.max_loops)
        spin_max_loops.valueChanged.connect(
            lambda v: setattr(cfg, 'max_loops', v)
        )
        layout.addRow("循环次数:", spin_max_loops)
        
        # 扫描间隔
        spin_interval = QDoubleSpinBox()
        spin_interval.setRange(0.1, 60.0)
        spin_interval.setSuffix(" 秒")
        spin_interval.setValue(cfg.scan_interval)
        spin_interval.valueChanged.connect(
            lambda v: setattr(cfg, 'scan_interval', v)
        )
        layout.addRow("扫描间隔:", spin_interval)
        

        
        # --- 统计信息 ---
        layout.addRow(QLabel(""))  # 分隔
        layout.addRow(QLabel("📊 统计"))
        n_watch = sum(1 for a in self.current_model.actions if a.type == "find_and_tap")
        n_tap = sum(1 for a in self.current_model.actions if a.type == "tap")
        n_total = len(self.current_model.actions)
        layout.addRow("监视规则:", QLabel(f"{n_watch} 条"))
        layout.addRow("点击动作:", QLabel(f"{n_tap} 个"))
        layout.addRow("总步骤数:", QLabel(f"{n_total}"))
        layout.addRow("启用模板:", QLabel(f"{len(self._enabled_templates)} 个"))
        
        self._set_props_widget(widget)
    
    def _create_props_widget(self, node) -> QWidget:
        """根据 ActionNode 类型动态生成参数面板（统一调用 action_props）"""
        from gui.action_props import build_action_props, append_comment_row
        from PyQt6.QtWidgets import QFormLayout
        
        wrapper = QWidget()
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        
        form_widget = QWidget()
        layout = QFormLayout(form_widget)
        
        def update_param(key, value):
            node.params[key] = value
            self._refresh_action_list_text()
        
        # 构建上下文
        main_win = self.window()
        ctx = {
            "main_win": main_win,
            "pictures_dir": self.current_model.pictures_dir if self.current_model else "",
            "internalize_fn": self.current_model.internalize_image if self.current_model else None,
            "on_open_gallery": self._open_gallery,
            "on_sub_action_add": self._add_sub_action,
            "on_sub_action_del": self._del_sub_action,
        }
        
        # 统一分派构建
        built = build_action_props(layout, node, update_param, ctx)
        if not built:
            layout.addRow(QLabel("暂无参数属性"))
        
        # 通用备注行
        append_comment_row(layout, node)
        
        outer.addWidget(form_widget)
        outer.addStretch(1)  # 将内容推到顶部，防止均匀拉伸
        return wrapper
    
    def _sync_meta_offsets(self, node, filename):
        """从 meta.json 同步偏移量到节点参数"""
        if not self.current_model:
            return
        try:
            import template_meta
            meta = template_meta.get(self.current_model.pictures_dir, filename)
            if meta.get("offset_x") is not None:
                node.params["offset_x"] = meta["offset_x"]
            if meta.get("offset_y") is not None:
                node.params["offset_y"] = meta["offset_y"]
        except Exception:
            pass
    
    # =================== 配置同步 ===================
    
    def get_enabled_templates(self) -> list:
        """返回当前启用的模板文件名列表，供引擎调用"""
        return list(self._enabled_templates) if self._enabled_templates else None
    
    def save_config(self):
        """保存当前循环配置到 script.json（config 已通过属性面板实时同步）"""
        if self.current_model:
            self.current_model.save()
            main_win = self.window()
            if hasattr(main_win, '_append_log'):
                main_win._append_log(f"💾 循环脚本已保存: {self.current_model.name}")
    
    def _open_gallery(self, node, mode="multi", param_key="templates"):
        """统一图库入口：在整个 Tab 区域显示图库（全覆盖）
        
        Args:
            node: 当前 ActionNode
            mode: "single" 单选 / "multi" 多选
            param_key: 写回参数的键名（multi→"templates", single→"template"）
        """
        if not self.current_model:
            return
        
        from gui.template_gallery_dialog import TemplateGalleryWidget
        
        pictures_dir = self.current_model.pictures_dir
        
        # 构造当前模板列表（单选模式也转为 list 格式统一处理）
        if mode == "single":
            tpl_val = node.params.get(param_key, "")
            current_templates = [{"template": tpl_val}] if tpl_val else []
        else:
            current_templates = node.params.get(param_key, [])
        
        # 创建图库控件
        gallery = TemplateGalleryWidget(pictures_dir, current_templates, mode=mode, parent=self)
        
        # 绑定主窗口的 ScreenshotWidget
        main_win = self.window()
        sw = getattr(main_win, 'screenshot_widget', None)
        if sw:
            gallery.bind_screenshot_widget(sw)
        
        # 记住当前选中的步骤行号
        prev_row = self.action_list.currentRow()
        
        # 添加为 page_stack 的新页面并切换
        idx = self._page_stack.addWidget(gallery)
        self._page_stack.setCurrentIndex(idx)
        
        # 返回时的处理
        def _on_gallery_closed(updated_templates):
            # 切回编辑器页面
            self._page_stack.setCurrentIndex(0)
            self._page_stack.removeWidget(gallery)
            gallery.deleteLater()
            
            if mode == "single":
                # 单选模式：取第一个选中的文件名写入 param_key
                new_val = updated_templates[0].get("template", "") if updated_templates else ""
                old_val = node.params.get(param_key, "")
                if new_val != old_val:
                    node.params[param_key] = new_val
                    self.current_model.save()
                    if hasattr(main_win, '_append_log'):
                        main_win._append_log(f"📂 已选择模板: {new_val}")
            else:
                # 多选模式：写入模板列表
                old_templates = node.params.get(param_key, [])
                changed = (len(updated_templates) != len(old_templates) or
                           any(u.get("template") != o.get("template")
                               for u, o in zip(updated_templates, old_templates)))
                if changed:
                    node.params[param_key] = updated_templates
                    self.current_model.save()
                    if hasattr(main_win, '_append_log'):
                        main_win._append_log(f"📂 模板已更新: {len(updated_templates)} 个启用")
            
            # 刷新并恢复选中行
            self._reload_action_list_ui()
            if prev_row >= 0 and prev_row < self.action_list.count():
                self.action_list.setCurrentRow(prev_row)
        
        gallery.closed.connect(_on_gallery_closed)
    
    def _add_sub_action(self, node, sub_action_dict):
        """向 multi_match 节点添加子动作并刷新面板"""
        node.params.setdefault("sub_actions", []).append(sub_action_dict)
        self.current_model.save()
        # 刷新属性面板（重新选中当前行触发面板重建）
        row = self.action_list.currentRow()
        self._on_action_selected(row)
    
    def _del_sub_action(self, node, index):
        """从 multi_match 节点删除指定子动作"""
        sub_actions = node.params.get("sub_actions", [])
        if 0 <= index < len(sub_actions):
            sub_actions.pop(index)
            self.current_model.save()
            row = self.action_list.currentRow()
            self._on_action_selected(row)
    
    def _on_convert(self):
        """流水线 → 多模板匹配转换（两步向导，创建新项目）"""
        if not self.current_model:
            QMessageBox.warning(self, "提示", "请先选择一个脚本项目。")
            return
        
        if not self.current_model.actions:
            QMessageBox.warning(self, "提示", "当前脚本没有任何步骤，无法转换。")
            return
        
        # 生成新项目名称（原名_loop，避免重名）
        source_name = self.current_model.name
        base_name = f"{source_name}_loop"
        new_name = base_name
        counter = 1
        while os.path.exists(os.path.join(ScriptModel.SCRIPTS_ROOT, new_name)):
            new_name = f"{base_name}_{counter}"
            counter += 1
        
        # 创建新项目目录和 Pictures 子目录
        new_project_dir = os.path.join(ScriptModel.SCRIPTS_ROOT, new_name)
        new_pictures_dir = os.path.join(new_project_dir, ScriptModel.PICTURES_DIR_NAME)
        os.makedirs(new_pictures_dir, exist_ok=True)
        
        from gui.convert_dialog import ConvertDialog
        dlg = ConvertDialog(self.current_model, new_pictures_dir, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            result = dlg.get_result()
            if result and result.get('type') == 'multi_match':
                # 创建新的 ScriptModel
                new_model = ScriptModel(name=new_name)
                new_model.project_dir = new_project_dir
                
                # 创建 multi_match 动作节点
                multi_node = ActionNode(
                    action_type="multi_match",
                    params={"templates": result['templates']},
                    comment=f"从 {source_name} 转换: {len(result['templates'])} 个模板"
                )
                new_model.add_action(multi_node)
                
                # 保存新项目
                new_model.save()
                
                # 刷新项目列表并切换到新项目
                self._refresh_projects()
                idx = self.project_combo.findText(new_name)
                if idx >= 0:
                    self.project_combo.setCurrentIndex(idx)
                
                main_win = self.window()
                if hasattr(main_win, '_append_log'):
                    main_win._append_log(
                        f"✨ 转换完成：新项目 [{new_name}]（{len(result['templates'])} 个模板）"
                    )
        else:
            # 用户取消 → 清理空项目目录
            import shutil
            if os.path.exists(new_project_dir) and not os.listdir(new_pictures_dir):
                shutil.rmtree(new_project_dir, ignore_errors=True)
