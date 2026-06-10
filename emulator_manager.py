"""
设备发现与管理引擎。

负责扫描本机已安装的模拟器实例（雷电/MuMu）和手机设备，
提供启动/关闭模拟器实例的能力。与 GUI 完全解耦。
"""

import os
import sys
import re
import json
import subprocess
import threading
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

import config

logger = logging.getLogger(__name__)

# Windows 下隐藏子进程控制台窗口
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0


def _decode_output(b) -> str:
    """解码子进程输出：优先 UTF-8，失败回退 GBK（中文 Windows 下实例名/路径含中文）。"""
    if b is None:
        return ""
    if isinstance(b, str):
        return b
    try:
        return b.decode('utf-8')
    except UnicodeDecodeError:
        return b.decode('gbk', errors='replace')


# =================== 数据模型 ===================

@dataclass
class DeviceInfo:
    """统一设备信息（模拟器实例或手机）"""
    device_type: str = ""       # "ldplayer" / "mumu" / "phone"
    device_id: str = ""         # ADB 连接地址（如 "127.0.0.1:5555"）或序列号
    name: str = ""              # 显示名称（如 "雷电-0"、"OPPO A97"）
    index: int = -1             # 模拟器实例索引（手机为 -1）
    running: bool = False       # 是否运行中
    console_path: str = ""      # 管理工具完整路径（手机为空）

    def to_dict(self) -> dict:
        """序列化为字典（用于 JSON 保存）"""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'DeviceInfo':
        """从字典反序列化"""
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# =================== 管理工具定位 ===================

def _find_ldconsole() -> Optional[str]:
    """
    定位雷电模拟器的 ldconsole.exe 管理工具。
    策略：从注册表/进程扫描已知的雷电安装目录中查找。
    """
    # 复用 config.py 的注册表扫描结果
    registry_dirs = config._search_registry_install_paths()
    ld_dir = registry_dirs.get("雷电", "")

    if ld_dir:
        candidate = os.path.join(ld_dir, "ldconsole.exe")
        if os.path.isfile(candidate):
            return candidate

    # 从 ADB 路径反推（ldconsole.exe 和 adb.exe 通常在同一目录）
    adb_paths = config._scanned_adb
    ld_adb = adb_paths.get("雷电", "")
    if ld_adb:
        ld_dir = os.path.dirname(ld_adb)
        candidate = os.path.join(ld_dir, "ldconsole.exe")
        if os.path.isfile(candidate):
            return candidate

    return None


def _find_mumu_manager() -> Optional[str]:
    """
    定位 MuMu 模拟器的 MuMuManager.exe 管理工具。
    策略：从注册表/进程扫描已知的 MuMu 安装目录中查找 shell/ 下的管理工具。
    """
    registry_dirs = config._search_registry_install_paths()
    mumu_dir = registry_dirs.get("MUMU", "")

    if mumu_dir:
        # MuMuManager.exe 通常在 shell/ 或 nx_main/ 子目录
        for sub in ["shell", "nx_main", ""]:
            candidate = os.path.join(mumu_dir, sub, "MuMuManager.exe") if sub else os.path.join(mumu_dir, "MuMuManager.exe")
            if os.path.isfile(candidate):
                return candidate

    # 从 ADB 路径反推
    adb_paths = config._scanned_adb
    mumu_adb = adb_paths.get("MUMU", "")
    if mumu_adb:
        mumu_dir = os.path.dirname(mumu_adb)
        for sub in ["", ".."]:
            base = os.path.normpath(os.path.join(mumu_dir, sub))
            candidate = os.path.join(base, "MuMuManager.exe")
            if os.path.isfile(candidate):
                return candidate

    return None


# =================== 解析器 ===================

