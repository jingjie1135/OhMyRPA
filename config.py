"""
配置文件：集中管理所有可调参数，与业务逻辑分离。
用户可直接修改此文件中的常量来适配不同应用/模拟器环境。
"""

import os
import sys
import glob
import logging
import string
import threading

# ===================== 路径配置 =====================
# 打包后（Nuitka --onefile）：__file__ 指向临时解压目录，需使用 exe 所在目录
# 开发环境：直接使用脚本所在目录
if getattr(sys, 'frozen', False) or '__compiled__' in dir():
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 目标模板图库目录
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
# 模板命中中心 → 后续点击点的默认 Y 轴偏移量（像素）
Y_OFFSET = 130

# 默认刷新/重试按钮的固定坐标 (x, y)
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

# 刷新/重试后等待画面加载（秒）
REFRESH_WAIT = 0.5

# 主循环每轮间隔（秒），避免 CPU 空转
LOOP_INTERVAL = 0.1

# ===================== 多开并发配置 =====================
# 线程池最大工作线程数
MAX_WORKERS = 4

# ===================== ADB 配置 =====================

_adb_logger = logging.getLogger(__name__)


def _get_available_drives():
    """
    动态获取系统所有可用盘符列表（如 ['C:\\', 'D:\\', 'G:\\']）。
    避免硬编码盘符，兼容任意磁盘配置。
    """
    drives = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            drives.append(drive)
    return drives


def _search_registry_install_paths():
    """
    从 Windows 注册表查找模拟器安装路径。
    策略：遍历 Uninstall 下所有子项，模糊匹配关键词（兼容任意版本号和名称变体）。
    返回 dict: { "显示名称": "安装目录" }
    """
    results = {}
    try:
        import winreg
    except ImportError:
        return results

    # 模糊匹配规则：(关键词列表, 显示名称) — 子项名称或 DisplayName 包含任一关键词即命中
    match_rules = [
        (["ldplayer", "leidian"], "雷电"),
        (["mumu", "nemu"], "MUMU"),
    ]

    # 需要搜索的注册表根路径
    uninstall_roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    for hkey, uninstall_path in uninstall_roots:
        try:
            with winreg.OpenKey(hkey, uninstall_path) as parent_key:
                i = 0
                while True:
                    try:
                        sub_key_name = winreg.EnumKey(parent_key, i)
                        i += 1
                    except OSError:
                        break

                    sub_key_lower = sub_key_name.lower()

                    for keywords, display_name in match_rules:
                        if display_name in results:
                            continue

                        # 检查子项名称是否包含关键词
                        matched = any(kw in sub_key_lower for kw in keywords)

                        if not matched:
                            # 再检查 DisplayName 值
                            try:
                                with winreg.OpenKey(parent_key, sub_key_name) as sub_key:
                                    disp_name, _ = winreg.QueryValueEx(sub_key, "DisplayName")
                                    if disp_name and any(kw in disp_name.lower() for kw in keywords):
                                        matched = True
                            except (FileNotFoundError, OSError):
                                pass

                        if matched:
                            try:
                                with winreg.OpenKey(parent_key, sub_key_name) as sub_key:
                                    install_dir, _ = winreg.QueryValueEx(sub_key, "InstallLocation")
                                    if install_dir and os.path.isdir(install_dir):
                                        results[display_name] = install_dir.rstrip("\\")
                                        _adb_logger.info(
                                            "注册表匹配 [%s] → %s 安装目录: %s",
                                            sub_key_name, display_name, install_dir
                                        )
                            except (FileNotFoundError, OSError):
                                # 没有 InstallLocation，尝试从 UninstallString 反推
                                try:
                                    with winreg.OpenKey(parent_key, sub_key_name) as sub_key:
                                        uninst, _ = winreg.QueryValueEx(sub_key, "UninstallString")
                                        if uninst:
                                            uninst_dir = os.path.dirname(uninst.strip('"'))
                                            if os.path.isdir(uninst_dir):
                                                results[display_name] = uninst_dir.rstrip("\\")
                                                _adb_logger.info(
                                                    "注册表从 UninstallString 反推 %s 目录: %s",
                                                    display_name, uninst_dir
                                                )
                                except (FileNotFoundError, OSError):
                                    pass

        except (FileNotFoundError, OSError):
            continue

    return results


def _find_adb_near_exe(exe_path):
    """
    从一个可执行文件路径出发，在其所在目录及上级目录中查找 adb.exe。
    同时检查 shell/ 和 vmonitor/bin/ 等子目录。最多向上查找 3 层。
    返回 adb.exe 路径或 None。
    """
    if not exe_path or not os.path.isfile(exe_path):
        return None

    search_dir = os.path.dirname(exe_path)
    # 需要检查的子目录列表
    _sub_dirs = ["", "shell", "nx_main", "vmonitor\\bin", "emulator\\nemu", "bin"]
    for _ in range(4):  # 当前目录 + 向上 3 层
        for sub in _sub_dirs:
            adb_path = os.path.join(search_dir, sub, "adb.exe") if sub else os.path.join(search_dir, "adb.exe")
            if os.path.isfile(adb_path):
                return adb_path
        parent = os.path.dirname(search_dir)
        if parent == search_dir:
            break
        search_dir = parent
    return None


