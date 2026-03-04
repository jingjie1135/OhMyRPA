"""
GUI 包：统一导出主窗口和入口函数。
"""

import sys
import os
from PyQt6.QtCore import QTranslator, QLocale, QLibraryInfo
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication

from gui.main_window import MainWindow

# 应用图标路径
_ICON_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon.png")


def main():
    """GUI 程序入口。"""
    app = QApplication(sys.argv)

    # 设置全局应用图标（窗口 + 任务栏 + 所有提示框）
    if os.path.isfile(_ICON_PATH):
        app.setWindowIcon(QIcon(_ICON_PATH))

    # 加载 Qt 中文翻译（汉化 OK/Cancel/Yes/No 等标准按钮）
    translator = QTranslator()
    translations_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(QLocale(QLocale.Language.Chinese), "qtbase", "_", translations_path):
        app.installTranslator(translator)

    # 全局字体渲染优化
    font = QFont("Microsoft YaHei", 9)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


__all__ = ['MainWindow', 'main']