def _parse_ld_list2(output: str, console_path: str, adb_running_ids: set = None) -> list[DeviceInfo]:
    """
    解析雷电 `ldconsole list2` 的输出。
    输出格式（每行逗号分隔）：
      索引,名称,顶层窗口句柄,绑定窗口句柄,是否进入,PID,VBox PID

    adb_running_ids: 当前 adb devices 的设备 ID 集合，用于交叉验证端口
    （雷电端口公式 5555+index*2 在改过端口/多开布局时可能不准）。
    """
    devices = []
    if adb_running_ids is None:
        adb_running_ids = set()
    for line in output.strip().splitlines():
        parts = line.strip().split(",")
        if len(parts) < 6:
            continue
        try:
            index = int(parts[0])
            name = parts[1] or f"雷电-{index}"
            running = int(parts[4]) == 1 if parts[4].isdigit() else False
            pid = int(parts[5]) if parts[5].isdigit() else 0

            # 雷电模拟器 ADB 端口规律：5555 + index * 2
            adb_port = 5555 + index * 2
            formula_id = f"127.0.0.1:{adb_port}"
            device_id = ""
            if running:
                # 交叉验证：优先采用 adb devices 中实际存在的端口（兼容 emulator-XXXX 变体）
                alt_id = f"emulator-{adb_port}"
                if formula_id in adb_running_ids:
                    device_id = formula_id
                elif alt_id in adb_running_ids:
                    device_id = alt_id
                else:
                    device_id = formula_id
                    if adb_running_ids:
                        logger.debug(
                            "雷电实例 %s(index=%d) 报告运行，但 adb devices 未见端口 %d，device_id 可能不准确",
                            name, index, adb_port,
                        )

            devices.append(DeviceInfo(
                device_type="ldplayer",
                device_id=device_id,
                name=name,
                index=index,
                running=running,
                console_path=console_path,
            ))
        except (ValueError, IndexError) as e:
            logger.debug("解析雷电 list2 行失败: %s, 原因: %s", line, e)
            continue

    return devices


def _parse_mumu_info(output: str, console_path: str,
                     adb_running_ids: set = None) -> list[DeviceInfo]:
    """
    解析 MuMu `MuMuManager info -v all` 的 JSON 输出。

    MuMu12 输出格式为 {"0": {...}, "1": {...}} 字典，每个值含：
      index, name, is_process_started, is_android_started 等字段。

    注意：is_process_started 在部分 MuMu 版本中不可靠，
    因此额外通过 adb devices 输出中的 emulator-XXXX 格式交叉验证。

    MuMu ADB 端口规律：emulator-5554, emulator-5556, ... (5554 + index * 2)
    """
    devices = []
    if adb_running_ids is None:
        adb_running_ids = set()

    try:
        data = json.loads(output)

        # MuMu12 返回 {"0": {info}, "1": {info}, ...} 字典格式
        if isinstance(data, dict):
            # 检查是否是 {"vms": [...]} 格式（旧版）
            if "vms" in data and isinstance(data["vms"], list):
                items = data["vms"]
            else:
                # 标准 MuMu12 格式：遍历 values
                items = list(data.values())
        elif isinstance(data, list):
            items = data
        else:
            return devices

        for item in items:
            if not isinstance(item, dict):
                continue

            # 解析索引（MuMu12 的 index 可能是字符串）
            raw_index = item.get("index", item.get("id", -1))
            try:
                index = int(raw_index)
            except (ValueError, TypeError):
                index = -1

            name = item.get("name", f"MuMu-{index}")

            # MuMu ADB 端口规律：emulator-5554 + index * 2
            adb_port = 5554 + index * 2
            emulator_id = f"emulator-{adb_port}"

            # 运行状态：优先通过 ADB 交叉验证，其次用 MuMu 报告
            is_running_adb = emulator_id in adb_running_ids
            is_running_info = item.get("is_process_started", False) or item.get("is_android_started", False)
            running = is_running_adb or is_running_info

            device_id = emulator_id if running else ""

            devices.append(DeviceInfo(
                device_type="mumu",
                device_id=device_id,
                name=name,
                index=index,
                running=running,
                console_path=console_path,
            ))
    except (json.JSONDecodeError, TypeError) as e:
        logger.debug("解析 MuMu info 输出失败: %s", e)

    return devices


def _get_adb_device_ids() -> set:
    """
    获取当前 adb devices 中所有已连接的设备 ID 集合。
    用于交叉验证模拟器运行状态。
    """
    ids = set()
    if not config.ADB_PATH:
        return ids
    try:
        result = subprocess.run(
            [config.ADB_PATH, "devices"],
            capture_output=True, timeout=10,
            creationflags=_SUBPROCESS_FLAGS
        )
        for line in _decode_output(result.stdout).strip().splitlines()[1:]:
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1] == "device":
                ids.add(parts[0])
    except Exception as e:
        logger.debug("获取 ADB 设备列表失败: %s", e)
    return ids


