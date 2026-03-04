"""
GUI 公共常量和工具函数：配色方案、字体创建。
"""

from PyQt6.QtGui import QFont


# ===================== 配色常量（手册 §十二） =====================
COLOR_PRIMARY = "#409eff"
COLOR_SUCCESS = "#67c23a"
COLOR_WARNING = "#e6a23c"
COLOR_DANGER = "#f56c6c"
COLOR_BG = "#f5f7fa"
COLOR_BORDER = "#dcdfe6"
COLOR_TEXT = "#2c3e50"
COLOR_DISABLED = "#909399"


def create_font(size=9, bold=False):
    """
    创建标准字体（手册 §二字体渲染优化）。
    中文优先 Microsoft YaHei，使用 PreferNoHinting。
    """
    font = QFont("Microsoft YaHei", size)
    if bold:
        font.setBold(True)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font