def _search_running_processes():
    """
    扫描当前运行中的模拟器进程，从进程路径反推 ADB 位置。
    返回 dict: { "显示名称": "adb.exe 完整路径" }
    无需第三方库，使用 WMIC 命令查询。
    """
    import subprocess as _sp
    results = {}

    # 进程名 → 显示名称（ADB 位置通过 _find_adb_near_exe 智能查找）
    process_map = {
        # 雷电模拟器
        "dnplayer.exe":        "雷电",
        "ldplayer.exe":        "雷电",
        "ldconsole.exe":       "雷电",
        "ldboxheadless.exe":   "雷电",
        # MUMU 模拟器（覆盖所有已知进程名）
        "mumuplayer.exe":      "MUMU",
        "mumuglobal.exe":      "MUMU",
        "mumumanager.exe":     "MUMU",
        "nemuheadless.exe":    "MUMU",
        "nemuplayer.exe":      "MUMU",
        "mumuvmmsvc.exe":      "MUMU",
        "mumuvmmheadless.exe": "MUMU",
        "mumuhypervcenter.exe":"MUMU",
    }

    try:
        _flags = _sp.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        result = _sp.run(
            ["wmic", "process", "get", "ExecutablePath"],
            capture_output=True, text=True, timeout=5,
            creationflags=_flags
        )
        if result.returncode != 0:
            return results

        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            exe_name = os.path.basename(line).lower()
            if exe_name in process_map:
                display_name = process_map[exe_name]
                if display_name in results:
                    continue
                # 智能查找 adb.exe（当前目录 + 上级目录 + 子目录）
                adb_path = _find_adb_near_exe(line)
                if adb_path:
                    results[display_name] = adb_path
                    _adb_logger.info("从运行进程发现 %s ADB: %s", display_name, adb_path)
    except Exception as e:
        _adb_logger.debug("进程扫描失败: %s", e)

    return results


