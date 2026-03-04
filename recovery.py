"""
异常恢复模块：处理游戏中的弹窗干扰和卡死状态。
采用 Lazy Check 策略——仅在 miss_count 达到阈值时才扫描弹窗，节省 CPU。
"""

import logging

from config import SAFE_CLICK_POS, MISS_COUNT_THRESHOLD
from adb_utils import tap
from image_engine import match_all

# 模块级日志器
logger = logging.getLogger(__name__)


def try_close_popup(device_id, screen, popup_templates, threshold=None):
    """
    扫描并关闭弹窗：在截图中匹配弹窗关闭按钮图库，找到就点击关闭。

    Args:
        device_id (str): 设备 ID
        screen (numpy.ndarray): 当前截图
        popup_templates (list): 弹窗关闭按钮模板列表
        threshold (float, optional): 匹配阈值

    Returns:
        bool: 是否成功找到并点击了关闭按钮
    """
    if not popup_templates:
        logger.debug("[%s] 弹窗图库为空，跳过扫描", device_id)
        return False

    matches = match_all(screen, popup_templates, threshold)

    if matches:
        # 取置信度最高的匹配结果，点击关闭
        name, cx, cy, score = matches[0]
        logger.info("[%s] 检测到弹窗 [%s] (置信度:%.3f)，执行关闭点击 (%d, %d)",
                    device_id, name, score, cx, cy)
        tap(device_id, cx, cy)
        return True

    return False


def blind_click(device_id):
    """
    盲点兜底策略：点击屏幕安全空白区域，尝试关闭任意点击可消失的弹窗。

    Args:
        device_id (str): 设备 ID
    """
    x, y = SAFE_CLICK_POS
    logger.info("[%s] 执行盲点兜底策略，点击安全区域 (%d, %d)", device_id, x, y)
    tap(device_id, x, y)


def handle_exception(device_id, screen, popup_templates, miss_count):
    """
    异常处理状态机：当连续未命中次数达到阈值时触发。

    处理流程：
    1. 判断 miss_count 是否达到阈值
    2. 达到阈值 → 先尝试匹配弹窗关闭按钮
    3. 匹配失败 → 执行盲点兜底策略
    4. 重置 miss_count 并返回

    Args:
        device_id (str): 设备 ID
        screen (numpy.ndarray): 当前截图
        popup_templates (list): 弹窗关闭按钮模板列表
        miss_count (int): 当前连续未命中计数

    Returns:
        int: 更新后的 miss_count（重置为 0 或维持原值）
    """
    if miss_count < MISS_COUNT_THRESHOLD:
        # 尚未达到阈值，不触发异常处理
        return miss_count

    logger.warning("[%s] 连续 %d 次未命中，触发异常恢复机制", device_id, miss_count)

    # 策略一：尝试匹配弹窗关闭按钮
    if try_close_popup(device_id, screen, popup_templates):
        logger.info("[%s] 弹窗已关闭，重置计数器", device_id)
        return 0

    # 策略二：盲点兜底
    blind_click(device_id)
    logger.info("[%s] 盲点策略已执行，重置计数器", device_id)
    return 0
