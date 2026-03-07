"""
截图后台线程：单次截图（ADB）和实时同步（自研 scrcpy 客户端）。
"""

import time
import logging

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage

logger = logging.getLogger(__name__)


class ScreencapWorker(QThread):
    """
    截图后台线程：
    - 单次截图：使用 ADB screencap（capture_once）
    - 实时同步：使用自研 ScrcpyClient H.264 流式传输（30fps+）
    """

    # 截图完成信号：发送 QImage 到 GUI
    screenshot_ready = pyqtSignal(QImage)
    # 日志信号
    log_signal = pyqtSignal(str)
    # FPS 信号
    fps_signal = pyqtSignal(float)
    # ScrcpyAdapter 就绪信号：通知 GUI 可使用低延迟操作
    adapter_ready = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._device_id = ""
        self._continuous = False
        self._pending = False
        self._scrcpy_client = None  # ScrcpyClient 实例引用

    def setup(self, device_id, continuous=False, interval_ms=0):
        """配置截图参数。"""
        self._device_id = device_id
        self._continuous = continuous

    def capture_once(self):
        """单次截图（ADB 方式，非阻塞）。"""
        self._continuous = False
        self._pending = True
        if not self.isRunning():
            self.start()

    @property
    def scrcpy_client(self):
        """获取 ScrcpyClient 实例（供外部获取控制器等）。"""
        return self._scrcpy_client

    def run(self):
        """线程入口：根据模式选择截图方式。"""
        if self._continuous:
            self._run_scrcpy()
        else:
            self._run_adb_once()

    def _run_adb_once(self):
        """ADB 单次截图模式。"""
        import cv2
        from adb_utils import screencap_fast, screencap_to_memory

        while not self.isInterruptionRequested():
            if not self._pending:
                break
            self._pending = False

            screen = screencap_fast(self._device_id)
            if screen is None:
                screen = screencap_to_memory(self._device_id)

            if screen is not None:
                rgb = cv2.cvtColor(screen, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb.shape
                q_img = QImage(rgb.data, w, h, ch * w,
                               QImage.Format.Format_RGB888).copy()
                self.screenshot_ready.emit(q_img)
            else:
                self.log_signal.emit(f"[{self._device_id}] 截图失败")

            if not self._pending:
                break

    def _run_scrcpy(self):
        """
        Scrcpy 流式传输模式：使用自研 ScrcpyClient。
        带 H.264 解码错误恢复 + 帧超时检测。
        """
        import cv2
        from scrcpy_client import ScrcpyClient
        from device_adapter import ScrcpyAdapter

        self.log_signal.emit("正在启动 scrcpy 流式传输...")

        # FPS 计算
        frame_count = 0
        fps_start = time.monotonic()

        # 帧回调：scrcpy 解码后的帧为 BGR numpy ndarray
        def on_frame(frame):
            nonlocal frame_count, fps_start

            if self.isInterruptionRequested():
                return

            if frame is None:
                return

            # BGR → RGB → QImage
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            q_img = QImage(rgb.data, w, h, ch * w,
                           QImage.Format.Format_RGB888).copy()
            self.screenshot_ready.emit(q_img)

            # FPS 计算
            frame_count += 1
            elapsed = time.monotonic() - fps_start
            if elapsed >= 1.0:
                fps = frame_count / elapsed
                self.fps_signal.emit(fps)
                frame_count = 0
                fps_start = time.monotonic()

        client = None
        try:
            # 创建自研 scrcpy 客户端
            client = ScrcpyClient(
                device_id=self._device_id,
                max_fps=60,
                bitrate=8_000_000,
                block_frame=True,
            )
            client.add_listener("frame", on_frame)

            # 启动（推送 server + 连接 + 解码线程）
            client.start(threaded=True)

            self._scrcpy_client = client
            self.log_signal.emit(
                f"scrcpy 连接成功: {client.device_name} "
                f"({client.resolution[0]}×{client.resolution[1]})"
            )

            # 创建 ScrcpyAdapter 并通知 GUI
            adapter = ScrcpyAdapter(self._device_id, client)
            self.adapter_ready.emit(adapter)

            # 主循环：等待中断信号
            while not self.isInterruptionRequested() and client.alive:
                self.msleep(100)

        except Exception as e:
            self.log_signal.emit(f"scrcpy 启动失败: {str(e)}")
            logger.exception("[%s] scrcpy 启动异常", self._device_id)
        finally:
            self._scrcpy_client = None
            if client is not None:
                try:
                    client.stop()
                except Exception:
                    pass
            self.log_signal.emit("scrcpy 已断开")
