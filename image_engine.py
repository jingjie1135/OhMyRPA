"""
图像识别引擎：负责模板图片的加载、缓存和高性能模板匹配。
使用 OpenCV matchTemplate + 非极大值抑制(NMS) 实现精准多目标识别。
"""

import os
import cv2
import numpy as np
import logging
import threading

from config import MATCH_THRESHOLD, NMS_IOU_THRESHOLD

# 模块级日志器
logger = logging.getLogger(__name__)

# ===================== 模板缓存 =====================
# 全局缓存字典：{目录路径: [(模板名, 模板图像矩阵), ...]}
# 避免重复从磁盘读取图片，显著降低 IO 开销
_template_cache = {}
_cache_lock = threading.Lock()

def clear_cache(directory=None):
    """清除模板缓存。如果指定了目录，则只清除该目录的缓存；否则清除所有。"""
    with _cache_lock:
        if directory is None:
            _template_cache.clear()
        elif directory in _template_cache:
            del _template_cache[directory]
        logger.info(f"已清理模板缓存: {directory or '全部'}")


def load_templates(directory):
    """
    加载指定目录下所有 .png 模板图片到内存（带缓存）。
    首次调用时从磁盘读取，后续调用直接返回缓存。

    Args:
        directory (str): 模板图片目录路径

    Returns:
        list[tuple[str, numpy.ndarray]]: [(模板名称, BGR图像矩阵), ...]
    """
    # 检查缓存命中
    with _cache_lock:
        if directory in _template_cache:
            return _template_cache[directory]

    templates = []

    if not os.path.isdir(directory):
        logger.warning("模板目录不存在: %s", directory)
        with _cache_lock:
            _template_cache[directory] = templates
        return templates

    for filename in os.listdir(directory):
        if not filename.lower().endswith(".png"):
            continue

        filepath = os.path.join(directory, filename)
        # 使用 numpy.fromfile + cv2.imdecode 读取，兼容中文路径
        # cv2.imread 在 Windows 上不支持中文路径，这是已知问题
        img_array = np.fromfile(filepath, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

        if img is None:
            logger.warning("无法读取模板图片: %s", filepath)
            continue

        # 去掉扩展名作为模板名称
        name = os.path.splitext(filename)[0]
        templates.append((name, img))
        logger.info("已加载模板: %s (%dx%d)", name, img.shape[1], img.shape[0])

    with _cache_lock:
        _template_cache[directory] = templates
    logger.info("目录 [%s] 共加载 %d 个模板", directory, len(templates))
    return templates


def clear_cache(directory=None):
    """
    清除模板缓存。当用户更新了图库文件后，可调用此函数强制重新加载。

    Args:
        directory (str, optional): 指定清除某目录的缓存；为 None 则清除全部
    """
    if directory:
        _template_cache.pop(directory, None)
    else:
        _template_cache.clear()
    logger.info("模板缓存已清除: %s", directory or "全部")


def _nms_boxes(boxes, iou_threshold):
    """
    非极大值抑制 (NMS)：去除高度重叠的检测框，保留置信度最高的结果。

    Args:
        boxes (list[tuple]): [(模板名, cx, cy, w, h, score), ...]
        iou_threshold (float): IoU 重叠阈值

    Returns:
        list[tuple]: 去重后的检测结果 [(模板名, cx, cy, score), ...]
    """
    if not boxes:
        return []

    # 提取坐标信息并转换为 numpy 数组以加速计算
    names = [b[0] for b in boxes]
    cx = np.array([b[1] for b in boxes], dtype=np.float32)
    cy = np.array([b[2] for b in boxes], dtype=np.float32)
    w = np.array([b[3] for b in boxes], dtype=np.float32)
    h = np.array([b[4] for b in boxes], dtype=np.float32)
    scores = np.array([b[5] for b in boxes], dtype=np.float32)

    # 转换为左上角-右下角格式
    x1 = cx - w / 2
    y1 = cy - h / 2
    x2 = cx + w / 2
    y2 = cy + h / 2
    areas = w * h

    # 按置信度降序排列
    order = scores.argsort()[::-1]
    keep = []

    while order.size > 0:
        i = order[0]
        keep.append(i)

        if order.size == 1:
            break

        # 计算当前最优框与其余所有框的 IoU
        rest = order[1:]
        inter_x1 = np.maximum(x1[i], x1[rest])
        inter_y1 = np.maximum(y1[i], y1[rest])
        inter_x2 = np.minimum(x2[i], x2[rest])
        inter_y2 = np.minimum(y2[i], y2[rest])

        inter_w = np.maximum(0, inter_x2 - inter_x1)
        inter_h = np.maximum(0, inter_y2 - inter_y1)
        inter_area = inter_w * inter_h

        iou = inter_area / (areas[i] + areas[rest] - inter_area + 1e-6)

        # 保留 IoU 低于阈值的框（即不重叠的）
        remaining = np.where(iou <= iou_threshold)[0]
        order = rest[remaining]

    # 返回精简结果：(模板名, 中心x, 中心y, 置信度)
    return [(names[i], int(cx[i]), int(cy[i]), float(scores[i])) for i in keep]


def match_all(screen, templates, threshold=None):
    """
    对截图执行多模板匹配，返回所有匹配到的目标位置。

    流程：
    1. 遍历所有模板，使用 cv2.matchTemplate 进行归一化互相关匹配
    2. 筛选超过阈值的匹配点
    3. 执行 NMS 去除重叠检测
    4. 返回去重后的结果列表

    Args:
        screen (numpy.ndarray): BGR 格式的全屏截图
        templates (list[tuple]): load_templates 返回的模板列表
        threshold (float, optional): 自定义阈值，默认使用 config.MATCH_THRESHOLD

    Returns:
        list[tuple[str, int, int, float]]: [(模板名, 中心x, 中心y, 置信度), ...]
        按置信度降序排列
    """
    if threshold is None:
        threshold = MATCH_THRESHOLD

    if screen is None or not templates:
        return []

    all_boxes = []

    for name, tmpl in templates:
        tmpl_h, tmpl_w = tmpl.shape[:2]

        # 确保模板不大于截图
        if tmpl_h > screen.shape[0] or tmpl_w > screen.shape[1]:
            logger.warning("模板 [%s] 尺寸(%dx%d)超过截图，跳过", name, tmpl_w, tmpl_h)
            continue

        # 使用归一化互相关系数进行模板匹配（彩色模式）
        result = cv2.matchTemplate(screen, tmpl, cv2.TM_CCOEFF_NORMED)

        # 找出所有超过阈值的匹配位置
        locations = np.where(result >= threshold)
        
        # 触发灰度+多尺度匹配回退机制的条件：
        # 如果当前精准匹配失败，说明可能跨模拟器实例存在微小的缩放或色彩渲染偏差。
        # 不随意降低阈值，而是尝试微小的多尺度缩放（98%, 99%, 101%, 102%）在灰度空间进行匹配。
        if len(locations[0]) == 0:
            gray_screen = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
            gray_tmpl = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)
            
            # 原始 1.0 比例灰度匹配
            result = cv2.matchTemplate(gray_screen, gray_tmpl, cv2.TM_CCOEFF_NORMED)
            locations = np.where(result >= threshold)
            
            # 如果 1.0 灰度还是不行，开启微尺度轮询
            if len(locations[0]) == 0:
                scales = [0.98, 0.99, 1.01, 1.02]
                for scale in scales:
                    new_w = int(gray_tmpl.shape[1] * scale)
                    new_h = int(gray_tmpl.shape[0] * scale)
                    # 如果缩放后比屏幕还大，跳过
                    if new_w <= 0 or new_h <= 0 or new_w > gray_screen.shape[1] or new_h > gray_screen.shape[0]:
                        continue
                        
                    scaled_tmpl = cv2.resize(gray_tmpl, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
                    res = cv2.matchTemplate(gray_screen, scaled_tmpl, cv2.TM_CCOEFF_NORMED)
                    locs = np.where(res >= threshold)
                    
                    if len(locs[0]) > 0:
                        # 找到了！我们要把匹配框修正回未缩放的原本尺寸（为了外层统一拿 tmpl_w, tmpl_h 读取中心点）
                        # cv2.matchTemplate 返回的是左上角坐标，这里把匹配到的左上角传出去
                        locations = locs
                        tmpl_w, tmpl_h = new_w, new_h  # 更新为实际找到的特征尺寸
                        break

        for pt_y, pt_x in zip(*locations):
            # 计算匹配区域的中心坐标
            cx = pt_x + tmpl_w // 2
            cy = pt_y + tmpl_h // 2
            score = float(result[pt_y, pt_x])
            all_boxes.append((name, cx, cy, tmpl_w, tmpl_h, score))

    # 执行 NMS 去重
    results = _nms_boxes(all_boxes, NMS_IOU_THRESHOLD)

    # 按置信度降序排序
    results.sort(key=lambda r: r[3], reverse=True)

    return results
