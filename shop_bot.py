"""
核心业务逻辑：神秘商店自动扫货。
实现单设备的主循环：截图 → 识别 → 偏移点击购买 → 刷新/异常恢复。
支持 GUI 模式（运行时参数、暂停/中断控制、回调通知）。
"""

import time
import logging

from config import (
    TARGETS_DIR, POPUPS_DIR, Y_OFFSET,
    REFRESH_BTN_POS, CLICK_DELAY, REFRESH_WAIT, LOOP_INTERVAL,
    MATCH_THRESHOLD
)
from device_adapter import DeviceAdapter, AdbAdapter
from image_engine import load_templates, match_all
from recovery import handle_exception

# 模块级日志器
logger = logging.getLogger(__name__)


class RuntimeConfig:
    """
    运行时配置：支持 GUI 滑动条实时修改参数。
    GUI 直接修改属性，工作线程每轮循环读取最新值。
    """

    def __init__(self):
        """使用 config.py 中的默认值初始化。"""
        self.y_offset = Y_OFFSET
        self.refresh_btn_x = REFRESH_BTN_POS[0]
        self.refresh_btn_y = REFRESH_BTN_POS[1]
        self.click_delay = CLICK_DELAY
        self.refresh_wait = REFRESH_WAIT
        self.loop_interval = LOOP_INTERVAL
        self.match_threshold = MATCH_THRESHOLD


def run_shop_bot(device_id, runtime_config=None, pause_event=None,
                 interrupt_check=None, callbacks=None, adapter=None):
    """
    单设备神秘商店自动扫货主循环。

    工作流程（无限循环）：
    1. 检查暂停/中断状态
    2. 极速截图 → 内存（通过回调发送到 GUI 预览）
    3. 多模板匹配目标物品（通过回调发送匹配结果到 GUI 标记）
    4. 找到目标 → 逐一执行 Y 轴偏移点击购买
    5. 未找到目标 → 异常恢复 或 刷新商店

    Args:
        device_id (str): 设备 ID
        runtime_config (RuntimeConfig, optional): 运行时可调参数对象
        pause_event (threading.Event, optional): 暂停控制事件
        interrupt_check (callable, optional): 中断检查函数，返回 True 则退出
        callbacks (dict, optional): 回调函数字典
            - 'on_log': fn(str) — 日志消息
            - 'on_screenshot': fn(numpy.ndarray) — 截图数据
            - 'on_match': fn(list) — 匹配结果列表
            - 'on_buy_count': fn(int) — 购买计数
    """
    # 使用默认配置（兼容无 GUI 的命令行模式）
    if runtime_config is None:
        runtime_config = RuntimeConfig()

    # DeviceAdapter（DRY：统一设备交互入口）
    _adapter = adapter or AdbAdapter(device_id)

    def log(msg):
        """统一日志输出：同时写入 logger 和 GUI 回调。"""
        logger.info("[%s] %s", device_id, msg)
        if callbacks and 'on_log' in callbacks:
            callbacks['on_log'](f"[{device_id}] {msg}")

    def should_stop():
        """检查是否应该停止运行。"""
        if interrupt_check and interrupt_check():
            return True
        return False

    def wait_if_paused():
        """如果处于暂停状态则阻塞等待，同时检查中断。"""
        if pause_event is not None:
            while not pause_event.is_set():
                if should_stop():
                    return False
                time.sleep(0.1)
        return True

    log("===== 神秘商店自动扫货启动 =====")

    # 预加载模板图库到内存（仅首次读取磁盘）
    target_templates = load_templates(TARGETS_DIR)
    popup_templates = load_templates(POPUPS_DIR)

    if not target_templates:
        log("目标物品图库为空！请在 targets/ 目录放入物品截图")
        return

    log(f"已加载 {len(target_templates)} 个目标模板, {len(popup_templates)} 个弹窗模板")

    # 连续未命中计数器
    miss_count = 0
    # 购买计数器
    buy_count = 0

    while True:
        try:
            # ========== 暂停/中断检查 ==========
            if not wait_if_paused():
                log("收到停止信号，退出主循环")
                break
            if should_stop():
                log("收到停止信号，退出主循环")
                break

            # ========== 第一步：极速截图 ==========
            screen = _adapter.get_frame()
            if screen is None:
                log("截图失败，等待重试...")
                time.sleep(1)
                continue

            # 通知 GUI 更新截图预览
            if callbacks and 'on_screenshot' in callbacks:
                callbacks['on_screenshot'](screen)

            # ========== 第二步：模板匹配目标物品 ==========
            cfg = runtime_config  # 读取当前参数快照
            matches = match_all(screen, target_templates, cfg.match_threshold)

            # 通知 GUI 绘制匹配标记
            if callbacks and 'on_match' in callbacks:
                callbacks['on_match'](matches)

            if matches:
                # ========== 第三步：找到目标，执行偏移点击购买 ==========
                log(f"本轮发现 {len(matches)} 个目标物品")

                for name, cx, cy, score in matches:
                    if should_stop():
                        break

                    # 计算购买按钮坐标：物品中心 Y 坐标 + 偏移量
                    buy_x = cx
                    buy_y = cy + cfg.y_offset

                    log(f"发现目标 [{name}] (置信度:{score:.3f})，"
                        f"物品位置({cx},{cy}) → 偏移点击购买按钮({buy_x},{buy_y})")
                    _adapter.tap(buy_x, buy_y)

                    buy_count += 1
                    if callbacks and 'on_buy_count' in callbacks:
                        callbacks['on_buy_count'](buy_count)

                    # 点击后等待
                    time.sleep(cfg.click_delay)

                # 成功购买，重置未命中计数
                miss_count = 0

            else:
                # ========== 第四步：未找到目标 ==========
                miss_count += 1

                # 检查是否需要触发异常恢复
                miss_count = handle_exception(
                    device_id, screen, popup_templates, miss_count
                )

                if miss_count == 0:
                    # 异常恢复已执行，直接进入下一轮
                    continue

                # 未达阈值，执行刷新操作
                rx = cfg.refresh_btn_x
                ry = cfg.refresh_btn_y
                log(f"点击刷新按钮 ({rx}, {ry})")
                _adapter.tap(rx, ry)
                time.sleep(cfg.refresh_wait)

            # 主循环间隔，防止 CPU 空转
            time.sleep(cfg.loop_interval)

        except Exception as e:
            # 全局异常兜底：防止线程因未知异常崩溃退出
            log(f"主循环异常: {str(e)}")
            logger.error("[%s] 主循环异常", device_id, exc_info=True)
            time.sleep(1)

    log("===== 神秘商店自动扫货已停止 =====")
