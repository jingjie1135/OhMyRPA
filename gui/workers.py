"""
截图后台线程：单次截图（ADB）和实时同步（scrcpy）。
"""

import time

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage


class ScreencapWorker(QThread):
    """
    截图后台线程：
    - 单次截图：使用 ADB screencap（capture_once）
    - 实时同步：使用 scrcpy H.264 流式传输（30fps+）
    """

    # 截图完成信号：发送 QImage 到 GUI
    screenshot_ready = pyqtSignal(QImage)
    # 日志信号
    log_signal = pyqtSignal(str)
    # FPS 信号
    fps_signal = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._device_id = ""
        self._continuous = False
        self._pending = False

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
        Scrcpy 流式传输模式：H.264 硬件编码 + 实时解码。
        使用 py-scrcpy-client 库，可达 30fps+。
        """
        import os
        import scrcpy
        import adbutils
        import config

        # 关键：monkey-patch adbutils，强制使用我们配置的 ADB（雷电模拟器版本），
        # 避免 adbutils 自带的 ADB（高版本）kill 掉模拟器的 ADB 服务器
        adbutils.adb_path = lambda: config.ADB_PATH
        adbutils.get_adb_exe = lambda: config.ADB_PATH

        self.log_signal.emit("正在启动 scrcpy 流式传输...")

        # FPS 计算
        frame_count = 0
        fps_start = time.monotonic()
        frame_received = False

        # 帧回调：scrcpy 解码后的帧为 BGR numpy ndarray
        def on_frame(frame):
            nonlocal frame_count, fps_start, frame_received

            if self.isInterruptionRequested():
                return

            if frame is None:
                return

            frame_received = True

            # BGR → RGB → QImage
            import cv2
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
            # Monkey-patch scrcpy 的流循环，添加 H.264 解码错误容错
            import av.error
            from av.codec import CodecContext as _CC
            def _patched_stream_loop(self_client):
                """带容错的视频流解析循环。"""
                codec = _CC.create("h264", "r")
                while self_client.alive:
                    try:
                        raw_h264 = self_client._Client__video_socket.recv(0x10000)
                        packets = codec.parse(raw_h264)
                        for packet in packets:
                            try:
                                frames = codec.decode(packet)
                            except av.error.InvalidDataError:
                                # 跳过损坏的 H.264 包（常见于流中断/丢帧）
                                continue
                            for frame in frames:
                                frame = frame.to_ndarray(format="bgr24")
                                if self_client.flip:
                                    import cv2
                                    frame = cv2.flip(frame, 1)
                                self_client.last_frame = frame
                                self_client.resolution = (frame.shape[1], frame.shape[0])
                                self_client._Client__send_to_listeners("frame", frame)
                    except BlockingIOError:
                        time.sleep(0.01)
                        if not self_client.block_frame:
                            self_client._Client__send_to_listeners("frame", None)
                    except OSError as e:
                        if self_client.alive:
                            raise e

            scrcpy.Client._Client__stream_loop = _patched_stream_loop

            # 创建 scrcpy 客户端
            client = scrcpy.Client(
                device=self._device_id,
                max_fps=60,
                bitrate=6_000_000,  # 原生分辨率需要更高码率
                block_frame=True,
            )
            client.add_listener(scrcpy.EVENT_FRAME, on_frame)

            self.log_signal.emit("scrcpy 连接成功，正在同步画面...")

            # 启动帧循环
            client.start(threaded=True)

            # 主循环：如果回调方式不工作，用轮询 last_frame 作为备选
            while not self.isInterruptionRequested():
                if frame_received:
                    self.msleep(50)
                    continue

                # 备选：轮询 client.last_frame
                if client.last_frame is not None:
                    on_frame(client.last_frame)

                self.msleep(33)  # ~30fps

        except Exception as e:
            self.log_signal.emit(f"scrcpy 启动失败: {str(e)}")
        finally:
            if client is not None:
                try:
                    client.stop()
                except Exception:
                    pass
            self.log_signal.emit("scrcpy 已断开")
