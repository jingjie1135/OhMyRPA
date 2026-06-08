"""
流程按批次执行编排器。

执行流程：
  批次1 → 启动设备 → 等待ADB → 并行执行步骤 → (auto_close时)关闭设备
  批次2 → ...
  全部完成 → finished_signal

注意：用户手动停止时，仅中断执行，不关闭任何实例。
"""

import time
import threading
import os
import copy

from PyQt6.QtCore import QThread, pyqtSignal

from script_model import ScriptModel, ActionNode
from script_engine import ScriptEngine
from emulator_manager import EmulatorManager, DeviceInfo
from device_adapter import HybridDeviceAdapter


class WorkflowRunner(QThread):
    """
    流程批次编排线程。

    按批次顺序执行流程步骤，每个批次内多设备并行执行。
    批次切换时负责启停模拟器实例。
    """

    # ========== 信号 ==========
    log_signal = pyqtSignal(str)               # 日志
    status_signal = pyqtSignal(str)             # 状态文本
    batch_progress_signal = pyqtSignal(int, int) # (当前批次索引, 总批次数)
    finished_signal = pyqtSignal()              # 全部完成

    def __init__(self, workflow_model, parent=None):
        """
        Args:
            workflow_model: WorkflowModel 实例（含 steps + batches）
        """
        super().__init__(parent)
        self._wf_model = workflow_model
        self._stopped = False  # 用户手动停止标记

    def stop(self):
        """用户主动停止（不关闭实例）"""
        self._stopped = True
        self.requestInterruption()

    def run(self):
        """主执行逻辑：按批次串行调度"""
        batches = self._wf_model.batches
        steps = self._wf_model.steps
        wf_name = self._wf_model.name

        if not batches:
            self._log(f"⚠️ 流程 [{wf_name}] 没有配置设备批次，无法执行。")
            self.finished_signal.emit()
            return

        if not steps:
            self._log(f"⚠️ 流程 [{wf_name}] 没有执行步骤。")
            self.finished_signal.emit()
            return

        self._log(f"🚀 流程 [{wf_name}] 开始执行: {len(batches)} 个批次, {len(steps)} 个步骤")
        self.status_signal.emit("流程执行中")

        for batch_idx, batch in enumerate(batches):
            if self._stopped or self.isInterruptionRequested():
                self._log("⏹ 用户停止，跳过后续批次。")
                break

            batch_name = batch.get("name", f"批次{batch_idx + 1}")
            devices_data = batch.get("devices", [])
            auto_close = batch.get("auto_close", True)

            # 反序列化设备信息
            devices = []
            for d in devices_data:
                if isinstance(d, dict):
                    devices.append(DeviceInfo.from_dict(d))
                elif isinstance(d, DeviceInfo):
                    devices.append(d)

            if not devices:
                self._log(f"⚠️ {batch_name} 没有设备，跳过。")
                continue

            self.batch_progress_signal.emit(batch_idx + 1, len(batches))
            self._log(f"\n{'='*50}")
            self._log(f"📦 开始执行 {batch_name} ({len(devices)} 台设备)")
            self._log(f"{'='*50}")

            # ===== 阶段1：启动模拟器实例 =====
            self._log(f"🔧 正在启动 {batch_name} 的模拟器实例...")
            for dev in devices:
                if self._stopped:
                    break
                if dev.device_type in ("ldplayer", "mumu") and not dev.running:
                    self._log(f"  ▶ 启动 {dev.name} (索引 {dev.index})...")
                    EmulatorManager.launch(dev)
                    dev.running = True
                elif dev.device_type == "phone":
                    self._log(f"  📱 {dev.name} 为手机设备，无需启动。")
                else:
                    self._log(f"  ✅ {dev.name} 已在运行中。")
                
                # 修复：如果设备在被选入批次时未运行，device_id 会为空。
                # 启动后需要根据模拟器类型和索引动态计算 ADB 连接地址。
                if not dev.device_id and dev.index >= 0:
                    if dev.device_type == "ldplayer":
                        # 雷电模拟器 ADB 端口规律：5555 + index * 2
                        dev.device_id = f"emulator-{5554 + dev.index * 2}"
                        self._log(f"  🔗 动态分配 ADB 地址: {dev.device_id}")
                    elif dev.device_type == "mumu":
                        # MuMu 使用 adb devices 扫描的格式
                        dev.device_id = f"127.0.0.1:{7555 + dev.index * 10}"
                        self._log(f"  🔗 动态分配 ADB 地址: {dev.device_id}")

            if self._stopped:
                break

            # ===== 阶段2：等待所有设备 ADB 就绪 =====
            self._log(f"⏳ 等待 {batch_name} 的设备 ADB 连接就绪...")
            ready_devices = []
            for dev in devices:
                if self._stopped:
                    break
                self._log(f"  ⏳ 等待 {dev.name} ({dev.device_id})...")
                if EmulatorManager.wait_adb_ready(dev, timeout=60):
                    self._log(f"  ✅ {dev.name} ADB 就绪")
                    ready_devices.append(dev)
                else:
                    self._log(f"  ❌ {dev.name} ADB 连接超时，该设备将被跳过")

            if self._stopped:
                break

            if not ready_devices:
                self._log(f"❌ {batch_name} 没有可用设备，跳过。")
                continue

            # ===== 阶段3：为每台设备并行执行流程步骤 =====
            self._log(f"🎬 {batch_name}: 在 {len(ready_devices)} 台设备上并行执行 {len(steps)} 个步骤")

            # 构建临时 ScriptModel（共享步骤数据）
            script_model = ScriptModel(name=f"流程:{wf_name}")
            script_model.actions = list(steps)
            # 设置 Pictures 目录
            if self._wf_model.pictures_dir:
                script_model.project_dir = self._wf_model.project_dir

            # 暂停控制（统一）
            pause_event = threading.Event()
            pause_event.set()

            # 为每台设备创建引擎并在线程中执行
            threads = []
            for dev in ready_devices:
                if self._stopped:
                    break
                # 每台设备使用独立的步骤副本，避免多设备并发共享同一批 ActionNode
                # （执行器未来若写入 params 也不会互相串改）
                dev_model = copy.deepcopy(script_model)
                t = threading.Thread(
                    target=self._run_on_device,
                    args=(dev, dev_model, pause_event),
                    name=f"Engine-{dev.name}",
                    daemon=True,
                )
                threads.append(t)
                t.start()

            # 等待所有设备线程完成
            for t in threads:
                while t.is_alive():
                    if self._stopped:
                        # 用户停止：不需要等待全部完成，引擎会自行中断
                        break
                    t.join(timeout=1.0)

            if self._stopped:
                self._log("⏹ 用户停止，等待引擎线程退出...")
                # 给引擎一点时间自然退出
                for t in threads:
                    t.join(timeout=5.0)
                break

            self._log(f"✅ {batch_name} 所有设备执行完毕")

            # ===== 阶段4：按设置关闭模拟器 =====
            if auto_close:
                self._log(f"🔌 关闭 {batch_name} 的模拟器实例...")
                for dev in devices:
                    if dev.device_type in ("ldplayer", "mumu"):
                        self._log(f"  ⏹ 关闭 {dev.name}...")
                        EmulatorManager.quit(dev)
                # 等待模拟器实际关闭（给予一些缓冲时间）
                time.sleep(3)
            else:
                self._log(f"ℹ️ {batch_name} 配置为不自动关闭实例。")

        # ===== 执行结束 =====
        if self._stopped:
            self._log(f"\n⏹ 流程 [{wf_name}] 被用户中止。")
        else:
            self._log(f"\n🏁 流程 [{wf_name}] 全部批次执行完毕！")

        self.status_signal.emit("已停止")
        self.finished_signal.emit()

    def _run_on_device(self, device: DeviceInfo, script_model: ScriptModel,
                       pause_event: threading.Event):
        """
        在单台设备上执行所有流程步骤（在独立线程中运行）。
        """
        device_id = device.device_id
        self._log(f"  🎯 [{device.name}] 开始执行...")

        try:
            adapter = HybridDeviceAdapter(device_id)

            engine = ScriptEngine(
                model=script_model,
                device_id=device_id,
                pause_event=pause_event,
                interrupt_check=self.isInterruptionRequested,
                callbacks={
                    'on_log': lambda msg: self._log(f"  [{device.name}] {msg}"),
                },
                adapter=adapter,
            )

            # 线性执行所有步骤
            for action in script_model.actions:
                if self._stopped or self.isInterruptionRequested():
                    break
                pause_event.wait()
                engine._execute_action(action)

        except KeyboardInterrupt:
            self._log(f"  [{device.name}] 执行被中断")
        except Exception as e:
            self._log(f"  [{device.name}] ❌ 执行异常: {e}")
            import traceback
            traceback.print_exc()

        self._log(f"  ✅ [{device.name}] 执行结束")

    def _log(self, msg: str):
        """线程安全的日志输出"""
        self.log_signal.emit(msg)
