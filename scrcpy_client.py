"""
自研 Scrcpy 客户端：借鉴 QtScrcpy 架构，替代 py-scrcpy-client。

核心改进：
1. H.264 解码器错误恢复（连续失败重建 codec）
2. 帧超时检测（3秒无帧自动重建解码器）
3. 低延迟触摸控制通道（完整 touch_down/move/up 状态机）
4. 使用项目配置的 ADB 路径（兼容雷电等模拟器）

架构：ScrcpyClient（连接管理）+ ControlSender（控制通道）
视频解码集成在 ScrcpyClient._stream_loop 中。
"""

import os
import math
import socket
import struct
import threading
import time
import logging
from typing import Optional, Tuple, Callable, List

import numpy as np
from av.codec import CodecContext
import av.error

logger = logging.getLogger(__name__)

# ==================== 常量 ====================

# 触摸动作
ACTION_DOWN = 0
ACTION_UP = 1
ACTION_MOVE = 2

# 控制消息类型
TYPE_INJECT_KEYCODE = 0
TYPE_INJECT_TEXT = 1
TYPE_INJECT_TOUCH_EVENT = 2
TYPE_INJECT_SCROLL_EVENT = 3

# 解码器错误恢复阈值（H.264 在等到关键帧前解码失败是正常的）
MAX_DECODE_ERRORS = 30
# 帧超时阈值（秒）
FRAME_TIMEOUT_SEC = 5.0


# ==================== ControlSender ====================

class ControlSender:
    """
    scrcpy 控制通道：通过 Socket 发送二进制触摸/按键事件。
    借鉴 QtScrcpy 的 InputManager 设计。
    """

    def __init__(self, control_socket: socket.socket,
                 resolution: Tuple[int, int],
                 socket_lock: threading.Lock):
        self._socket = control_socket
        self._resolution = resolution
        self._lock = socket_lock

    def _send(self, data: bytes) -> None:
        """线程安全地发送控制数据。"""
        if self._socket is None:
            return
        try:
            with self._lock:
                self._socket.send(data)
        except OSError:
            logger.warning("控制通道发送失败（连接可能已断开）")

    def _update_resolution(self, resolution: Tuple[int, int]) -> None:
        """更新设备分辨率（帧大小变化时调用）。"""
        self._resolution = resolution

    # ---------- 触摸事件 ----------

    def _touch_event(self, x: int, y: int, action: int,
                     touch_id: int = -1) -> None:
        """发送原始触摸事件包（v3.3.3 协议）。"""
        x, y = max(x, 0), max(y, 0)
        w, h = self._resolution
        # v3.3.3 二进制格式：type(1) + action(1) + pointerId(8) + x(4) + y(4)
        #   + width(2) + height(2) + pressure(2) + actionButtons(4) + buttons(4)
        data = struct.pack(">B", TYPE_INJECT_TOUCH_EVENT)
        data += struct.pack(
            ">BqiiHHHII",
            action, touch_id,
            int(x), int(y),
            int(w), int(h),
            0xFFFF,        # pressure
            1,             # actionButtons (AMOTION_EVENT_BUTTON_PRIMARY)
            1,             # buttons
        )
        self._send(data)

    def tap(self, x: int, y: int) -> None:
        """低延迟点击（DOWN + UP，<5ms）。"""
        self._touch_event(x, y, ACTION_DOWN)
        self._touch_event(x, y, ACTION_UP)

    def touch_down(self, x: int, y: int, touch_id: int = -1) -> None:
        """手指按下。"""
        self._touch_event(x, y, ACTION_DOWN, touch_id)

    def touch_move(self, x: int, y: int, touch_id: int = -1) -> None:
        """手指移动。"""
        self._touch_event(x, y, ACTION_MOVE, touch_id)

    def touch_up(self, x: int, y: int, touch_id: int = -1) -> None:
        """手指抬起。"""
        self._touch_event(x, y, ACTION_UP, touch_id)

    # ---------- 滑动操作 ----------

    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int = 300, steps: int = 0) -> None:
        """
        带缓动曲线的平滑滑动。
        使用 ease-in-out 缓动函数模拟真实手指滑动。
        """
        if steps <= 0:
            # 根据距离和时长自动计算步数
            dist = math.hypot(x2 - x1, y2 - y1)
            steps = max(10, int(dist / 5))

        interval = duration_ms / 1000.0 / steps

        self.touch_down(x1, y1)
        for i in range(1, steps + 1):
            # ease-in-out 缓动：t 从 0 到 1
            t = i / steps
            ease_t = t * t * (3 - 2 * t)  # smoothstep
            cx = int(x1 + (x2 - x1) * ease_t)
            cy = int(y1 + (y2 - y1) * ease_t)
            self.touch_move(cx, cy)
            time.sleep(interval)
        self.touch_up(x2, y2)

    def swipe_path(self, points: list, duration_ms: int = 500) -> None:
        """
        沿录制轨迹回放（支持曲线路径）。
        points: [(x, y, timestamp_ms), ...] 带时间戳的路径点
        """
        if len(points) < 2:
            return

        self.touch_down(points[0][0], points[0][1])

        # 如果有时间戳则按实际时间间隔回放
        if len(points[0]) >= 3:
            t0 = points[0][2]
            for i in range(1, len(points)):
                x, y = points[i][0], points[i][1]
                dt = (points[i][2] - points[i - 1][2]) / 1000.0
                if dt > 0:
                    time.sleep(min(dt, 0.1))  # 单步最长 100ms 防卡
                self.touch_move(x, y)
        else:
            # 无时间戳，均匀分配
            interval = duration_ms / 1000.0 / (len(points) - 1)
            for i in range(1, len(points)):
                x, y = points[i][0], points[i][1]
                self.touch_move(x, y)
                time.sleep(interval)

        last = points[-1]
        self.touch_up(last[0], last[1])


