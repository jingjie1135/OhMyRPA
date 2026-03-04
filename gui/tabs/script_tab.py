"""
脚本功能页（原神秘商店）：参数调整 + 控制按钮 + 快捷操作。
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QPushButton, QSpinBox, QDoubleSpinBox,
)

from config import (
    Y_OFFSET, REFRESH_BTN_POS, CLICK_DELAY,
    REFRESH_WAIT, MATCH_THRESHOLD, LOOP_INTERVAL,
)
from shop_bot import RuntimeConfig
from gui.constants import create_font


class ScriptTab(QWidget):
    """
    脚本功能 Tab 页：参数调整滑动条 + 控制按钮 + 快捷操作。
    （原 ShopTab，语义化重命名）
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        """构建界面。"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ===== 参数调整组 =====
        params_group = QGroupBox("参数调整")
        params_group.setFont(create_font(9, bold=True))
        params_layout = QGridLayout(params_group)
        params_layout.setSpacing(8)

        # Y 轴偏移量
        self.y_offset_spin = QSpinBox()
        self.y_offset_spin.setRange(0, 500)
        self.y_offset_spin.setValue(Y_OFFSET)
        self.y_offset_spin.setSuffix(" px")
        self.y_offset_spin.setFont(create_font())
        self._add_param_row(params_layout, 0, "Y轴偏移:", self.y_offset_spin)

        # 刷新按钮 X 坐标
        self.refresh_x_spin = QSpinBox()
        self.refresh_x_spin.setRange(0, 2000)
        self.refresh_x_spin.setValue(REFRESH_BTN_POS[0])
        self.refresh_x_spin.setSuffix(" px")
        self.refresh_x_spin.setFont(create_font())
        self._add_param_row(params_layout, 1, "刷新按钮X:", self.refresh_x_spin)

        # 刷新按钮 Y 坐标
        self.refresh_y_spin = QSpinBox()
        self.refresh_y_spin.setRange(0, 2000)
        self.refresh_y_spin.setValue(REFRESH_BTN_POS[1])
        self.refresh_y_spin.setSuffix(" px")
        self.refresh_y_spin.setFont(create_font())
        self._add_param_row(params_layout, 2, "刷新按钮Y:", self.refresh_y_spin)

        # 点击延迟
        self.click_delay_spin = QDoubleSpinBox()
        self.click_delay_spin.setRange(0.01, 5.0)
        self.click_delay_spin.setValue(CLICK_DELAY)
        self.click_delay_spin.setSingleStep(0.05)
        self.click_delay_spin.setSuffix(" 秒")
        self.click_delay_spin.setDecimals(2)
        self.click_delay_spin.setFont(create_font())
        self._add_param_row(params_layout, 3, "点击延迟:", self.click_delay_spin)

        # 刷新等待
        self.refresh_wait_spin = QDoubleSpinBox()
        self.refresh_wait_spin.setRange(0.1, 10.0)
        self.refresh_wait_spin.setValue(REFRESH_WAIT)
        self.refresh_wait_spin.setSingleStep(0.1)
        self.refresh_wait_spin.setSuffix(" 秒")
        self.refresh_wait_spin.setDecimals(1)
        self.refresh_wait_spin.setFont(create_font())
        self._add_param_row(params_layout, 4, "刷新等待:", self.refresh_wait_spin)

        # 匹配阈值
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.5, 1.0)
        self.threshold_spin.setValue(MATCH_THRESHOLD)
        self.threshold_spin.setSingleStep(0.05)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setFont(create_font())
        self._add_param_row(params_layout, 5, "匹配阈值:", self.threshold_spin)

        # 主循环间隔
        self.loop_interval_spin = QDoubleSpinBox()
        self.loop_interval_spin.setRange(0.05, 5.0)
        self.loop_interval_spin.setValue(LOOP_INTERVAL)
        self.loop_interval_spin.setSingleStep(0.05)
        self.loop_interval_spin.setSuffix(" 秒")
        self.loop_interval_spin.setDecimals(2)
        self.loop_interval_spin.setFont(create_font())
        self._add_param_row(params_layout, 6, "循环间隔:", self.loop_interval_spin)

        layout.addWidget(params_group)

        # ===== 控制按钮组 =====
        ctrl_group = QGroupBox("控制")
        ctrl_group.setFont(create_font(9, bold=True))
        ctrl_layout = QHBoxLayout(ctrl_group)

        self.start_btn = QPushButton("▶ 启动")
        self.start_btn.setFont(create_font(10, bold=True))
        self.start_btn.setFixedSize(90, 36)
        self.start_btn.setObjectName("successBtn")

        self.pause_btn = QPushButton("⏸ 暂停")
        self.pause_btn.setFont(create_font(10, bold=True))
        self.pause_btn.setFixedSize(90, 36)
        self.pause_btn.setObjectName("warningBtn")
        self.pause_btn.setEnabled(False)

        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.setFont(create_font(10, bold=True))
        self.stop_btn.setFixedSize(90, 36)
        self.stop_btn.setObjectName("dangerBtn")
        self.stop_btn.setEnabled(False)

        ctrl_layout.addWidget(self.start_btn)
        ctrl_layout.addWidget(self.pause_btn)
        ctrl_layout.addWidget(self.stop_btn)

        layout.addWidget(ctrl_group)
        layout.addStretch()

    def _add_param_row(self, grid_layout, row, label_text, widget):
        """向网格布局添加 标签 + 控件 行。"""
        label = QLabel(label_text)
        label.setFont(create_font())
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        grid_layout.addWidget(label, row, 0)
        grid_layout.addWidget(widget, row, 1)

    def get_runtime_config(self):
        """从 UI 控件读取当前参数，构建 RuntimeConfig。"""
        config = RuntimeConfig()
        config.y_offset = self.y_offset_spin.value()
        config.refresh_btn_x = self.refresh_x_spin.value()
        config.refresh_btn_y = self.refresh_y_spin.value()
        config.click_delay = self.click_delay_spin.value()
        config.refresh_wait = self.refresh_wait_spin.value()
        config.match_threshold = self.threshold_spin.value()
        config.loop_interval = self.loop_interval_spin.value()
        return config

    def sync_to_runtime_config(self, config):
        """将 UI 控件最新值同步到运行时配置（实时热更新）。"""
        config.y_offset = self.y_offset_spin.value()
        config.refresh_btn_x = self.refresh_x_spin.value()
        config.refresh_btn_y = self.refresh_y_spin.value()
        config.click_delay = self.click_delay_spin.value()
        config.refresh_wait = self.refresh_wait_spin.value()
        config.match_threshold = self.threshold_spin.value()
        config.loop_interval = self.loop_interval_spin.value()