def _scan_phone_devices(known_emulator_ids: set) -> list[DeviceInfo]:
    """
    通过 adb devices 扫描真机设备。
    排除：已知模拟器 ADB 地址、emulator-* 前缀的设备。
    """
    devices = []
    if not config.ADB_PATH:
        return devices

    try:
        result = subprocess.run(
            [config.ADB_PATH, "devices", "-l"],
            capture_output=True, timeout=10,
            creationflags=_SUBPROCESS_FLAGS
        )
        for line in _decode_output(result.stdout).strip().splitlines()[1:]:
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1] == "device":
                device_id = parts[0]

                # 排除已知模拟器地址
                if device_id in known_emulator_ids:
                    continue

                # 排除 emulator-* 前缀（MuMu/其他模拟器的 ADB 格式）
                if device_id.startswith("emulator-"):
                    continue

                # 排除 127.0.0.1 本地地址（通常为模拟器）
                if device_id.startswith("127.0.0.1:"):
                    continue

                # 尝试获取设备型号
                model = "手机设备"
                model_match = re.search(r'model:(\S+)', line)
                if model_match:
                    model = model_match.group(1).replace("_", " ")

                devices.append(DeviceInfo(
                    device_type="phone",
                    device_id=device_id,
                    name=model,
                    index=-1,
                    running=True,
                    console_path="",
                ))
    except Exception as e:
        logger.debug("扫描手机设备失败: %s", e)

    return devices


# =================== 公共 API ===================

