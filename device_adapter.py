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
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        """直线滑动操作。"""
        ...
        
    def swipe_path(self, path: list) -> None:
        """根据完整的轨迹点回放多段滑动。path 格式: [(x, y, timestamp_ms), ...]"""
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

    def back(self) -> None:
        """触发返回操作。"""
        ...

    def home(self) -> None:
        """触发主页操作。"""
        ...

    def app_switch(self) -> None:
        """触发多任务切换操作。"""
        ...

    def set_display_power(self, on: bool) -> None:
        """设置屏幕电源状态 (熄屏/亮屏)。"""
        ...

    def back_or_screen_on(self) -> None:
        """唤醒屏幕（如果亮屏则等同于按下 Back）。"""
        ...

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

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        from adb_utils import swipe
        swipe(self._device_id, x1, y1, x2, y2, duration_ms)
        
    def swipe_path(self, path: list) -> None:
        """ADB无法执行平滑的多点触摸，回退为取首尾点直线滑动"""
        if len(path) >= 2:
            x1, y1 = path[0][:2]
            x2, y2 = path[-1][:2]
            dur = max(100, path[-1][2] - path[0][2])
            from adb_utils import swipe
            swipe(self._device_id, x1, y1, x2, y2, dur)

    def back(self) -> None:
        from adb_utils import keyevent
        keyevent(self._device_id, 4)

    def home(self) -> None:
        from adb_utils import keyevent
        keyevent(self._device_id, 3)

    def app_switch(self) -> None:
        from adb_utils import keyevent
        keyevent(self._device_id, 187)

    def set_display_power(self, on: bool) -> None:
        """ADB无法直接精准设置屏幕电源，只能发送 power 按键翻转状态"""
        from adb_utils import keyevent
        keyevent(self._device_id, 26) # KEYCODE_POWER

    def back_or_screen_on(self) -> None:
        from adb_utils import keyevent
        keyevent(self._device_id, 224) # KEYCODE_WAKEUP

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

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        if self._client and self._client.alive:
            self._client.control.swipe(x1, y1, x2, y2, duration_ms)
            
    def swipe_path(self, path: list) -> None:
        """使用 Scrcpy 控制通道执行零延迟的高精度轨迹重放"""
        if not path or not self._client or not self._client.alive:
            return
        
        import time
        x0, y0, t0 = path[0]
        self._client.control.touch_down(x0, y0)
        
        last_t = t0
        for i in range(1, len(path)):
            x, y, t = path[i]
            delay = (t - last_t) / 1000.0
            if delay > 0:
                time.sleep(delay)
            self._client.control.touch_move(x, y)
            last_t = t
            
        self._client.control.touch_up(path[-1][0], path[-1][1])

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

    def back(self) -> None:
        if self._client and self._client.alive:
            self._client.control.back()

    def home(self) -> None:
        if self._client and self._client.alive:
            self._client.control.home()

    def app_switch(self) -> None:
        if self._client and self._client.alive:
            self._client.control.app_switch()

    def set_display_power(self, on: bool) -> None:
        if self._client and self._client.alive:
            self._client.control.set_display_power(on)

    def back_or_screen_on(self) -> None:
        if self._client and self._client.alive:
            # AndroidKeyeventAction.AKEY_EVENT_ACTION_DOWN (0) -> UP (1)
            self._client.control.back_or_screen_on(0)
            self._client.control.back_or_screen_on(1)

    @property
    def supports_touch(self) -> bool:
        """ScrcpyAdapter 支持精细触摸操作。"""
        return self._client is not None and self._client.alive


# ==================== HybridDeviceAdapter ====================

class HybridDeviceAdapter(DeviceAdapter):
    """
    基于 RPA Matrix 架构的混合驱动适配器 (Sensor-Actuator Separation)。
    
    特点：
    - 视觉感知 (Sensor): 强制使用 ADB 获取绝对无损的实时画面 (`get_frame` / `get_resolution`)。
    - 物理操作 (Actuator): 自动将所有操作 (`click`, `swipe_path` 等) 路由至由于 Scrcpy 控制通道，
                      实现极低延迟和防封笔迹。如果 Scrcpy 不可用，自动平滑退化回 ADB 盲打。
    """
    
    def __init__(self, device_id: str, scrcpy_client=None):
        self._device_id = device_id
        # 视觉/后备控制单元
        self._adb_adapter = AdbAdapter(device_id)
        # 高速执行单元 (即便 client 为 None，我们也将其视作占位符)
        self._scrcpy_adapter = ScrcpyAdapter(device_id, scrcpy_client)

    @property
    def device_id(self) -> str:
        return self._device_id

    # ---------- 视觉感知层 (路由至 ADB) ----------
    
    def get_resolution(self) -> tuple[int, int]:
        return self._adb_adapter.get_resolution()

    def get_frame(self):
        """核心：强制走 ADB 极速无损拉取，保证 100% 找图命中率。"""
        return self._adb_adapter.get_frame()

    # ---------- 物理操作层 (优先路由至 Scrcpy 控制通道) ----------

    @property
    def _actuator(self) -> DeviceAdapter:
        """选择最佳执行器"""
        if self._scrcpy_adapter.supports_touch:
            return self._scrcpy_adapter
        return self._adb_adapter

    def tap(self, x: int, y: int) -> None:
        self._actuator.tap(x, y)

    def click(self, x: int, y: int) -> None:
        self._actuator.click(x, y)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 500) -> None:
        self._actuator.swipe(x1, y1, x2, y2, duration_ms)

    def swipe_path(self, path: list[tuple[int, int]], duration_ms: int = 500) -> None:
        self._actuator.swipe_path(path, duration_ms)

    def touch_down(self, x: int, y: int, touch_id: int = -1) -> None:
        self._actuator.touch_down(x, y, touch_id)

    def touch_move(self, x: int, y: int, touch_id: int = -1) -> None:
        self._actuator.touch_move(x, y, touch_id)

    def touch_up(self, x: int, y: int, touch_id: int = -1) -> None:
        self._actuator.touch_up(x, y, touch_id)

    def back(self) -> None:
        self._actuator.back()

    def home(self) -> None:
        self._actuator.home()

    def app_switch(self) -> None:
        self._actuator.app_switch()

    def set_display_power(self, on: bool) -> None:
        self._actuator.set_display_power(on)

    def back_or_screen_on(self) -> None:
        self._actuator.back_or_screen_on()

    @property
    def supports_touch(self) -> bool:
        return self._actuator.supports_touch
