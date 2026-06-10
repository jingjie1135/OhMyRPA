"""
流程编排 Tab：三栏式布局，用于串联多个脚本项目为自动化流水线。

布局：
  ┌─ 顶部工具栏 ─────────────────────────────────────────────────┐
  │ 流程: [▼ 选择]  [+ 新建]  [🔄]              [📱 设备管理]     │
  ├─ 左侧 ────────┬─ 中间 ──────────────┬─ 右侧 ─────────────────┤
  │ 指令工具箱     │ 流程步骤列表         │ 属性面板               │
  │ (双击添加)     │ (拖拽排序)           │ (步骤属性/流程属性)     │
  └────────────────┴─────────────────────┴────────────────────────┘

属性面板行为：
  - 无步骤选中 → 显示流程属性（设备批次配置 + 设备选择器入口）
  - 选中步骤 → 显示该步骤的属性编辑器
"""

import os
import json
import uuid

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QListWidget, QListWidgetItem, QPushButton, QComboBox,
    QLabel, QGroupBox, QSplitter, QMessageBox,
    QTreeWidget, QTreeWidgetItem, QStackedWidget, QLineEdit,
    QScrollArea, QInputDialog,
)

from script_model import ScriptModel, ActionNode
from gui.constants import create_font, COLOR_DANGER, COLOR_SUCCESS

# =================== 流程数据模型 ===================

# 流程文件存储目录（与 Scripts/ 同级）
WORKFLOWS_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "Workflows"
)


class WorkflowModel:
    """
    流程数据模型：步骤序列 + 设备批次配置。

    存储结构（与 ScriptModel 一致的项目文件夹模式）：
        Workflows/
          <流程名>/
            workflow.json   # 流程配置
            Pictures/       # 流程专属图库
    """

    def __init__(self, name: str = ""):
        self.name = name
        self.project_dir: str = ""         # 项目文件夹路径
        self.steps: list[ActionNode] = []  # 复用 ActionNode 数据结构
        self.batches: list[dict] = []      # 设备批次列表

    @property
    def pictures_dir(self) -> str:
        """流程专属图库目录"""
        if self.project_dir:
            return os.path.join(self.project_dir, "Pictures")
        return ""

    def add_step(self, node: ActionNode):
        self.steps.append(node)

    def remove_step(self, node_id: str):
        self.steps = [s for s in self.steps if s.id != node_id]

    def save(self):
        """保存流程到项目文件夹"""
        if not self.project_dir:
            self.project_dir = os.path.join(WORKFLOWS_ROOT, self.name)
        os.makedirs(self.project_dir, exist_ok=True)
        os.makedirs(self.pictures_dir, exist_ok=True)  # 自动创建 Pictures/

        filepath = os.path.join(self.project_dir, "workflow.json")
        data = {
            "name": self.name,
            "steps": [
                {"id": s.id, "type": s.type, "params": s.params,
                 "comment": getattr(s, 'comment', '')}
                for s in self.steps
            ],
            "batches": self.batches,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, name: str) -> 'WorkflowModel':
        """从项目文件夹加载流程"""
        project_dir = os.path.join(WORKFLOWS_ROOT, name)
        filepath = os.path.join(project_dir, "workflow.json")

        # 兼容旧版扁平 JSON 文件（自动迁移）
        if not os.path.isfile(filepath):
            old_path = os.path.join(WORKFLOWS_ROOT, f"{name}.json")
            if os.path.isfile(old_path):
                os.makedirs(project_dir, exist_ok=True)
                os.rename(old_path, filepath)

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        model = cls(name=data.get("name", name))
        model.project_dir = project_dir
        for step_data in data.get("steps", []):
            node = ActionNode(
                action_type=step_data.get("type", ""),
                params=step_data.get("params", {}),
                comment=step_data.get("comment", ""),
            )
            # 恢复原始 ID
            if "id" in step_data:
                node.id = step_data["id"]
            model.steps.append(node)
        model.batches = data.get("batches", [])
        return model

    @staticmethod
    def list_workflows() -> list[str]:
        """列出所有已保存的流程名称"""
        if not os.path.isdir(WORKFLOWS_ROOT):
            return []
        results = []
        for entry in os.listdir(WORKFLOWS_ROOT):
            entry_path = os.path.join(WORKFLOWS_ROOT, entry)
            # 新格式：文件夹 + workflow.json
            if os.path.isdir(entry_path) and os.path.isfile(
                os.path.join(entry_path, "workflow.json")
            ):
                results.append(entry)
            # 兼容旧格式：扁平 .json 文件
            elif entry.endswith(".json") and os.path.isfile(entry_path):
                results.append(os.path.splitext(entry)[0])
        return sorted(results)


