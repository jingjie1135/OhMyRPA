"""
配置文件：集中管理所有可调参数，与业务逻辑分离。
用户可直接修改此文件中的常量来适配不同游戏/模拟器环境。
"""

import os
import sys

# ===================== 路径配置 =====================
# 打包后（Nuitka --onefile）：__file__ 指向临时解压目录，需使用 exe 所在目录
# 开发环境：直接使用脚本所在目录
if getattr(sys, 'frozen', False) or '__compiled__' in dir():
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 目标物品图库目录
TARGETS_DIR = os.path.join(BASE_DIR, "targets")

# 弹窗关闭按钮图库目录
POPUPS_DIR = os.path.join(BASE_DIR, "popups")

# ===================== 分辨率配置 =====================
# 运行时检测到的设备分辨率（连接设备后自动设置）
DEVICE_WIDTH = 0
DEVICE_HEIGHT = 0


def set_device_resolution(w, h):
    """运行时更新设备分辨率（GUI 选择设备后调用）。"""
    global DEVICE_WIDTH, DEVICE_HEIGHT
    DEVICE_WIDTH = w
    DEVICE_HEIGHT = h


def get_resolution_tag():
    """获取分辨率标签字符串，用于文件名。如 '1280x720'。"""
    if DEVICE_WIDTH > 0 and DEVICE_HEIGHT > 0:
        return f"{DEVICE_WIDTH}x{DEVICE_HEIGHT}"
    return "unknown"

# ===================== 图像识别配置 =====================
# 模板匹配相似度阈值（0.0 ~ 1.0），越高越严格
MATCH_THRESHOLD = 0.8

# 非极大值抑制（NMS）的 IoU 阈值，用于去除重叠检测
NMS_IOU_THRESHOLD = 0.3

# ===================== 点击坐标配置 =====================
# 物品图标中心 → 购买按钮的 Y 轴向下偏移量（像素）
Y_OFFSET = 130

# "20元宝刷新"按钮的固定坐标 (x, y)
REFRESH_BTN_POS = (640, 400)

# 盲点兜底：安全空白区域点击坐标
SAFE_CLICK_POS = (10, 10)

# ===================== 异常恢复配置 =====================
# 连续未命中次数阈值，达到后触发异常恢复
MISS_COUNT_THRESHOLD = 3

# 异常后线程休眠秒数
ERROR_SLEEP = 10

# ===================== 时间延迟配置 =====================
# 每次点击后的极短等待（秒），追求极速但给予系统最小响应时间
CLICK_DELAY = 0.05

# 刷新商店后等待画面加载（秒）
REFRESH_WAIT = 0.5

# 主循环每轮间隔（秒），避免 CPU 空转
LOOP_INTERVAL = 0.1

# ===================== 多开并发配置 =====================
# 线程池最大工作线程数
MAX_WORKERS = 4

# ===================== ADB 配置 =====================

import glob
import shutil


def scan_adb_paths():
    """
    自动扫描常见模拟器和系统的 ADB 路径。
    返回 dict: { "显示名称": "adb.exe 完整路径" }
    扫描范围：雷电、MUMU、夜神、系统 PATH
    """
    found = {}

    # --- 雷电模拟器 (LDPlayer) ---
    # 常见安装路径模式
    ld_patterns = [
        r"G:\leidian\LDPlayer*\adb.exe",
        r"C:\leidian\LDPlayer*\adb.exe",
        r"D:\leidian\LDPlayer*\adb.exe",
        r"E:\leidian\LDPlayer*\adb.exe",
        os.path.expandvars(r"%ProgramFiles%\LDPlayer*\adb.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\LDPlayer*\adb.exe"),
    ]
    for pattern in ld_patterns:
        for path in glob.glob(pattern):
            if os.path.isfile(path):
                found["雷电"] = path

    # --- MUMU 模拟器 ---
    # MUMU 的 ADB 位于 NetEase\MuMu\nx_main 目录下
    mumu_patterns = [
        # 各盘符根目录
        r"C:\NetEase\MuMu*\nx_main\adb.exe",
        r"D:\NetEase\MuMu*\nx_main\adb.exe",
        r"E:\NetEase\MuMu*\nx_main\adb.exe",
        r"G:\NetEase\MuMu*\nx_main\adb.exe",
        # Program Files
        os.path.expandvars(r"%ProgramFiles%\NetEase\MuMu*\nx_main\adb.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\NetEase\MuMu*\nx_main\adb.exe"),
        # 旧版 MUMU（shell 目录）
        os.path.expandvars(r"%ProgramFiles%\MuMu*\shell\adb.exe"),
        r"C:\Program Files\MuMu*\shell\adb.exe",
        r"D:\Program Files\MuMu*\shell\adb.exe",
        # MUMU 12 用户数据目录
        os.path.expandvars(r"%LocalAppData%\Netease\MuMuPlayer*\shell\adb.exe"),
    ]
    for pattern in mumu_patterns:
        for path in glob.glob(pattern):
            if os.path.isfile(path):
                found["MUMU"] = path

    # --- 夜神模拟器 (Nox) ---
    nox_patterns = [
        os.path.expandvars(r"%ProgramFiles%\Nox\bin\nox_adb.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Nox\bin\nox_adb.exe"),
        r"D:\Program Files\Nox\bin\nox_adb.exe",
    ]
    for pattern in nox_patterns:
        for path in glob.glob(pattern):
            if os.path.isfile(path):
                found["夜神 (Nox)"] = path

    # --- 系统 ADB（通过 PATH 查找） ---
    system_adb = shutil.which("adb")
    if system_adb:
        found["系统 ADB"] = os.path.abspath(system_adb)

    return found


# 自动扫描结果缓存
_scanned_adb = scan_adb_paths()

# 当前使用的 ADB 路径（默认取第一个找到的，找不到则 fallback 到 "adb"）
ADB_PATH = next(iter(_scanned_adb.values()), "adb")


def set_adb_path(path):
    """运行时切换 ADB 路径（GUI 调用）。"""
    global ADB_PATH
    ADB_PATH = path


# ===================== GUI 配置 =====================
# 截图预览区最大宽度（像素）
PREVIEW_MAX_WIDTH = 400
