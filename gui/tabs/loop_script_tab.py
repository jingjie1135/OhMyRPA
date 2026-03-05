"""
循环脚本 Tab：导入顺序脚本项目，以循环模式管理和运行。
布局：
  ┌─ 顶部工具栏 ──────────────────────────────────────┐
  │ 导入脚本: [下拉框 ▼] [导入]  循环次数/间隔/默认坐标 │
  ├─ 左侧 ──────────┬─ 右侧 ──────────────────────────┤
  │ 模板缩略图列表    │ 选中模板的详情/子动作编辑         │
  │ (勾选启用/禁用)   │                                 │
  └──────────────────┴─────────────────────────────────┘
"""

import os
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QListWidget, QListWidgetItem, QPushButton, QComboBox,
    QSpinBox, QDoubleSpinBox, QLabel, QGroupBox,
    QSplitter, QCheckBox, QMessageBox,
)

from script_model import ScriptModel
from gui.constants import create_font


class LoopScriptTab(QWidget):
    """循环脚本管理 Tab"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_model = None       # 当前加载的 ScriptModel
        self._enabled_templates = set() # 启用的模板文件名集合
        self._template_items = {}       # {filename: QListWidgetItem}
        self._init_ui()
    
    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        
        # =================== 顶部：导入 + 循环参数 ===================
        toolbar = QHBoxLayout()
        
        # 项目选择
        toolbar.addWidget(QLabel("📂 导入脚本:"))
        self.project_combo = QComboBox()
        self.project_combo.setMinimumWidth(150)
        toolbar.addWidget(self.project_combo)
        
        import_btn = QPushButton("📥 导入")
        import_btn.setToolTip("将选中脚本项目导入循环模式")
        import_btn.clicked.connect(self._on_import)
        toolbar.addWidget(import_btn)
        
        refresh_btn = QPushButton("🔄")
        refresh_btn.setToolTip("刷新项目列表")
        refresh_btn.setFixedWidth(30)
        refresh_btn.clicked.connect(self._refresh_projects)
        toolbar.addWidget(refresh_btn)
        
        toolbar.addStretch()
        
        # 循环参数
        toolbar.addWidget(QLabel("循环次数:"))
        self.spin_max_loops = QSpinBox()
        self.spin_max_loops.setRange(0, 99999)
        self.spin_max_loops.setSpecialValueText("无限")
        self.spin_max_loops.setToolTip("0 = 无限循环")
        self.spin_max_loops.valueChanged.connect(self._sync_config)
        toolbar.addWidget(self.spin_max_loops)
        
        toolbar.addWidget(QLabel("间隔:"))
        self.spin_interval = QDoubleSpinBox()
        self.spin_interval.setRange(0.1, 60.0)
        self.spin_interval.setSuffix(" 秒")
        self.spin_interval.setValue(1.0)
        self.spin_interval.valueChanged.connect(self._sync_config)
        toolbar.addWidget(self.spin_interval)
        
        root.addLayout(toolbar)
        
        # 默认坐标行
        default_row = QHBoxLayout()
        default_row.addWidget(QLabel("无匹配时默认点击:"))
        self.spin_def_x = QSpinBox()
        self.spin_def_x.setRange(0, 4000)
        self.spin_def_x.setPrefix("X=")
        self.spin_def_x.valueChanged.connect(self._sync_config)
        default_row.addWidget(self.spin_def_x)
        self.spin_def_y = QSpinBox()
        self.spin_def_y.setRange(0, 4000)
        self.spin_def_y.setPrefix("Y=")
        self.spin_def_y.valueChanged.connect(self._sync_config)
        default_row.addWidget(self.spin_def_y)
        
        # 当前脚本名称标签
        self.model_label = QLabel("未导入脚本")
        self.model_label.setStyleSheet("color: #888; font-style: italic;")
        default_row.addStretch()
        default_row.addWidget(self.model_label)
        
        root.addLayout(default_row)
        
        # =================== 主区域：模板列表 + 详情 ===================
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧：模板缩略图列表
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        left_layout.addWidget(QLabel("📋 监视模板（勾选=启用）"))
        
        self.template_list = QListWidget()
        self.template_list.setIconSize(QSize(64, 64))
        self.template_list.itemChanged.connect(self._on_item_check_changed)
        self.template_list.currentItemChanged.connect(self._on_template_selected)
        left_layout.addWidget(self.template_list)
        
        # 全选/取消按钮
        btn_row = QHBoxLayout()
        sel_all_btn = QPushButton("全选")
        sel_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        btn_row.addWidget(sel_all_btn)
        desel_btn = QPushButton("全不选")
        desel_btn.clicked.connect(lambda: self._set_all_checked(False))
        btn_row.addWidget(desel_btn)
        left_layout.addLayout(btn_row)
        
        splitter.addWidget(left)
        
        # 右侧：选中模板详情
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        right_layout.addWidget(QLabel("📝 模板详情"))
        
        self.detail_group = QGroupBox()
        self.detail_layout = QFormLayout(self.detail_group)
        self.detail_layout.addRow("选中模板查看详情", QLabel(""))
        right_layout.addWidget(self.detail_group)
        
        right_layout.addStretch()
        splitter.addWidget(right)
        
        splitter.setSizes([300, 400])
        root.addWidget(splitter)
        
        # 初始化项目列表
        self._refresh_projects()
    
    # =================== 项目管理 ===================
    
    def _refresh_projects(self):
        """刷新可导入的脚本项目列表"""
        self.project_combo.clear()
        projects = ScriptModel.list_projects()
        self.project_combo.addItems(projects)
    
    def _on_import(self):
        """导入选中的脚本项目"""
        project_name = self.project_combo.currentText()
        if not project_name:
            return
        
        project_dir = os.path.join(ScriptModel.SCRIPTS_ROOT, project_name)
        model = ScriptModel.load_from_project(project_dir)
        self.current_model = model
        
        # 同步 UI
        self.model_label.setText(f"🔄 {model.name}")
        self.model_label.setStyleSheet("color: #4fc3f7; font-weight: bold;")
        
        # 加载循环配置
        cfg = model.config
        self.spin_max_loops.setValue(cfg.max_loops)
        self.spin_interval.setValue(cfg.scan_interval)
        self.spin_def_x.setValue(cfg.default_tap_x)
        self.spin_def_y.setValue(cfg.default_tap_y)
        
        # 加载模板列表
        self._load_templates()
    
    def _load_templates(self):
        """从项目 Pictures/ 目录加载模板缩略图列表"""
        self.template_list.clear()
        self._template_items.clear()
        self._enabled_templates.clear()
        
        if not self.current_model:
            return
        
        pics_dir = self.current_model.pictures_dir
        if not os.path.isdir(pics_dir):
            return
        
        # 同时从 actions 中收集已有的 find_and_tap 模板（用于自动勾选）
        actions_templates = set()
        for action in self.current_model.actions:
            if action.type == "find_and_tap":
                tpl = action.params.get("template", "")
                actions_templates.add(os.path.basename(tpl))
        
        for filename in sorted(os.listdir(pics_dir)):
            if not filename.lower().endswith(('.png', '.jpg', '.bmp')):
                continue
            if filename == "meta.json":
                continue
            
            filepath = os.path.join(pics_dir, filename)
            item = QListWidgetItem()
            item.setText(filename)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            
            # 如果模板在 actions 的 find_and_tap 中出现过，默认勾选
            if actions_templates and filename in actions_templates:
                item.setCheckState(Qt.CheckState.Checked)
                self._enabled_templates.add(filename)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            
            # 缩略图
            pixmap = QPixmap(filepath)
            if not pixmap.isNull():
                item.setIcon(QIcon(pixmap.scaled(
                    64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )))
            
            self.template_list.addItem(item)
            self._template_items[filename] = item
    
    def _on_item_check_changed(self, item):
        """模板勾选状态改变时更新启用集合"""
        filename = item.text()
        if item.checkState() == Qt.CheckState.Checked:
            self._enabled_templates.add(filename)
        else:
            self._enabled_templates.discard(filename)
    
    def _set_all_checked(self, checked: bool):
        """全选/全不选"""
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.template_list.count()):
            self.template_list.item(i).setCheckState(state)
    
    def _on_template_selected(self, current, previous):
        """选中模板时显示详情"""
        # 清除旧内容
        while self.detail_layout.rowCount() > 0:
            self.detail_layout.removeRow(0)
        
        if not current or not self.current_model:
            self.detail_layout.addRow("选中模板查看详情", QLabel(""))
            return
        
        filename = current.text()
        filepath = os.path.join(self.current_model.pictures_dir, filename)
        
        # 缩略图预览
        pixmap = QPixmap(filepath)
        if not pixmap.isNull():
            preview = QLabel()
            preview.setPixmap(pixmap.scaled(
                200, 200, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))
            self.detail_layout.addRow("预览:", preview)
        
        self.detail_layout.addRow("文件名:", QLabel(filename))
        
        # 从 meta.json 读取偏移量
        import template_meta
        meta = template_meta.get(self.current_model.pictures_dir, filename)
        ox = meta.get("offset_x", 0)
        oy = meta.get("offset_y", 0)
        self.detail_layout.addRow("偏移 X:", QLabel(str(ox)))
        self.detail_layout.addRow("偏移 Y:", QLabel(str(oy)))
        
        # 查找对应的 find_and_tap action，显示阈值
        for action in self.current_model.actions:
            if action.type == "find_and_tap":
                tpl_name = os.path.basename(action.params.get("template", ""))
                if tpl_name == filename:
                    th = action.params.get("threshold", 0.9)
                    self.detail_layout.addRow("匹配阈值:", QLabel(f"{th:.2f}"))
                    # 统计子动作
                    sub_count = 0
                    idx = self.current_model.actions.index(action)
                    for j in range(idx + 1, len(self.current_model.actions)):
                        sub = self.current_model.actions[j]
                        if sub.type == "find_and_tap":
                            break
                        if sub.type in ("tap", "sleep", "swipe"):
                            sub_count += 1
                    if sub_count > 0:
                        self.detail_layout.addRow("绑定子动作:", QLabel(f"{sub_count} 个"))
                    break
    
    # =================== 配置同步 ===================
    
    def _sync_config(self):
        """将 UI 参数同步到 model.config"""
        if not self.current_model:
            return
        cfg = self.current_model.config
        cfg.max_loops = self.spin_max_loops.value()
        cfg.scan_interval = self.spin_interval.value()
        cfg.default_tap_x = self.spin_def_x.value()
        cfg.default_tap_y = self.spin_def_y.value()
    
    def get_enabled_templates(self) -> list:
        """返回当前启用的模板文件名列表，供引擎调用"""
        return list(self._enabled_templates) if self._enabled_templates else None
    
    def save_config(self):
        """保存当前循环配置到 script.json"""
        if self.current_model:
            self._sync_config()
            self.current_model.save()