# =================== 流程 Tab ===================

class WorkflowTab(QWidget):
    """流程编排 Tab — 三栏式布局"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_model: WorkflowModel | None = None
        self._init_ui()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # 顶层页面栈：page0=编辑器, page1=设备选择器（全覆盖）
        self._page_stack = QStackedWidget()
        outer.addWidget(self._page_stack)

        # ===== Page 0: 编辑器主体 =====
        editor_page = QWidget()
        root = QVBoxLayout(editor_page)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)

        # =================== 顶部工具栏 ===================
        toolbar = QHBoxLayout()

        toolbar.addWidget(QLabel("🔗 流程:"))
        self.workflow_combo = QComboBox()
        self.workflow_combo.setMinimumWidth(150)
        self.workflow_combo.currentTextChanged.connect(self._on_workflow_changed)
        toolbar.addWidget(self.workflow_combo)

        new_btn = QPushButton("+ 新建")
        new_btn.setFont(create_font())
        new_btn.setToolTip("创建新流程")
        new_btn.clicked.connect(self._on_new_workflow)
        toolbar.addWidget(new_btn)

        refresh_btn = QPushButton("🔄")
        refresh_btn.setToolTip("刷新流程列表")
        refresh_btn.setFixedSize(36, 28)
        refresh_btn.clicked.connect(self._refresh_workflows)
        toolbar.addWidget(refresh_btn)

        toolbar.addStretch()

        # 当前流程名称标签
        self.model_label = QLabel("未加载流程")
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
        self.toolbox_tree.setIndentation(12)
        self._populate_toolbox()
        left_layout.addWidget(self.toolbox_tree)

        # ================= 中间：步骤列表 =================
        center_widget = QGroupBox("流程步骤")
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
        self.delete_btn.clicked.connect(self._on_delete_step)
        step_btns.addWidget(self.delete_btn)

        self.save_btn = QPushButton("💾 保存")
        self.save_btn.clicked.connect(self._on_save)
        step_btns.addWidget(self.save_btn)
        step_btns.addStretch()
        center_layout.addLayout(step_btns)

        # ================= 右侧：属性面板 =================
        right_widget = QGroupBox("属性面板")
        right_widget.setMinimumWidth(220)
        right_layout = QVBoxLayout(right_widget)

        # 用 QScrollArea 包裹属性面板
        props_scroll = QScrollArea()
        props_scroll.setWidgetResizable(True)
        props_scroll.setStyleSheet("QScrollArea { border: none; }")

        self.props_stack = QStackedWidget()

        # 默认无选中时的提示
        empty_prop = QLabel("请先创建或选择一个流程")
        empty_prop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_prop.setStyleSheet("color: #888;")
        self.props_stack.addWidget(empty_prop)

        props_scroll.setWidget(self.props_stack)
        right_layout.addWidget(props_scroll)

        # 加入分割器
        splitter.addWidget(left_widget)
        splitter.addWidget(center_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([190, 340, 250])

        root.addWidget(splitter, stretch=1)

        self._page_stack.addWidget(editor_page)  # page 0 = 编辑器

        # ================= 信号连接 =================
        self.toolbox_tree.itemDoubleClicked.connect(self._on_toolbox_double_clicked)
        self.action_list.currentRowChanged.connect(self._on_step_selected)
        self.action_list.model().rowsMoved.connect(self._on_steps_reordered)

        # 初始化流程列表
        self._refresh_workflows()

    # =================== 左侧工具箱 ===================

    def _populate_toolbox(self):
        """填充左侧指令工具箱（复用 ACTION_REGISTRY，包含脚本编排分类）"""
        from gui.action_props import ACTION_REGISTRY
        categories = {}
        for type_key, (icon, display_name, category) in ACTION_REGISTRY.items():
            # 流程 Tab 排除"流程控制"分类（loop_start / loop_end）
            if category == "流程控制":
                continue
            if category not in categories:
                categories[category] = []
            categories[category].append((type_key, icon, display_name))

        for cat_name, items in categories.items():
            cat = QTreeWidgetItem(self.toolbox_tree, [cat_name])
            for type_key, icon, display_name in items:
                child = QTreeWidgetItem(cat, [f"{icon} {display_name}"])
                child.setData(0, Qt.ItemDataRole.UserRole, type_key)
        self.toolbox_tree.expandAll()

    def _on_toolbox_double_clicked(self, item: QTreeWidgetItem, column: int):
        """双击工具箱项，添加新步骤"""
        action_type = item.data(0, Qt.ItemDataRole.UserRole)
        if not action_type or not self.current_model:
            return

        # 默认参数模板
        default_params = {
            "run_script": {"script_project": ""},
            "tap": {"x": 0, "y": 0},
            "sleep": {"seconds": 1.0},
            "swipe": {"x1": 0, "y1": 0, "x2": 0, "y2": 0, "duration": 300},
            "find_and_tap": {"template": "", "threshold": 0.9, "timeout": 3.0},
            "multi_match": {"templates": [], "sub_actions": []},
            "wait_image": {"template": "", "timeout": 30.0, "action_on_fail": "abort"},
        }.get(action_type, {})

        node = ActionNode(action_type=action_type, params=default_params)
        self.current_model.add_step(node)
        self._add_node_to_ui_list(node)

    def _add_node_to_ui_list(self, node: ActionNode):
        """将节点添加到中间步骤列表 UI"""
        list_item = QListWidgetItem()
        list_item.setData(Qt.ItemDataRole.UserRole, node.id)
        self.action_list.addItem(list_item)
        self._refresh_action_list_text()

    # =================== 流程管理 ===================

    def _refresh_workflows(self):
        """刷新流程下拉列表"""
        self.workflow_combo.blockSignals(True)
        current = self.workflow_combo.currentText()
        self.workflow_combo.clear()
        workflows = WorkflowModel.list_workflows()
        self.workflow_combo.addItems(workflows)
        idx = self.workflow_combo.findText(current)
        if idx >= 0:
            self.workflow_combo.setCurrentIndex(idx)
        self.workflow_combo.blockSignals(False)

        # 如果有流程但未恢复之前的选中项，自动加载当前项
        if idx < 0 and self.workflow_combo.count() > 0:
            self._on_workflow_changed(self.workflow_combo.currentText())

    def _on_workflow_changed(self, name: str):
        """下拉框选中流程后自动加载"""
        if not name:
            return
        try:
            model = WorkflowModel.load(name)
            self._load_model(model)
        except Exception as e:
            QMessageBox.warning(self, "加载失败", f"无法加载流程 \"{name}\":\n{e}")

    def _on_new_workflow(self):
        """创建新流程"""
        name, ok = QInputDialog.getText(self, "新建流程", "流程名称:")
        if not ok or not name.strip():
            return
        name = name.strip()

        # 检查重名
        if name in WorkflowModel.list_workflows():
            QMessageBox.warning(self, "名称冲突", f"流程 \"{name}\" 已存在。")
            return

        model = WorkflowModel(name=name)
        model.save()
        self._refresh_workflows()
        idx = self.workflow_combo.findText(name)
        if idx >= 0:
            self.workflow_combo.setCurrentIndex(idx)
        self._load_model(model)

        main_win = self.window()
        if hasattr(main_win, '_append_log'):
            main_win._append_log(f"📋 已创建新流程: {name}")

    def _load_model(self, model: WorkflowModel):
        """加载模型到 UI"""
        self.current_model = model
        self.model_label.setText(f"🔗 {model.name}")
        self.model_label.setStyleSheet("color: #4fc3f7; font-weight: bold;")
        self._reload_action_list_ui()

    # =================== 中间步骤列表 ===================

    def _reload_action_list_ui(self):
        """根据 current_model 重建步骤列表"""
        self.action_list.clear()

        if not self.current_model:
            return

        for node in self.current_model.steps:
            list_item = QListWidgetItem()
            list_item.setData(Qt.ItemDataRole.UserRole, node.id)
            self.action_list.addItem(list_item)

        self._refresh_action_list_text()
        # 无步骤选中 → 显示流程属性
        self._show_workflow_config()

    def _refresh_action_list_text(self):
        """刷新步骤列表的显示文本"""
        from gui.action_props import format_action_text
        if not self.current_model:
            return
        for i in range(self.action_list.count()):
            item = self.action_list.item(i)
            node_id = item.data(Qt.ItemDataRole.UserRole)
            node = next((n for n in self.current_model.steps if n.id == node_id), None)
            if not node:
                continue
            item.setText(f"{i+1}. {format_action_text(node)}")

    def _on_steps_reordered(self):
        """拖拽排序后同步 model.steps 顺序"""
        if not self.current_model:
            return
        id_order = []
        for i in range(self.action_list.count()):
            item = self.action_list.item(i)
            id_order.append(item.data(Qt.ItemDataRole.UserRole))
        id_to_node = {n.id: n for n in self.current_model.steps}
        self.current_model.steps = [id_to_node[nid] for nid in id_order if nid in id_to_node]
        self._refresh_action_list_text()

    def _on_delete_step(self):
        """删除当前选中的步骤"""
        row = self.action_list.currentRow()
        if row < 0 or not self.current_model:
            return

        item = self.action_list.item(row)
        node_id = item.data(Qt.ItemDataRole.UserRole)
        self.current_model.remove_step(node_id)
        self.action_list.takeItem(row)
        self._refresh_action_list_text()

    def _on_save(self):
        """保存当前流程"""
        if self.current_model:
            self.current_model.save()
            main_win = self.window()
            if hasattr(main_win, '_append_log'):
                main_win._append_log(f"💾 流程已保存: {self.current_model.name}")

    # =================== 右侧属性面板 ===================

    def _on_step_selected(self, row: int):
        """选中步骤时切换右侧属性面板"""
        if row < 0:
            self._show_workflow_config()
            return

        item = self.action_list.item(row)
        node_id = item.data(Qt.ItemDataRole.UserRole)
        if not self.current_model:
            return
        node = next((n for n in self.current_model.steps if n.id == node_id), None)
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

    def _show_workflow_config(self):
        """
        在右侧属性面板显示流程属性（设备批次配置）。
        当无步骤选中时显示。
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)

        if not self.current_model:
            layout.addWidget(QLabel("请先创建或选择一个流程"))
            self._set_props_widget(widget)
            return

        # 流程信息
        title = QLabel("📋 流程属性")
        title.setFont(create_font(10, bold=True))
        layout.addWidget(title)

        form = QFormLayout()
        form.addRow("流程名称:", QLabel(self.current_model.name))
        form.addRow("总步骤数:", QLabel(str(len(self.current_model.steps))))

        # 统计脚本引用
        script_count = sum(1 for s in self.current_model.steps if s.type == "run_script")
        form.addRow("脚本引用:", QLabel(f"{script_count} 个"))
        layout.addLayout(form)

        # 分隔
        layout.addWidget(QLabel(""))

        # ===== 设备批次区域 =====
        batch_title = QLabel("── 设备批次 ──")
        batch_title.setFont(create_font(9, bold=True))
        batch_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(batch_title)

        batches = self.current_model.batches
        if batches:
            for b in batches:
                name = b.get("name", "未命名")
                devices = b.get("devices", [])
                device_names = ", ".join(d.get("name", "?") for d in devices[:3])
                if len(devices) > 3:
                    device_names += f" +{len(devices)-3}"
                batch_label = QLabel(f"📦 {name}: {len(devices)}台 ({device_names})")
                batch_label.setStyleSheet("font-size: 12px; padding: 2px;")
                batch_label.setWordWrap(True)
                layout.addWidget(batch_label)
        else:
            no_batch = QLabel("暂未配置设备批次")
            no_batch.setStyleSheet("color: #888;")
            no_batch.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(no_batch)

        # 配置设备列表按钮
        device_btn = QPushButton("📱 配置设备列表")
        device_btn.setFont(create_font(9, bold=True))
        device_btn.setFixedHeight(32)
        device_btn.setStyleSheet("""
            QPushButton {
                background: #2d5aa0;
                color: white;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background: #3a6ec0;
            }
        """)
        device_btn.clicked.connect(self._open_device_selector)
        layout.addWidget(device_btn)

        layout.addStretch()
        self._set_props_widget(widget)

    def _create_props_widget(self, node) -> QWidget:
        """根据 ActionNode 类型动态生成参数面板"""
        from gui.action_props import build_action_props, append_comment_row

        wrapper = QWidget()
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        form_widget = QWidget()
        layout = QFormLayout(form_widget)

        def update_param(key, value):
            node.params[key] = value
            self._refresh_action_list_text()

        # 尝试从节点参数中推断当前脚本项目的图库目录
        pictures_dir = self._resolve_pictures_dir(node)

        def internalize_fn(src_path: str) -> str:
            """将外部图片复制到当前 pictures_dir（如果有的话）"""
            if not pictures_dir or not os.path.isdir(pictures_dir):
                return os.path.basename(src_path)
            import shutil
            dst = os.path.join(pictures_dir, os.path.basename(src_path))
            if src_path != dst:
                shutil.copy2(src_path, dst)
            return os.path.basename(src_path)

        # 构建上下文，传入图库回调（与 script_tab 保持一致）
        main_win = self.window()
        ctx = {
            "main_win": main_win,
            "pictures_dir": pictures_dir,
            "internalize_fn": internalize_fn,
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
        outer.addStretch(1)
        return wrapper

    def _resolve_pictures_dir(self, node) -> str:
        """
        推断图库目录，优先级：
        1. 当前流程项目自带的 Pictures/
        2. 节点引用的脚本项目图库
        3. 降级到第一个脚本项目的图库
        """
        # 优先使用流程项目自带的图库
        if self.current_model and self.current_model.pictures_dir:
            pic_dir = self.current_model.pictures_dir
            os.makedirs(pic_dir, exist_ok=True)
            return pic_dir

        # 降级：查找节点引用的脚本项目图库
        project_name = node.params.get("script_project", "")
        if not project_name and self.current_model:
            for step in self.current_model.steps:
                if step.type == "run_script":
                    project_name = step.params.get("script_project", "")
                    if project_name:
                        break

        if project_name:
            project_dir = os.path.join(ScriptModel.SCRIPTS_ROOT, project_name)
            pictures_dir = os.path.join(project_dir, "Pictures")
            if os.path.isdir(pictures_dir):
                return pictures_dir

        return ""

    def _open_gallery(self, node, mode: str = "single", param_key: str = "template"):
        """
        打开模板图库，供流程 Tab 中的指令选择模板图片。
        优先使用流程项目自带的 Pictures 图库。
        """
        from gui.template_gallery_dialog import TemplateGalleryWidget

        # 优先使用流程自带的 Pictures 目录
        preferred_dir = self._resolve_pictures_dir(node)
        if not preferred_dir:
            QMessageBox.information(
                self, "提示",
                "当前流程未保存或无可用图库。\n请先保存流程或在「脚本」Tab 中创建脚本项目。"
            )
            return

        os.makedirs(preferred_dir, exist_ok=True)

        # 构造当前模板列表
        if mode == "single":
            tpl_val = node.params.get(param_key, "")
            current_templates = [{"template": tpl_val}] if tpl_val else []
        else:
            raw_list = node.params.get(param_key, [])
            current_templates = raw_list if isinstance(raw_list, list) else []

        gallery = TemplateGalleryWidget(
            pictures_dir=preferred_dir,
            current_templates=current_templates,
            mode=mode,
            parent=self,
        )

        # 绑定 ScreenshotWidget（使找图测试可获取当前截图）
        main_win = self.window()
        sw = getattr(main_win, 'screenshot_widget', None)
        if sw:
            gallery.bind_screenshot_widget(sw)

        idx = self._page_stack.addWidget(gallery)
        self._page_stack.setCurrentIndex(idx)

        def _on_gallery_closed(result):
            # 切回编辑器
            self._page_stack.setCurrentIndex(0)
            self._page_stack.removeWidget(gallery)
            gallery.deleteLater()

            # 空结果 = 取消/未选择，保持原配置不变（与脚本/循环 Tab 行为一致，
            # 避免用户点「返回」却把已配置的模板清空）
            if not result:
                return

            # 写回参数
            if mode == "single":
                tpl_name = result[0].get("template", "")
                node.params[param_key] = tpl_name
            else:
                node.params[param_key] = result

            self._refresh_action_list_text()
            # 刷新属性面板（显示新选的模板）
            row = self.action_list.currentRow()
            self._on_step_selected(row)

        gallery.closed.connect(_on_gallery_closed)

    def _add_sub_action(self, node, sub_action_dict):
        """向 multi_match 节点添加子动作"""
        node.params.setdefault("sub_actions", []).append(sub_action_dict)
        if self.current_model:
            self.current_model.save()
        row = self.action_list.currentRow()
        self._on_step_selected(row)

    def _del_sub_action(self, node, index):
        """从 multi_match 节点删除子动作"""
        sub_actions = node.params.get("sub_actions", [])
        if 0 <= index < len(sub_actions):
            sub_actions.pop(index)
            if self.current_model:
                self.current_model.save()
            row = self.action_list.currentRow()
            self._on_step_selected(row)

    # =================== 设备选择器 ===================

    def _open_device_selector(self):
        """切换到设备选择器全屏页面"""
        if not self.current_model:
            return

        from gui.device_selector import DeviceSelectorWidget

        selector = DeviceSelectorWidget(
            current_batches=self.current_model.batches,
            parent=self,
        )

        idx = self._page_stack.addWidget(selector)
        self._page_stack.setCurrentIndex(idx)

        def _on_selector_closed(batches_list):
            # 切回编辑器页面
            self._page_stack.setCurrentIndex(0)
            self._page_stack.removeWidget(selector)
            selector.deleteLater()

            # 更新批次数据
            self.current_model.batches = batches_list
            self.current_model.save()

            # 刷新属性面板
            self._show_workflow_config()

            main_win = self.window()
            if hasattr(main_win, '_append_log'):
                total_devices = sum(len(b.get("devices", [])) for b in batches_list)
                main_win._append_log(
                    f"📱 设备批次已更新: {len(batches_list)} 个批次, 共 {total_devices} 台设备"
                )

        selector.closed.connect(_on_selector_closed)
