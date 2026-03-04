"""
ADB 工具模块：封装所有与 Android 模拟器的底层交互操作。
包含设备发现、分辨率校验、极速截图（内存直读）、点击指令。
"""

import subprocess
import sys
import numpy as np
import cv2
import logging

import config

# 模块级日志器
logger = logging.getLogger(__name__)

# Windows 下隐藏子进程控制台窗口（PyQt6 手册 §十一）
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0


def get_connected_devices():
    """
    通过 `adb devices` 获取当前所有已连接的模拟器设备 ID 列表。

    Returns:
        list[str]: 设备 ID 列表，例如 ['emulator-5554', 'emulator-5556']

    Raises:
        RuntimeError: ADB 命令执行失败时抛出
    """
    try:
        result = subprocess.run(
            [config.ADB_PATH, "devices"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_SUBPROCESS_FLAGS
        )
        devices = []
        for line in result.stdout.strip().splitlines()[1:]:  # 跳过首行标题
            parts = line.strip().split("\t")
            if len(parts) == 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices
    except subprocess.TimeoutExpired:
        logger.error("ADB devices 命令超时")
        raise RuntimeError("ADB 命令超时，请检查 ADB 服务是否正常运行")
    except FileNotFoundError:
        logger.error("找不到 ADB 可执行文件: %s", config.ADB_PATH)
        raise RuntimeError(f"找不到 ADB: {config.ADB_PATH}，请确认已安装并加入 PATH")


def check_resolution(device_id):
    """
    校验指定设备的屏幕分辨率是否符合预期。

    Args:
        device_id (str): 设备 ID

    Raises:
        ValueError: 分辨率不匹配时抛出，提示用户调整
    """
    try:
        result = subprocess.run(
            [config.ADB_PATH, "-s", device_id, "shell", "wm", "size"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_SUBPROCESS_FLAGS
        )
        # 输出格式示例: "Physical size: 1280x720"
        output = result.stdout.strip()
        if "Override size:" in output:
            # 优先使用 Override（用户设置的）分辨率
            size_line = [l for l in output.splitlines() if "Override" in l][-1]
        else:
            size_line = output.splitlines()[-1]

        size_str = size_line.split(":")[-1].strip()
        width, height = map(int, size_str.split("x"))

        if width != config.EXPECTED_WIDTH or height != config.EXPECTED_HEIGHT:
            raise ValueError(
                f"[{device_id}] 分辨率不匹配！"
                f"当前: {width}x{height}, 要求: {config.EXPECTED_WIDTH}x{config.EXPECTED_HEIGHT}。"
                f"请在模拟器设置中调整分辨率。"
            )
        logger.info("[%s] 分辨率校验通过: %dx%d", device_id, width, height)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"[{device_id}] 分辨率检查超时")


def screencap_to_memory(device_id):
    """
    截图方式一：通过 adb shell 管道直接读入内存。
    兼容雷电等模拟器（部分模拟器不支持 exec-out 命令）。

    注意：adb shell 在 Windows 上会将字节流中的 0x0A 替换为 0x0D0A，
    需要手动还原，否则 PNG 解码会失败。

    Args:
        device_id (str): 设备 ID

    Returns:
        numpy.ndarray: BGR 格式的截图图像矩阵；截图失败返回 None
    """
    try:
        result = subprocess.run(
            [config.ADB_PATH, "-s", device_id, "shell", "screencap", "-p"],
            capture_output=True,
            timeout=10,
            creationflags=_SUBPROCESS_FLAGS
        )
        if result.returncode != 0 or not result.stdout:
            logger.warning("[%s] 截图失败, returncode=%d", device_id, result.returncode)
            return None

        # adb shell 在 Windows 上会将 \n (0x0A) 替换为 \r\n (0x0D0A)
        # 必须还原，否则 PNG 数据损坏无法解码
        raw_data = result.stdout.replace(b'\r\n', b'\n')

        # 将原始 PNG 字节流解码为 numpy 数组
        img_array = np.frombuffer(raw_data, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

        if img is None:
            logger.warning("[%s] 截图解码失败，可能模拟器画面异常", device_id)
            return None

        return img
    except subprocess.TimeoutExpired:
        logger.warning("[%s] 截图命令超时", device_id)
        return None


def screencap_fast(device_id):
    """
    截图方式二（高速版）：文件中转，绕过 adb shell 管道的 \\r\\n 损坏问题。
    流程：设备端截图保存为文件 → adb pull 二进制传输 → 本地读取。
    优势：
    - adb pull 是二进制传输，无 \\r\\n 损坏
    - 避免 Python 端全量字节替换（大图时是主要瓶颈）

    Args:
        device_id (str): 设备 ID

    Returns:
        numpy.ndarray: BGR 格式的截图图像矩阵；截图失败返回 None
    """
    import tempfile
    import os

    # 设备端临时文件路径
    remote_path = "/sdcard/_adb_screencap.png"
    # 本地临时文件（用设备ID区分多开）
    local_path = os.path.join(
        tempfile.gettempdir(), f"_screencap_{device_id.replace(':', '_')}.png"
    )

    try:
        # Step 1: 设备端截图保存为 PNG 文件
        r1 = subprocess.run(
            [config.ADB_PATH, "-s", device_id, "shell", "screencap", "-p", remote_path],
            capture_output=True, timeout=5,
            creationflags=_SUBPROCESS_FLAGS
        )
        if r1.returncode != 0:
            logger.warning("[%s] 设备端截图失败", device_id)
            return None

        # Step 2: adb pull 二进制传输到本地（无 \r\n 损坏）
        r2 = subprocess.run(
            [config.ADB_PATH, "-s", device_id, "pull", remote_path, local_path],
            capture_output=True, timeout=5,
            creationflags=_SUBPROCESS_FLAGS
        )
        if r2.returncode != 0:
            logger.warning("[%s] pull 截图文件失败", device_id)
            return None

        # Step 3: 本地读取 PNG（支持中文路径）
        raw = np.fromfile(local_path, dtype=np.uint8)
        img = cv2.imdecode(raw, cv2.IMREAD_COLOR)

        if img is None:
            logger.warning("[%s] 截图解码失败", device_id)
            return None

        return img

    except subprocess.TimeoutExpired:
        logger.warning("[%s] 高速截图超时", device_id)
        return None
    except Exception as e:
        logger.warning("[%s] 高速截图异常: %s", device_id, str(e))
        return None


def tap(device_id, x, y):
    """
    执行极速 ADB 点击操作。

    Args:
        device_id (str): 设备 ID
        x (int): 点击 X 坐标
        y (int): 点击 Y 坐标
    """
    try:
        subprocess.run(
            [config.ADB_PATH, "-s", device_id, "shell", "input", "tap", str(x), str(y)],
            capture_output=True,
            timeout=5,
            creationflags=_SUBPROCESS_FLAGS
        )
        logger.debug("[%s] 点击坐标 (%d, %d)", device_id, x, y)
    except subprocess.TimeoutExpired:
        logger.warning("[%s] 点击命令超时: (%d, %d)", device_id, x, y)
