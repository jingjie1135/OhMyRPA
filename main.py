"""
程序入口：多开并发控制引擎。
负责设备发现、分辨率校验、线程池分配和日志初始化。
"""

import sys
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import MAX_WORKERS, ERROR_SLEEP
from adb_utils import get_connected_devices, get_resolution
from shop_bot import run_shop_bot


def setup_logging():
    """
    初始化日志系统：同时输出到终端和日志文件。
    格式包含时间戳和设备标识，方便多开调试。
    """
    log_format = "[%(asctime)s] %(levelname)-7s %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # 根日志器配置
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # 终端输出处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format, date_format))
    root_logger.addHandler(console_handler)

    # 文件输出处理器（追加模式，保留历史日志）
    file_handler = logging.FileHandler("bot.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format, date_format))
    root_logger.addHandler(file_handler)


def run_device_worker(device_id):
    """
    单设备工作线程入口：带全局异常捕获和自动重连。

    异常策略：
    - 捕获所有异常，避免线程因错误退出
    - 异常后休眠固定时间再重试
    - 持续运行直至主进程终止

    Args:
        device_id (str): 设备 ID
    """
    logger = logging.getLogger(__name__)

    while True:
        try:
            logger.info("[%s] 工作线程启动", device_id)
            run_shop_bot(device_id)
        except KeyboardInterrupt:
            logger.info("[%s] 收到中断信号，线程退出", device_id)
            break
        except Exception as e:
            logger.error(
                "[%s] 线程发生严重异常: %s，%d 秒后重试...",
                device_id, str(e), ERROR_SLEEP,
                exc_info=True
            )
            time.sleep(ERROR_SLEEP)


def main():
    """
    主函数：发现设备 → 检测分辨率 → 启动线程池。
    """
    # 初始化日志系统
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("安卓游戏多开自动化脚本系统 v0.1 启动")
    logger.info("=" * 60)

    # ========== 第一步：发现所有已连接设备 ==========
    logger.info("正在扫描已连接的模拟器设备...")
    devices = get_connected_devices()

    if not devices:
        logger.error("未发现任何已连接的模拟器设备！")
        logger.error("请检查：")
        logger.error("  1. 模拟器是否已启动")
        logger.error("  2. 是否已开启 USB 调试 / ADB 调试")
        logger.error("  3. ADB 是否已正确安装并加入 PATH")
        sys.exit(1)

    logger.info("发现 %d 个设备: %s", len(devices), ", ".join(devices))

    # ========== 第二步：检测各设备分辨率（仅记录，不阻止） ==========
    from config import set_device_resolution
    for device_id in devices:
        w, h = get_resolution(device_id)
        if w > 0 and h > 0:
            set_device_resolution(w, h)
            logger.info("[%s] 设备分辨率: %dx%d", device_id, w, h)
        else:
            logger.warning("[%s] 无法获取分辨率", device_id)

    logger.info("共 %d 个设备准备就绪", len(devices))

    # ========== 第三步：启动线程池，每个设备独立运行 ==========
    worker_count = min(MAX_WORKERS, len(devices))
    logger.info("正在启动线程池 (工作线程数: %d)...", worker_count)

    try:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            # 为每个设备提交独立的工作线程
            futures = {
                executor.submit(run_device_worker, dev): dev
                for dev in devices
            }

            logger.info("所有设备线程已启动，脚本运行中... (Ctrl+C 停止)")

            # 等待线程完成（正常情况下不会完成，除非外部中断）
            for future in as_completed(futures):
                device_id = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logger.error("[%s] 线程异常退出: %s", device_id, str(e))

    except KeyboardInterrupt:
        logger.info("\n收到 Ctrl+C 中断信号，正在停止所有线程...")
        logger.info("程序已安全退出")


if __name__ == "__main__":
    main()