def scan_adb_paths():
    """
    自动扫描雷电 / MUMU 模拟器的 ADB 路径（不使用系统 ADB）。
    扫描策略（按优先级）：
      1. Windows 注册表 — 最精准，直接读取安装目录
      2. 运行进程反推 — 如果模拟器正在运行，从进程路径定位
      3. 全盘符路径猜测 — 遍历所有盘符 + 常见安装路径模式
    返回 dict: { "显示名称": "adb.exe 完整路径" }
    """
    found = {}

    # ===== 策略一：注册表查找 =====
    registry_dirs = _search_registry_install_paths()
    for name, install_dir in registry_dirs.items():
        if name not in found:
            # 统一使用智能查找，兼容各种子目录结构
            # 手动搜索：直接在安装目录及子目录找 adb.exe
            for sub in ["", "shell", "nx_main", "vmonitor\\bin", "emulator\\nemu", "bin"]:
                adb = os.path.join(install_dir, sub, "adb.exe") if sub else os.path.join(install_dir, "adb.exe")
                if os.path.isfile(adb):
                    found[name] = adb
                    _adb_logger.info("注册表发现 %s ADB: %s", name, adb)
                    break

    # ===== 策略二：运行进程反推 =====
    if "雷电" not in found or "MUMU" not in found:
        process_results = _search_running_processes()
        for name, path in process_results.items():
            if name not in found:
                found[name] = path

    # ===== 策略三：全盘符路径模式扫描 =====
    drives = _get_available_drives()

    # --- 雷电模拟器 (LDPlayer) ---
    if "雷电" not in found:
        ld_sub_patterns = [
            r"leidian\LDPlayer*\adb.exe",
            r"Program Files\LDPlayer*\adb.exe",
            r"Program Files (x86)\LDPlayer*\adb.exe",
            r"LDPlayer*\adb.exe",
            r"ChangZhi\LDPlayer*\adb.exe",
        ]
        for drive in drives:
            for sub in ld_sub_patterns:
                pattern = os.path.join(drive, sub)
                for path in glob.glob(pattern):
                    if os.path.isfile(path):
                        found["雷电"] = path
                        _adb_logger.info("路径扫描发现雷电 ADB: %s", path)
                        break
                if "雷电" in found:
                    break
            if "雷电" in found:
                break

    # --- MUMU 模拟器 ---
    if "MUMU" not in found:
        mumu_sub_patterns = [
            # MUMU 12 — 注意大小写变体：NetEase / Netease / netease
            r"NetEase\MuMu*\adb.exe",
            r"Netease\MuMu*\adb.exe",
            r"NetEase\MuMu*\shell\adb.exe",
            r"Netease\MuMu*\shell\adb.exe",
            # nx_main 子目录（MUMU 12 常见结构）
            r"NetEase\MuMu*\nx_main\adb.exe",
            r"Netease\MuMu*\nx_main\adb.exe",
            r"NetEase\MuMu*\vmonitor\bin\adb.exe",
            r"Netease\MuMu*\vmonitor\bin\adb.exe",
            # Nemu 系列（MUMU 旧版内部名称）
            r"NetEase\Nemu*\adb.exe",
            r"Netease\Nemu*\adb.exe",
            r"Nemu*\adb.exe",
            # Program Files 安装
            r"Program Files\NetEase\MuMu*\adb.exe",
            r"Program Files (x86)\NetEase\MuMu*\adb.exe",
            r"Program Files\NetEase\MuMu*\nx_main\adb.exe",
            r"Program Files (x86)\NetEase\MuMu*\nx_main\adb.exe",
            r"Program Files\Netease\MuMu*\nx_main\adb.exe",
            r"Program Files (x86)\Netease\MuMu*\nx_main\adb.exe",
            r"Program Files\Netease\MuMu*\adb.exe",
            r"Program Files (x86)\Netease\MuMu*\adb.exe",
            r"Program Files\NetEase\MuMu*\shell\adb.exe",
            r"Program Files (x86)\NetEase\MuMu*\shell\adb.exe",
            r"Program Files\Netease\MuMu*\shell\adb.exe",
            r"Program Files (x86)\Netease\MuMu*\shell\adb.exe",
            r"Program Files\MuMu*\shell\adb.exe",
            r"Program Files (x86)\MuMu*\shell\adb.exe",
            # 直接在盘符根目录
            r"MuMu*\adb.exe",
            r"MuMu*\shell\adb.exe",
            r"MuMuPlayer*\shell\adb.exe",
            r"MuMuPlayer*\adb.exe",
        ]
        # 额外搜索 %LocalAppData% 和 %AppData%
        special_dirs = [
            os.path.expandvars(r"%LocalAppData%"),
            os.path.expandvars(r"%AppData%"),
            os.path.expandvars(r"%ProgramData%"),
        ]
        for base_dir in special_dirs:
            if not os.path.isdir(base_dir):
                continue
            for local_sub in [r"Netease\MuMu*\shell\adb.exe",
                              r"Netease\MuMu*\adb.exe",
                              r"NetEase\MuMu*\shell\adb.exe",
                              r"NetEase\MuMu*\adb.exe",
                              r"MuMuPlayer*\shell\adb.exe",
                              r"MuMuPlayer*\adb.exe"]:
                pattern = os.path.join(base_dir, local_sub)
                for path in glob.glob(pattern):
                    if os.path.isfile(path):
                        found["MUMU"] = path
                        _adb_logger.info("特殊目录发现 MUMU ADB: %s", path)
                        break
                if "MUMU" in found:
                    break
            if "MUMU" in found:
                break

        if "MUMU" not in found:
            for drive in drives:
                for sub in mumu_sub_patterns:
                    pattern = os.path.join(drive, sub)
                    for path in glob.glob(pattern):
                        if os.path.isfile(path):
                            found["MUMU"] = path
                            _adb_logger.info("路径扫描发现 MUMU ADB: %s", path)
                            break
                    if "MUMU" in found:
                        break
                if "MUMU" in found:
                    break

    if not found:
        _adb_logger.warning("未找到任何模拟器 ADB，请在 GUI 中手动选择")

    return found


# 自动扫描结果缓存（惰性：首次访问 config.ADB_PATH / config._scanned_adb 时才扫描，
# 避免 import config 即触发注册表 + WMIC + 全盘 glob 的昂贵副作用）
_scan_cache = None
_scan_lock = threading.Lock()


def _ensure_scanned():
    """惰性执行一次模拟器 ADB 扫描并缓存结果（线程安全：检查与赋值都在锁内）。"""
    global _scan_cache
    with _scan_lock:
        if _scan_cache is None:
            _scan_cache = scan_adb_paths()
        return _scan_cache


def __getattr__(name):
    # PEP 562：仅当模块没有真实属性 name 时才调用。
    # set_adb_path 会创建真实的 ADB_PATH 全局，之后不再走到这里。
    if name == "_scanned_adb":
        return _ensure_scanned()
    if name == "ADB_PATH":
        return next(iter(_ensure_scanned().values()), "")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def set_adb_path(path):
    """运行时切换 ADB 路径（GUI 调用）。设置真实全局后，后续访问不再触发惰性扫描。"""
    global ADB_PATH
    ADB_PATH = path


def refresh_adb_scan():
    """强制重新扫描模拟器 ADB（GUI 刷新时调用），清除惰性缓存。"""
    global _scan_cache
    with _scan_lock:
        _scan_cache = None
    return _ensure_scanned()


# ===================== GUI 配置 =====================
# 截图预览区最大宽度（像素）
PREVIEW_MAX_WIDTH = 400
