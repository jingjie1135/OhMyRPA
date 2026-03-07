"""
统一设备交互接口（DeviceAdapter）。

遵循 DRY 原则，所有设备操作（截图、点击、滑动、触摸状态机）
均通过 DeviceAdapter 接口访问，调用方无需关心底层实现。

两个实现：
- AdbAdapter：基于 ADB 命令（无损截图、群控友好、无状态）
- ScrcpyAdapter：基于 scrcpy 协议（实时帧流、低延迟触摸、仅用于 GUI 预览/录制）
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class DeviceAdapter(ABC):
    """
    统一设备交互接口（抽象基类）。

    所有调用方（script_engine、shop_bot、widgets 等）仅依赖此接口，
    不直接调用 adb_utils 或 scrcpy_client。
    """

    @property
    @abstractmethod
    def device_id(self) -> str:
        """设备 ID。"""
        ...

    @abstractmethod
    def get_frame(self) -> Optional[np.ndarray]:
        """
        获取当前画面帧（BGR numpy 数组）。
        AdbAdapter 返回无损 PNG 截图，ScrcpyAdapter 返回 H.264 解码帧。
        """
        ...

    @abstractmethod
    def tap(self, x: int, y: int) -> None:
        """点击指定坐标。"""
        ...

    @abstractmethod
    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int = 300) -> None:
        """直线滑动。"""
        ...

    def touch_down(self, x: int, y: int, touch_id: int = -1) -> None:
        """手指按下（默认不支持，子类可覆盖）。"""
        raise NotImplementedError("此 Adapter 不支持精细触摸操作")

    def touch_move(self, x: int, y: int, touch_id: int = -1) -> None:
        """手指移动（默认不支持，子类可覆盖）。"""
        raise NotImplementedError("此 Adapter 不支持精细触摸操作")

    def touch_up(self, x: int, y: int, touch_id: int = -1) -> None:
        """手指抬起（默认不支持，子类可覆盖）。"""
        raise NotImplementedError("此 Adapter 不支持精细触摸操作")

    def swipe_path(self, points: list, duration_ms: int = 500) -> None:
        """
        沿路径滑动（默认用直线 swipe 近似）。
        points: [(x, y, timestamp_ms), ...] 路径点列表
        """
        if len(points) < 2:
            return
        start = points[0]
        end = points[-1]
        self.swipe(start[0], start[1], end[0], end[1], duration_ms)

    @property
    def supports_touch(self) -> bool:
        """是否支持精细触摸操作（touch_down/move/up）。"""
        return False


# ==================== AdbAdapter ====================

class AdbAdapter(DeviceAdapter):
    """
    基于 ADB 命令的设备适配器。

    特点：
    - 无损 PNG 截图（画质保证，适合模板匹配）
    - 无状态（天然支持群控多设备并行）
    - 每次操作独立 subprocess，延迟 100-300ms
    """

    def __init__(self, device_id: str):
        self._device_id = device_id

    @property
    def device_id(self) -> str:
        return self._device_id

    def get_frame(self) -> Optional[np.ndarray]:
        """ADB 无损截图：优先用 screencap_fast，失败回退 screencap_to_memory。"""
        from adb_utils import screencap_fast, screencap_to_memory
        frame = screencap_fast(self._device_id)
        if frame is None:
            frame = screencap_to_memory(self._device_id)
        return frame

    def tap(self, x: int, y: int) -> None:
        from adb_utils import tap as adb_tap
        adb_tap(self._device_id, x, y)

    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int = 300) -> None:
        from adb_utils import swipe as adb_swipe
        adb_swipe(self._device_id, x1, y1, x2, y2, duration_ms)


# ==================== ScrcpyAdapter ====================

class ScrcpyAdapter(DeviceAdapter):
    """
    基于 scrcpy 协议的设备适配器。

    特点：
    - H.264 实时帧流（<1ms 获取，有损压缩）
    - Socket 低延迟触摸（<5ms，完整 touch_down/move/up 状态机）
    - 仅用于 GUI 实时预览和录制模式
    - 一对一持久连接，不适合群控
    """

    def __init__(self, device_id: str, scrcpy_client=None):
        """
        Args:
            device_id: 设备 ID
            scrcpy_client: ScrcpyClient 实例（从 workers.py 传入）
        """
        self._device_id = device_id
        self._client = scrcpy_client

    @property
    def device_id(self) -> str:
        return self._device_id

    def set_client(self, client) -> None:
        """设置/更新 ScrcpyClient 引用。"""
        self._client = client

    @property
    def client(self):
        """获取 ScrcpyClient 实例（供外部获取连接状态等）。"""
        return self._client

    def get_frame(self) -> Optional[np.ndarray]:
        """从 scrcpy 内存帧池获取最新帧（H.264 解码，<1ms）。"""
        if self._client and self._client.last_frame is not None:
            return self._client.last_frame
        return None

    def tap(self, x: int, y: int) -> None:
        """通过 scrcpy 控制通道发送点击（<5ms）。"""
        if self._client and self._client.alive:
            self._client.control.tap(x, y)
        else:
            logger.warning("ScrcpyAdapter: 连接未就绪，tap 操作被忽略")

    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int = 300) -> None:
        """通过 scrcpy 控制通道发送带缓动的平滑滑动。"""
        if self._client and self._client.alive:
            self._client.control.swipe(x1, y1, x2, y2, duration_ms)
        else:
            logger.warning("ScrcpyAdapter: 连接未就绪，swipe 操作被忽略")

    def touch_down(self, x: int, y: int, touch_id: int = -1) -> None:
        """手指按下（通过 scrcpy 控制通道）。"""
        if self._client and self._client.alive:
            self._client.control.touch_down(x, y, touch_id)

    def touch_move(self, x: int, y: int, touch_id: int = -1) -> None:
        """手指移动（通过 scrcpy 控制通道）。"""
        if self._client and self._client.alive:
            self._client.control.touch_move(x, y, touch_id)

    def touch_up(self, x: int, y: int, touch_id: int = -1) -> None:
        """手指抬起（通过 scrcpy 控制通道）。"""
        if self._client and self._client.alive:
            self._client.control.touch_up(x, y, touch_id)

    def swipe_path(self, points: list, duration_ms: int = 500) -> None:
        """沿路径滑动（通过 scrcpy 控制通道，支持曲线轨迹）。"""
        if self._client and self._client.alive:
            self._client.control.swipe_path(points, duration_ms)
        else:
            # 回退到父类的简化直线 swipe
            super().swipe_path(points, duration_ms)

    @property
    def supports_touch(self) -> bool:
        """ScrcpyAdapter 支持精细触摸操作。"""
        return self._client is not None and self._client.alive