# ==================== ScrcpyClient ====================

class ScrcpyClient:
    """
    自研 scrcpy 客户端：管理与 Android 设备的连接。

    生命周期：
    1. __init__() → 配置参数
    2. start(threaded=True) → 推送 server、建立连接、启动视频解码线程
    3. last_frame → 获取最新帧 / control → 发送操作
    4. stop() → 断开连接、清理资源
    """

    def __init__(
        self,
        device_id: str,
        max_fps: int = 60,
        bitrate: int = 8_000_000,
        max_width: int = 0,
        block_frame: bool = True,
    ):
        self._device_id = device_id
        self._max_fps = max_fps
        self._bitrate = bitrate
        self._max_width = max_width
        self._block_frame = block_frame

        # 连接状态
        self.alive = False
        self.device_name: Optional[str] = None
        self.resolution: Tuple[int, int] = (0, 0)
        self.last_frame: Optional[np.ndarray] = None

        # Socket 连接
        self._video_socket: Optional[socket.socket] = None
        self._control_socket: Optional[socket.socket] = None
        self._control_lock = threading.Lock()
        self._listen_socket: Optional[socket.socket] = None
        self._server_process = None

        # 控制器（start 后初始化）
        self.control: Optional[ControlSender] = None

        # 回调
        self._frame_listeners: List[Callable] = []
        self._init_listeners: List[Callable] = []

    def add_listener(self, event: str, callback: Callable) -> None:
        """添加事件监听器。event: 'frame' | 'init'"""
        if event == "frame":
            self._frame_listeners.append(callback)
        elif event == "init":
            self._init_listeners.append(callback)

    def remove_listener(self, event: str, callback: Callable) -> None:
        """移除事件监听器。"""
        if event == "frame":
            self._frame_listeners.remove(callback)
        elif event == "init":
            self._init_listeners.remove(callback)

    # ---------- 生命周期 ----------

    def start(self, threaded: bool = True) -> None:
        """启动 scrcpy 客户端：推送 server → 建立连接 → 启动解码线程。"""
        assert not self.alive, "客户端已在运行"

        self._deploy_server()
        self._init_connection()
        self.alive = True

        # 创建控制器
        self.control = ControlSender(
            self._control_socket, self.resolution, self._control_lock
        )

        # 通知 init 监听器
        for cb in self._init_listeners:
            cb()

        if threaded:
            t = threading.Thread(target=self._stream_loop, daemon=True)
            t.start()
        else:
            self._stream_loop()

    def stop(self) -> None:
        """停止客户端，释放所有资源。"""
        self.alive = False

        # 关闭 socket 连接
        for s in (self._control_socket, self._video_socket, self._listen_socket):
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass

        # 终止 server 子进程
        proc = getattr(self, '_server_process', None)
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                pass

        # 清理 adb reverse
        try:
            import config
            import subprocess
            import sys
            _flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            subprocess.run(
                [config.ADB_PATH, "-s", self._device_id, "reverse", "--remove-all"],
                capture_output=True, timeout=5, creationflags=_flags
            )
        except Exception:
            pass

        self._video_socket = None
        self._control_socket = None
        self._listen_socket = None
        self._server_process = None
        self.control = None
        logger.info("[%s] scrcpy 客户端已停止", self._device_id)

    # ---------- 服务器部署 ----------

    def _deploy_server(self) -> None:
        """
        推送并启动 scrcpy-server（reverse 模式，借鉴 QtScrcpy）。

        Reverse 模式协议：
        1. 电脑端先监听一个本地 TCP 端口
        2. adb reverse localabstract:scrcpy tcp:本地端口
        3. 启动 server（不传 tunnel_forward=true）
        4. 设备上的 server 通过 adb reverse 隧道连接到电脑
        5. 电脑端的 TCP 服务器收到两个连接：video + control
        """
        import config
        import subprocess
        import sys

        _flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        adb_path = config.ADB_PATH

        # 查找 server jar 文件
        jar_path = self._find_server_jar()
        remote_path = "/data/local/tmp/scrcpy-server.jar"  # 远程固定路径（与 QtScrcpy 一致）

        # Step 1: 推送 jar 到设备
        r = subprocess.run(
            [adb_path, "-s", self._device_id, "push",
             jar_path, remote_path],
            capture_output=True, text=True, timeout=10, creationflags=_flags
        )
        logger.info("[%s] push: %s (rc=%d)", self._device_id, r.stdout.strip(), r.returncode)

        # Step 2: 清理残留环境
        subprocess.run(
            [adb_path, "-s", self._device_id, "reverse", "--remove-all"],
            capture_output=True, timeout=5, creationflags=_flags
        )
        subprocess.run(
            [adb_path, "-s", self._device_id, "shell",
             "pkill", "-f", "scrcpy"],
            capture_output=True, timeout=5, creationflags=_flags
        )
        time.sleep(1)  # 等待进程完全退出

        # Step 3: 电脑端监听本地端口（TCP 服务器）
        self._listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listen_socket.bind(("127.0.0.1", 0))  # 自动分配端口
        self._listen_socket.listen(2)  # 最多接受 2 个连接（video + control）
        local_port = self._listen_socket.getsockname()[1]
        logger.info("[%s] 本地监听端口: %d", self._device_id, local_port)

        # Step 4: adb reverse（设备端 localabstract:scrcpy → 电脑端 TCP 端口）
        result = subprocess.run(
            [adb_path, "-s", self._device_id, "reverse",
             "localabstract:scrcpy", f"tcp:{local_port}"],
            capture_output=True, text=True, timeout=5, creationflags=_flags
        )
        if result.returncode != 0:
            self._listen_socket.close()
            raise RuntimeError(
                f"adb reverse 失败: {result.stderr.strip()}"
            )
        logger.info("[%s] adb reverse 已建立 (localabstract:scrcpy → tcp:%d)", self._device_id, local_port)

        # 等待 reverse 隧道生效
        time.sleep(0.5)

        # Step 5: 启动 scrcpy-server v3.3.3（reverse 模式，不传 tunnel_forward=true）
        # 注意：尽量减少参数传递，使用 server 默认值（和 QtScrcpy 一致）
        server_cmd = [
            adb_path, "-s", self._device_id, "shell",
            f"CLASSPATH={remote_path}",
            "app_process", "/",
            "com.genymobile.scrcpy.Server",
            "3.3.3",                          # server 版本
            "log_level=info",
            f"video_bit_rate={self._bitrate}",  # v3.x 参数名
            f"max_size={self._max_width}",
            f"max_fps={self._max_fps}",
            "audio=false",                     # v3.x 默认开启音频，这里关闭
            # reverse 模式不传 tunnel_forward
            "control=true",
        ]
        logger.info("[%s] server cmd: %s", self._device_id, " ".join(server_cmd))
        self._server_process = subprocess.Popen(
            server_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_flags
        )
        logger.info("[%s] scrcpy-server v3.3.3 已启动 (pid=%d)", self._device_id, self._server_process.pid)

    def _find_server_jar(self) -> str:
        """查找 scrcpy-server 文件路径（支持 v3.x 无扩展名格式和旧 .jar 格式）。"""
        base_dir = os.path.dirname(os.path.abspath(__file__))

        # 优先级 1：v3.3.3 格式（scrcpy-server，无扩展名）
        server_v3 = os.path.join(base_dir, "scrcpy-server")
        if os.path.exists(server_v3):
            return server_v3

        # 优先级 2：旧 .jar 格式
        server_jar = os.path.join(base_dir, "scrcpy-server.jar")
        if os.path.exists(server_jar):
            return server_jar

        raise FileNotFoundError(
            "找不到 scrcpy-server，请确认文件存在于项目目录"
        )

    # ---------- 连接建立 ----------

    def _init_connection(self) -> None:
        """
        等待设备连接到电脑（reverse 模式）。

        reverse 模式下，设备主动通过 adb reverse 隧道连接到电脑的 TCP 服务器。
        电脑端 accept 两次：第一次是 video socket，第二次是 control socket。
        """
        self._listen_socket.settimeout(15.0)  # server 启动较慢，15 秒超时

        # 后台监控 server stderr
        def _monitor_server():
            if self._server_process and self._server_process.stderr:
                for line in iter(self._server_process.stderr.readline, b''):
                    txt = line.decode('utf-8', errors='replace').rstrip()
                    if txt:
                        logger.warning("[%s] server stderr: %s", self._device_id, txt)

        monitor = threading.Thread(target=_monitor_server, daemon=True)
        monitor.start()

        try:
            # 第一个连接：video socket
            self._video_socket, _ = self._listen_socket.accept()
            logger.info("[%s] video socket 已连接", self._device_id)

            # v3.3.3 不发送 dummy byte（send_dummy_byte 默认 false）
            # 直接等待第二个连接

            # 第二个连接：control socket
            self._control_socket, _ = self._listen_socket.accept()
            logger.info("[%s] control socket 已连接", self._device_id)

        except socket.timeout:
            # 诊断信息
            poll = self._server_process.poll() if self._server_process else "N/A"
            logger.error("[%s] 超时! server poll=%s", self._device_id, poll)
            raise ConnectionError(
                f"[{self._device_id}] 等待设备连接超时（15秒），server进程状态={poll}"
            )
        finally:
            # 关闭监听 socket（不再需要）
            self._listen_socket.close()
            self._listen_socket = None

        # 读取设备信息（v3.3.3 格式：64B 设备名 + 4B AVCodecID + 4B 宽 + 4B 高 = 76 字节）
        device_meta = self._recv_exact(self._video_socket, 76)
        self.device_name = device_meta[:64].decode("utf-8").rstrip("\x00")
        # AVCodecID 4 字节（跳过，当前只支持 H.264）
        width = struct.unpack(">I", device_meta[68:72])[0]
        height = struct.unpack(">I", device_meta[72:76])[0]
        self.resolution = (width, height)

        # 设置非阻塞模式
        self._video_socket.setblocking(False)

        logger.info(
            "[%s] scrcpy 连接成功: %s (%dx%d)",
            self._device_id, self.device_name,
            self.resolution[0], self.resolution[1]
        )

    # ---------- 辅助方法 ----------

    @staticmethod
    def _recv_exact(sock: socket.socket, n: int) -> bytes:
        """阻塞读取恰好 n 个字节。"""
        data = b""
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("连接断开")
            data += chunk
        return data

    # ---------- 视频解码循环 ----------

    def _stream_loop(self) -> None:
        """
        视频流解码主循环（v3.3.3 帧包装协议 + QtScrcpy 错误恢复）。

        v3.3.3 帧格式（send_frame_meta=true）：
        [PTS flags 8B] [packet size 4B] [raw H.264 data ...]
        - PTS bit63 = config packet
        - PTS bit62 = key frame

        核心改进：
        1. 精确读取完整帧（meta header 指定大小）
        2. Config packet 拼接后再送解码器
        3. 连续解码失败重建 codec
        4. 帧有效性校验
        """
        HEADER_SIZE = 12
        SC_PACKET_FLAG_CONFIG = 1 << 63
        SC_PACKET_FLAG_KEY_FRAME = 1 << 62

        codec = CodecContext.create("h264", "r")
        error_count = 0
        last_frame_time = time.monotonic()
        config_data = b""  # 缓存 config packet

        while self.alive:
            try:
                # 读取 12 字节帧头（阻塞模式读帧头）
                self._video_socket.setblocking(True)
                self._video_socket.settimeout(1.0)
                try:
                    header = self._recv_exact(self._video_socket, HEADER_SIZE)
                except (socket.timeout, ConnectionError):
                    # 超时检测
                    if (time.monotonic() - last_frame_time) > FRAME_TIMEOUT_SEC:
                        logger.warning(
                            "[%s] 帧超时 %.1f 秒，重建解码器",
                            self._device_id, FRAME_TIMEOUT_SEC
                        )
                        codec = CodecContext.create("h264", "r")
                        last_frame_time = time.monotonic()
                    continue

                # 解析 meta header
                pts_flags = struct.unpack(">Q", header[:8])[0]
                pkt_size = struct.unpack(">I", header[8:12])[0]

                if pkt_size == 0:
                    continue

                # 读取帧数据
                raw_data = self._recv_exact(self._video_socket, pkt_size)

                is_config = bool(pts_flags & SC_PACKET_FLAG_CONFIG)
                is_keyframe = bool(pts_flags & SC_PACKET_FLAG_KEY_FRAME)

                if is_config:
                    # Config packet: 缓存，等待下一个 data packet 再一起送解码器
                    config_data = raw_data
                    continue

                # Data packet: 如果有缓存的 config，拼接在前面
                if config_data:
                    raw_data = config_data + raw_data
                    config_data = b""

                # 送 H.264 数据到解码器
                packets = codec.parse(raw_data)
                for packet in packets:
                    if is_keyframe:
                        packet.is_keyframe = True
                    try:
                        frames = codec.decode(packet)
                        error_count = 0
                    except av.error.InvalidDataError:
                        error_count += 1
                        if error_count >= MAX_DECODE_ERRORS:
                            logger.debug(
                                "[%s] 连续 %d 次解码失败，重建解码器（等待关键帧）",
                                self._device_id, error_count
                            )
                            codec = CodecContext.create("h264", "r")
                            error_count = 0
                        continue

                    for frame in frames:
                        bgr = frame.to_ndarray(format="bgr24")

                        # 帧有效性校验
                        if bgr.mean() < 1.0:
                            continue

                        self.last_frame = bgr
                        new_res = (bgr.shape[1], bgr.shape[0])
                        if new_res != self.resolution:
                            self.resolution = new_res
                            if self.control:
                                self.control._update_resolution(new_res)

                        last_frame_time = time.monotonic()

                        for cb in self._frame_listeners:
                            try:
                                cb(bgr)
                            except Exception:
                                pass

            except OSError as e:
                if self.alive:
                    logger.error("[%s] 视频流异常: %s", self._device_id, e)
                break

        logger.info("[%s] 视频解码循环已退出", self._device_id)
