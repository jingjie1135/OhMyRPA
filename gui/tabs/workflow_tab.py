"""
流程编排页（预留占位）：未来用于自由组合脚本。
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

from gui.constants import COLOR_DISABLED, create_font


class WorkflowTab(QWidget):
    """
    流程 Tab 页（预留占位）。
    未来扩展：自由组合脚本为自动化流程。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        placeholder = QLabel("🚧 流程编排功能\n即将推出，敬请期待...\n\n可自由组合多个脚本为自动化流程")
        placeholder.setFont(create_font(12))
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet(f"color: {COLOR_DISABLED};")
        layout.addWidget(placeholder)
