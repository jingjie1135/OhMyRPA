"""
GUI 包：统一导出主窗口和入口函数。
"""

import sys
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from gui.main_window import MainWindow


def main():
    """GUI 程序入口。"""
    app = QApplication(sys.argv)

    # 全局字体渲染优化（手册 §二）
    font = QFont("Microsoft YaHei", 9)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


__all__ = ['MainWindow', 'main']
