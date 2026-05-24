"""
QThread 工作线程：桥接 GUI 界面与业务逻辑。
通过 pyqtSignal 信号槽与 UI 层通信，遵循 PyQt6 手册第九章多线程规范。
"""

import threading
import cv2
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage

from script_engine import ScriptEngine
from script_model import ScriptModel


class BotWorker(QThread):
    """
    通用脚本执行工作线程。
    继承 QThread，使用 pyqtSignal 发射状态到 GUI 主线程。
    """

    # ========== 信号定义 ==========
    # 日志消息 → GUI 日志区
    log_signal = pyqtSignal(str)
    # 截图图像 → GUI 预览区
    screenshot_signal = pyqtSignal(QImage)
    # 匹配结果列表 → GUI 标记绘制 [(名称, cx, cy, 置信度), ...]
    match_signal = pyqtSignal(list)
    # 运行状态文本 → GUI 状态栏
    status_signal = pyqtSignal(str)
    # 线程完成信号
    finished_signal = pyqtSignal()

    def __init__(self, device_id, script_model: ScriptModel = None,
                 loop_mode: bool = False, enabled_templates: list = None,
                 adapter=None, parent=None):
        """
        初始化工作线程。

        Args:
            device_id (str): 目标设备 ID
            script_model (ScriptModel): JSON 解析后的动作对象
            loop_mode (bool): 是否以循环模式运行
            enabled_templates (list): 循环模式下启用的模板文件名列表
            adapter: 可选的自定义设备驱动
            parent: 父 QObject
        """
        super().__init__(parent)
        self.device_id = device_id
        self.script_model = script_model or ScriptModel()
        self.loop_mode = loop_mode
        self.enabled_templates = enabled_templates
        self.adapter = adapter

        # 暂停控制事件：set=运行, clear=暂停
        self._pause_event = threading.Event()
        self._pause_event.set()  # 默认运行状态

    def run(self):
        """
        线程执行入口：根据 loop_mode 选择顺序或循环执行。
        """
        self.status_signal.emit("运行中")

        callbacks = {
            'on_log': self._on_log,
            'on_screenshot': self._on_screenshot,
            'on_match': self._on_match,
        }

        self.engine = ScriptEngine(
            model=self.script_model,
            device_id=self.device_id,
            pause_event=self._pause_event,
            interrupt_check=self.isInterruptionRequested,
            callbacks=callbacks,
            adapter=self.adapter
        )
        
        if self.loop_mode:
            self.engine.run_loop(self.enabled_templates)
        else:
            self.engine.run()

        self.status_signal.emit("已停止")
        self.finished_signal.emit()

    def pause(self):
        """暂停工作线程。"""
        self._pause_event.clear()
        self.status_signal.emit("已暂停")

    def resume(self):
        """恢复工作线程。"""
        self._pause_event.set()
        self.status_signal.emit("运行中")

    def is_paused(self):
        """检查是否处于暂停状态。"""
        return not self._pause_event.is_set()

    def stop(self):
        """
        安全停止工作线程（手册 §六资源保护）。
        先恢复暂停（避免死锁），再请求中断。
        """
        self._pause_event.set()  # 确保不阻塞在暂停
        self.requestInterruption()

    # ========== 回调方法：将数据通过信号发送到 GUI ==========

    def _on_log(self, msg):
        """日志回调 → 信号。"""
        self.log_signal.emit(msg)

    def _on_screenshot(self, cv_img):
        """
        截图回调 → 转换为 QImage → 信号。
        OpenCV BGR → Qt RGB 格式转换。
        """
        if cv_img is None:
            return
        try:
            # BGR → RGB
            rgb_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_img.shape
            bytes_per_line = ch * w
            # 创建 QImage（需要保持数据引用，使用 .copy()）
            q_img = QImage(rgb_img.data, w, h, bytes_per_line,
                           QImage.Format.Format_RGB888).copy()
            self.screenshot_signal.emit(q_img)
        except Exception:
            pass  # 忽略转换异常，不影响主流程

    def _on_match(self, matches):
        """匹配结果回调 → 信号。"""
        self.match_signal.emit(matches)
