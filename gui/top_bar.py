import sys
import os
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QApplication, QMainWindow, QWidget, QVBoxLayout, QDialog
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon, QPixmap

class DonateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("赞赏作者")
        self.resize(380, 520)
        self.setMinimumSize(380, 520)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        icon_path = os.path.join(os.path.dirname(__file__), "app_icon.png")
        if os.path.exists(icon_path): self.setWindowIcon(QIcon(icon_path))
        self.initUI()


    def initUI(self):
        self.setStyleSheet("""
            QDialog { background-color: #f0f2f5; }
            QLabel#tipLabel { color: #2c3e50; font-size: 16px; font-weight: bold; }
            QLabel#subLabel { color: #7f8c8d; font-size: 12px; }
            QPushButton#confirmBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #67c23a, stop:1 #85ce61);
                color: white; border: none; border-radius: 20px; font-size: 16px; font-weight: bold;
            }
            QPushButton#confirmBtn:disabled { background: #c0c4cc; color: #909399; }
            QPushButton#confirmBtn:hover:!disabled {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #85ce61, stop:1 #a4da6a);
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(15)
        
        tip_label = QLabel("如果本软件对你有帮助，请赞赏支持，感谢！")
        tip_label.setObjectName("tipLabel")
        tip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tip_label.setWordWrap(True)
        layout.addWidget(tip_label)
        
        qr_label = QLabel()
        qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_path = os.path.join(os.path.dirname(__file__), "donate_qr.png")
        if os.path.exists(qr_path):
            pixmap = QPixmap(qr_path)
            dpr = self.devicePixelRatio()
            target_width = int(280 * dpr)
            scaled = pixmap.scaledToWidth(target_width, Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            qr_label.setPixmap(scaled)
        else:
            qr_label.setText("收款码图片未找到")
            qr_label.setStyleSheet("color: #e74c3c; font-size: 14px;")
        layout.addWidget(qr_label)
        
        sub_label = QLabel("微信/支付宝扫码赞赏")
        sub_label.setObjectName("subLabel")
        sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub_label)
        
        layout.addStretch()
        self.confirm_btn = QPushButton("我已赞赏 (3)")
        self.confirm_btn.setObjectName("confirmBtn")
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.setFixedSize(160, 44)
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.clicked.connect(self.accept)
        layout.addWidget(self.confirm_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.countdown = 3
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_countdown)
        self.timer.start(1000)

    def update_countdown(self):
        self.countdown -= 1
        if self.countdown > 0:
            self.confirm_btn.setText(f"我已赞赏 ({self.countdown})")
        else:
            self.confirm_btn.setText("我已赞赏")
            self.confirm_btn.setEnabled(True)
            self.timer.stop()

class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关于")
        self.resize(420, 580)
        self.setMinimumSize(420, 580)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        icon_path = os.path.join(os.path.dirname(__file__), "app_icon.png")
        if os.path.exists(icon_path): self.setWindowIcon(QIcon(icon_path))
        self.initUI()


    def initUI(self):
        self.setStyleSheet("""
            QDialog { background-color: #f8f9fa; }
            QLabel#titleLabel { color: #2c3e50; font-size: 20px; font-weight: bold; }
            QLabel#versionLabel { color: #7f8c8d; font-size: 12px; }
            QLabel#descLabel { color: #34495e; font-size: 13px; line-height: 1.5; }
            QLabel#infoLabel { color: #2c3e50; font-size: 13px; }
            QLabel#copyrightLabel { color: #95a5a6; font-size: 11px; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(12)
        
        title_label = QLabel("镜界自动化")
        title_label.setObjectName("titleLabel")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        version_label = QLabel("版本 v0.1")
        version_label.setObjectName("versionLabel")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)
        layout.addSpacing(10)
        
        desc_label = QLabel(
            "<b>软件简介</b><br>"
            "一个强大的通用模拟器自动化控制框架，<br>"
            "帮助您自动完成各类重复性的繁杂操作。<br><br>"
            "<b>核心特性</b><br>"
            "✓ 纯视觉方案 - 安全无注入<br>"
            "✓ 全面兼容 - 支持雷电、MUMU 及各类安卓模拟器<br>"
            "✓ 跨设备群控 - 支持多台模拟器并行独立执行<br>"
            "✓ 可视化节点 - 直观的条件逻辑与循环控制编辑<br>"
            "✓ 稳健纠错机制 - 自动处理应用闪退与网络异常"
        )
        desc_label.setObjectName("descLabel")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)
        layout.addSpacing(10)
        
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #dcdfe6;")
        line.setFixedHeight(1)
        layout.addWidget(line)
        layout.addSpacing(8)
        
        home_label = QLabel('作者主页: <a href="https://space.bilibili.com/1499434734" style="color: #3498db;">Bilibili</a>')
        home_label.setOpenExternalLinks(True)
        layout.addWidget(home_label)
        
        layout.addWidget(QLabel("联系作者: QQ 2283348039"))
        
        copyright_label = QLabel("© 2025-2026 镜界工作室")
        copyright_label.setObjectName("copyrightLabel")
        layout.addWidget(copyright_label)
        layout.addSpacing(8)
        
        qr_tip = QLabel("关注公众号获取更多工具")
        qr_tip.setStyleSheet("color: #7f8c8d; font-size: 12px;")
        qr_tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(qr_tip)
        
        qr_label = QLabel()
        qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_path = os.path.join(os.path.dirname(__file__), "official_qr.png")
        if os.path.exists(qr_path):
            pixmap = QPixmap(qr_path)
            dpr = self.devicePixelRatio()
            target_width = int(340 * dpr)
            scaled = pixmap.scaledToWidth(target_width, Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            qr_label.setPixmap(scaled)
        layout.addWidget(qr_label)


class TopBar(QFrame):
    """
    通用顶栏组件
    提供带标题和右侧操作按钮的标准顶栏。
    """
    
    # 按钮点击信号
    donate_clicked = pyqtSignal()
    about_clicked = pyqtSignal()

    def __init__(self, title_text="软件标题", parent=None):
        super().__init__(parent)
        self.title_text = title_text
        self.initUI()

    def initUI(self):
        """初始化顶栏的界面和样式"""
        self.setObjectName("headerFrame")
        self.setFixedHeight(50)
        
        # 顶栏专属 CSS 样式
        self.setStyleSheet("""
            QFrame#headerFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1a2a3a, stop:0.5 #2c3e50, stop:1 #1a2a3a);
                border-bottom: 2px solid #409eff;
            }
            QLabel#headerTitle {
                color: white; font-size: 16px; font-weight: bold; letter-spacing: 2px;
            }
            QPushButton#donateBtn {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #e74c3c, stop:1 #c0392b);
                color: white; border: none; border-radius: 6px; padding: 8px 16px; font-size: 12px; font-weight: bold;
            }
            QPushButton#donateBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ff6b5b, stop:1 #e74c3c);
            }
            QPushButton#aboutBtn {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #5dade2, stop:1 #3498db);
                color: white; border: none; border-radius: 6px; padding: 8px 16px; font-size: 12px; font-weight: bold;
            }
            QPushButton#aboutBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #7ec8e3, stop:1 #5dade2);
            }
        """)

        # 横向布局
        hl = QHBoxLayout(self)
        hl.setContentsMargins(20, 0, 20, 0)
        
        # 左侧：软件标题
        title_label = QLabel(self.title_text)
        title_label.setObjectName("headerTitle")
        hl.addWidget(title_label)
        
        # 中间：拉伸空白，将按钮推向右侧
        hl.addStretch()
        
        # 右侧：赞赏作者按钮
        self.donate_btn = QPushButton("❤ 赞赏作者")
        self.donate_btn.setObjectName("donateBtn")
        self.donate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.donate_btn.clicked.connect(self.show_donate)
        hl.addWidget(self.donate_btn)

        # 右侧：关于按钮
        self.about_btn = QPushButton("ℹ 关于")
        self.about_btn.setObjectName("aboutBtn")
        self.about_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.about_btn.clicked.connect(self.show_about)
        hl.addWidget(self.about_btn)

    def show_donate(self):
        """显示赞赏对话框，并触发信号"""
        DonateDialog(self).exec()
        self.donate_clicked.emit()
        
    def show_about(self):
        """显示关于对话框，并触发信号"""
        AboutDialog(self).exec()
        self.about_clicked.emit()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 创建一个测试主窗口
    test_window = QMainWindow()
    test_window.setWindowTitle("顶栏组件独立预览")
    test_window.resize(600, 400)
    
    # 强制设置全局背景为常见主窗口背景色，以凸显顶栏
    test_window.setStyleSheet("QMainWindow { background-color: #f5f7fa; }")
    
    # 将顶栏放入布局并展现
    central_widget = QWidget()
    test_layout = QVBoxLayout(central_widget)
    test_layout.setContentsMargins(0, 0, 0, 0)
    test_layout.setSpacing(0)
    
    top_bar = TopBar("顶栏独立预览效果")
    
    test_layout.addWidget(top_bar)
    test_layout.addStretch()  # 其他部分留白
    
    test_window.setCentralWidget(central_widget)
    test_window.show()
    
    sys.exit(app.exec())
