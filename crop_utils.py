"""
候选裁切预览图生成工具。
用于流水线 → 循环转换时，以点击坐标为中心生成候选模板图。
"""

import os
import cv2
import numpy as np


def generate_candidate_crop(screenshot, click_x: int, click_y: int,
                            size: int = 80) -> np.ndarray:
    """
    以点击坐标为中心，从截图中裁切正方形候选区域。

    Args:
        screenshot: BGR 格式的 numpy 数组截图，或截图文件路径
        click_x: 点击坐标 X
        click_y: 点击坐标 Y
        size: 裁切正方形边长（像素），默认 80

    Returns:
        numpy.ndarray: 裁切后的 BGR 图像；若坐标超出范围则填充黑色
    """
    # 支持文件路径输入
    if isinstance(screenshot, str):
        if not os.path.exists(screenshot):
            return None
        img_array = np.fromfile(screenshot, dtype=np.uint8)
        screenshot = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if screenshot is None:
            return None

    h, w = screenshot.shape[:2]
    half = size // 2

    # 计算裁切边界（允许超出屏幕范围，用黑色填充）
    x1 = click_x - half
    y1 = click_y - half
    x2 = x1 + size
    y2 = y1 + size

    # 裁切区域的有效范围（夹紧到图像边界）
    src_x1 = max(0, x1)
    src_y1 = max(0, y1)
    src_x2 = min(w, x2)
    src_y2 = min(h, y2)

    # 创建黑色画布，将有效区域复制到对应位置
    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    dst_x1 = src_x1 - x1
    dst_y1 = src_y1 - y1
    dst_x2 = dst_x1 + (src_x2 - src_x1)
    dst_y2 = dst_y1 + (src_y2 - src_y1)

    if src_x2 > src_x1 and src_y2 > src_y1:
        canvas[dst_y1:dst_y2, dst_x1:dst_x2] = screenshot[src_y1:src_y2, src_x1:src_x2]

    return canvas


def generate_candidate_crops_for_actions(screenshot, actions: list,
                                         size: int = 80) -> list:
    """
    为动作列表中的每个 tap 动作生成候选裁切预览图。

    Args:
        screenshot: BGR 格式的 numpy 数组截图
        actions: ActionNode 列表
        size: 裁切正方形边长

    Returns:
        list[dict]: [{
            'action_index': int,
            'action': ActionNode,
            'crop': numpy.ndarray,  # 裁切后的图像
            'click_x': int,
            'click_y': int,
        }, ...]
        仅包含 tap 类型且有有效坐标的动作
    """
    results = []
    for i, action in enumerate(actions):
        if action.type == "tap":
            x = action.params.get('x', 0)
            y = action.params.get('y', 0)
            if x > 0 or y > 0:
                crop = generate_candidate_crop(screenshot, x, y, size)
                if crop is not None:
                    results.append({
                        'action_index': i,
                        'action': action,
                        'crop': crop,
                        'click_x': x,
                        'click_y': y,
                    })
    return results


def save_crop_as_template(crop: np.ndarray, save_dir: str,
                          name: str, resolution_tag: str = "") -> str:
    """
    将裁切图保存为 PNG 模板文件。

    Args:
        crop: BGR 格式的 numpy 数组
        save_dir: 保存目录
        name: 模板名称（不含扩展名）
        resolution_tag: 分辨率标签（如 "540x960"），为空则不添加

    Returns:
        str: 保存后的文件名
    """
    os.makedirs(save_dir, exist_ok=True)

    if resolution_tag:
        filename = f"{name}@{resolution_tag}.png"
    else:
        filename = f"{name}.png"

    filepath = os.path.join(save_dir, filename)

    # 使用 imencode 避免中文路径问题
    success, buf = cv2.imencode('.png', crop)
    if success:
        buf.tofile(filepath)

    return filename