class EmulatorManager:
    """设备发现与管理（静态方法集合）"""

    # 扫描结果缓存
    _cache: list[DeviceInfo] = []
    # 缓存与扫描互斥锁（防止并发 scan_all 重复扫描 / 写缓存竞争）
    _cache_lock: threading.Lock = threading.Lock()

    @staticmethod
    def scan_all() -> list[DeviceInfo]:
        """
        扫描所有设备（雷电模拟器 + MuMu模拟器 + 手机设备）。
        返回 DeviceInfo 列表，结果同时缓存。
        整个扫描过程持有 _cache_lock，并发调用会串行化（去重并发扫描）。
        """
        with EmulatorManager._cache_lock:
            return EmulatorManager._scan_all_locked()

    @staticmethod
    def _scan_all_locked() -> list[DeviceInfo]:
        all_devices = []
        known_emulator_ids = set()

        # 预先获取所有 ADB 已连接设备（用于交叉验证模拟器运行状态）
        adb_running_ids = _get_adb_device_ids()

        # ===== 扫描雷电模拟器 =====
        ldconsole = _find_ldconsole()
        if ldconsole:
            try:
                result = subprocess.run(
                    [ldconsole, "list2"],
                    capture_output=True, timeout=10,
                    creationflags=_SUBPROCESS_FLAGS
                )
                ld_stdout = _decode_output(result.stdout)
                if result.returncode == 0 and ld_stdout.strip():
                    ld_devices = _parse_ld_list2(ld_stdout, ldconsole, adb_running_ids)
                    all_devices.extend(ld_devices)
                    known_emulator_ids.update(d.device_id for d in ld_devices if d.device_id)
                    logger.info("雷电模拟器: 发现 %d 个实例", len(ld_devices))
            except Exception as e:
                logger.warning("扫描雷电模拟器失败: %s", e)
        else:
            logger.debug("未找到 ldconsole.exe，跳过雷电模拟器扫描")

        # ===== 扫描 MuMu 模拟器 =====
        mumu_mgr = _find_mumu_manager()
        if mumu_mgr:
            try:
                result = subprocess.run(
                    [mumu_mgr, "info", "-v", "all"],
                    capture_output=True, timeout=10,
                    creationflags=_SUBPROCESS_FLAGS
                )
                mumu_stdout = _decode_output(result.stdout)
                if result.returncode == 0 and mumu_stdout.strip():
                    mumu_devices = _parse_mumu_info(
                        mumu_stdout, mumu_mgr,
                        adb_running_ids=adb_running_ids
                    )
                    all_devices.extend(mumu_devices)
                    # 将 MuMu 的 emulator-XXXX 地址加入已知集合
                    known_emulator_ids.update(d.device_id for d in mumu_devices if d.device_id)
                    logger.info("MuMu模拟器: 发现 %d 个实例", len(mumu_devices))
            except Exception as e:
                logger.warning("扫描 MuMu 模拟器失败: %s", e)
        else:
            logger.debug("未找到 MuMuManager.exe，跳过 MuMu 模拟器扫描")

        # ===== 扫描手机设备 =====
        phone_devices = _scan_phone_devices(known_emulator_ids)
        all_devices.extend(phone_devices)
        if phone_devices:
            logger.info("手机设备: 发现 %d 台", len(phone_devices))

        # 缓存结果
        EmulatorManager._cache = all_devices
        return all_devices

    @staticmethod
    def launch(device: DeviceInfo) -> bool:
        """启动模拟器实例。仅支持模拟器设备，手机设备返回 True（无需启动）。"""
        if device.device_type == "phone":
            return True  # 手机不需要启动

        if not device.console_path or not os.path.isfile(device.console_path):
            logger.error("管理工具路径无效: %s", device.console_path)
            return False

        try:
            if device.device_type == "ldplayer":
                cmd = [device.console_path, "launch", "--index", str(device.index)]
            elif device.device_type == "mumu":
                cmd = [device.console_path, "launch", "-v", str(device.index)]
            else:
                return False

            r = subprocess.run(cmd, capture_output=True, timeout=30,
                               creationflags=_SUBPROCESS_FLAGS)
            if r.returncode != 0:
                logger.warning("启动 %s (索引 %d) 失败 (rc=%d): %s",
                               device.name, device.index, r.returncode,
                               _decode_output(r.stderr).strip())
                return False
            logger.info("已启动 %s (索引 %d)", device.name, device.index)
            return True
        except Exception as e:
            logger.error("启动 %s 失败: %s", device.name, e)
            return False

    @staticmethod
    def quit(device: DeviceInfo) -> bool:
        """关闭模拟器实例。仅支持模拟器设备。"""
        if device.device_type == "phone":
            return False  # 手机不支持远程关闭

        if not device.console_path or not os.path.isfile(device.console_path):
            return False

        try:
            if device.device_type == "ldplayer":
                cmd = [device.console_path, "quit", "--index", str(device.index)]
            elif device.device_type == "mumu":
                # MuMu 没有标准的 quit 命令，尝试 shutdown
                cmd = [device.console_path, "shutdown", "-v", str(device.index)]
            else:
                return False

            r = subprocess.run(cmd, capture_output=True, timeout=15,
                               creationflags=_SUBPROCESS_FLAGS)
            if r.returncode != 0:
                logger.warning("关闭 %s (索引 %d) 失败 (rc=%d): %s",
                               device.name, device.index, r.returncode,
                               _decode_output(r.stderr).strip())
                return False
            logger.info("已关闭 %s (索引 %d)", device.name, device.index)
            return True
        except Exception as e:
            logger.error("关闭 %s 失败: %s", device.name, e)
            return False

    @staticmethod
    def wait_adb_ready(device: DeviceInfo, timeout: int = 30) -> bool:
        """等待设备 ADB 连接就绪。"""
        if not config.ADB_PATH or not device.device_id:
            return False

        import time
        start = time.time()
        while time.time() - start < timeout:
            try:
                result = subprocess.run(
                    [config.ADB_PATH, "-s", device.device_id, "shell", "echo", "ok"],
                    capture_output=True, timeout=5,
                    creationflags=_SUBPROCESS_FLAGS
                )
                if result.returncode == 0 and "ok" in _decode_output(result.stdout):
                    logger.info("设备 %s ADB 就绪", device.device_id)
                    return True
            except Exception:
                # 单次探测失败属正常（设备尚未就绪），记 debug 便于排查配置类错误
                logger.debug("等待设备 %s ADB 就绪探测失败", device.device_id, exc_info=True)
            time.sleep(1)

        logger.warning("等待设备 %s ADB 超时 (%ds)", device.device_id, timeout)
        return False
