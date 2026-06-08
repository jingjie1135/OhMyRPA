import time
import os
import cv2

from script_model import ScriptModel, ActionNode
from device_adapter import DeviceAdapter, HybridDeviceAdapter
import image_engine
import template_meta

class ScriptEngine:
    """
    通用脚本执行引擎，负责解析 ActionNode 流水线并调用底层接口。
    包揽阻塞状态控制、异常处理及弹窗守卫逻辑 (PopupGuard)。
    """
    def __init__(self, model: ScriptModel, device_id: str, pause_event=None, interrupt_check=None, callbacks=None, adapter: DeviceAdapter = None, call_stack: set = None):
        self.model = model
        self.device_id = device_id
        self.pause_event = pause_event
        self.interrupt_check = interrupt_check
        self.callbacks = callbacks or {}

        # DeviceAdapter（DRY：统一设备交互入口）
        self._adapter = adapter or HybridDeviceAdapter(device_id)

        # 嵌套 run_script 的调用链，用于检测循环引用（A→B→A）防止无限递归
        self._call_stack = set(call_stack) if call_stack else set()

        self.consecutive_fails = 0
        
    def _log(self, msg):
        if 'on_log' in self.callbacks:
            self.callbacks['on_log'](msg)
        else:
            print(msg)

    def _check_interrupt_and_pause(self):
        """实时检查 UI 传来的终止或暂停信号。"""
        if self.interrupt_check and self.interrupt_check():
            raise KeyboardInterrupt("User abort")
        if self.pause_event:
            self.pause_event.wait()
            
    def _run_popup_guard(self) -> bool:
        """全局弹窗守卫（防卡死扫描）"""
        guard_dir = self.model.config.guard_dir
        if not os.path.exists(guard_dir):
            return False
            
        self._log("🛡 触发弹窗守卫：正在扫描可能的干扰弹窗...")
        img = self._adapter.get_frame()
        if img is None: 
            return False

        # 一次性加载整个守卫目录的所有模板，避免循环内重复 I/O
        loaded_tmpls = image_engine.load_templates(guard_dir)
        if not loaded_tmpls:
            return False

        matches = image_engine.match_all(img, loaded_tmpls, threshold=0.8)
        if matches:
            name, cx, cy, score = matches[0]
            self._log(f"🛡 弹窗守卫命中目标 [{name}]，执行点击以关闭 ({cx}, {cy})")
            self._adapter.tap(cx, cy)
            self.consecutive_fails = 0
            return True
                
        return False

    def run(self):
        """主执行流程"""
        self._log(f"🎬 开始执行脚本: {self.model.name}")
        self.consecutive_fails = 0
        
        # 启动前预检查（生命周期钩子）
        if not self._pre_flight_checks():
            return
        
        try:
            # 临时方案：不支持嵌套循环或跳转，严格线性执行
            for action in self.model.actions:
                self._check_interrupt_and_pause()
                self._execute_action(action)
        except KeyboardInterrupt:
            self._log("⏹ 脚本运行已终止。")
        except Exception as e:
            self._log(f"🚨 脚本运行异常: {e}")
            import traceback
            traceback.print_exc()
            
        self._log(f"🏁 脚本运行完毕。")

    def _pre_flight_checks(self) -> bool:
        """启动前预检查（生命周期钩子），返回 False 则中止执行。"""
        # 分辨率一致性检测
        if self.model.config.check_resolution and self.model.config.resolution:
            from config import get_resolution_tag
            device_res = get_resolution_tag()
            script_res = self.model.config.resolution
            if device_res != "unknown" and script_res != device_res:
                self._log(f"❌ 分辨率不匹配！脚本适配 {script_res}，当前设备 {device_res}。脚本已中止。")
                return False
            self._log(f"✅ 分辨率检测通过: {device_res}")
        return True

    def _execute_action(self, action: ActionNode):
        action_type = action.type
        p = action.params
        
        if action_type == "tap":
            x, y = p.get('x', 0), p.get('y', 0)
            self._log(f"🎯 执行: 点击坐标 ({x}, {y})")
            self._adapter.tap(x, y)

        elif action_type == "swipe":
            x1, y1 = p.get('x1', 0), p.get('y1', 0)
            x2, y2 = p.get('x2', 0), p.get('y2', 0)
            dur = p.get('duration', 300)
            path = p.get('path', [])
            
            if path and getattr(self._adapter, 'supports_touch', False):
                self._log(f"👆 执行: 高精度轨迹滑动 ({len(path)} 个控制点)")
                self._adapter.swipe_path(path)
            else:
                self._log(f"👆 执行: 滑动 ({x1},{y1})→({x2},{y2}) {dur}ms")
                self._adapter.swipe(x1, y1, x2, y2, dur)
            
        elif action_type == "back":
            self._log("◀ 执行: 返回键")
            self._adapter.back()
            
        elif action_type == "home":
            self._log("⌂ 执行: 主页键")
            self._adapter.home()
            
        elif action_type == "app_switch":
            self._log("⎕ 执行: 多任务键")
            self._adapter.app_switch()
            
        elif action_type == "sleep":
            sec = p.get('seconds', 1.0)
            self._log(f"⏳ 执行: 等待 {sec} 秒")
            # 使用时间戳计时，避免浮点累加精度漂移
            start = time.time()
            while time.time() - start < sec:
                self._check_interrupt_and_pause()
                time.sleep(0.1)
                
        elif action_type == "find_and_tap":
            template = p.get('template', '')
            if not template:
                self._log("⚠️ 找图指令未配置目标图片。跳过。")
                return
                
            threshold = p.get('threshold', 0.9)
            timeout = p.get('timeout', 5.0)
            self._log(f"👁 寻找并点击图片 [{template}]，超时 {timeout}s")
            
            start_time = time.time()
            found = False
            
            # 模板路径解析优先级：绝对路径 → 项目 Pictures 目录 → templates/
            template_path = template
            if not os.path.exists(template_path):
                template_path = os.path.join(self.model.pictures_dir, template)
            if not os.path.exists(template_path):
                template_path = os.path.join("templates", template)
            
            # 预加载模板（移到循环外，避免重复 I/O）
            template_dir = os.path.dirname(template_path) or "."
            loaded_tmpls = image_engine.load_templates(template_dir)
            target_name = os.path.splitext(os.path.basename(template_path))[0]
            target_tmpl = [tmpl for tmpl in loaded_tmpls if tmpl[0] == target_name]
            
            if not target_tmpl:
                self._log(f"⚠️ 未找到模板文件: [{template}]")
                self._log(f"   解析路径: {template_path}")
                self._log(f"   Pictures目录: {self.model.pictures_dir}")
                return
            
            # 诊断用：跟踪匹配过程中的最高分数
            _diag_max_score = 0.0
            _diag_frame_count = 0
            _diag_frame_size = ""
            _diag_tmpl_size = f"{target_tmpl[0][1].shape[1]}x{target_tmpl[0][1].shape[0]}"
            
            while time.time() - start_time < timeout:
                self._check_interrupt_and_pause()
                img = self._adapter.get_frame()
                if img is None:
                    time.sleep(0.5)
                    continue
                
                _diag_frame_count += 1
                _diag_frame_size = f"{img.shape[1]}x{img.shape[0]}"
                    
                if 'on_screenshot' in self.callbacks:
                    self.callbacks['on_screenshot'](img)
                    
                matches = image_engine.match_all(img, target_tmpl, threshold)
                
                # 诊断：即使未匹配也获取最高分数
                if not matches:
                    import cv2
                    _res = cv2.matchTemplate(img, target_tmpl[0][1], cv2.TM_CCOEFF_NORMED)
                    _cur_max = float(_res.max())
                    if _cur_max > _diag_max_score:
                        _diag_max_score = _cur_max
                
                if matches:
                    name, cx, cy, score = matches[0]
                    # 应用点击偏移量
                    ox = p.get('offset_x', 0)
                    oy = p.get('offset_y', 0)
                    final_x, final_y = cx + ox, cy + oy
                    self._log(f"👉 找到图片 (匹配度:{score:.2f})，点击 ({final_x}, {final_y})")
                    self._adapter.tap(final_x, final_y)
                    found = True
                    self.consecutive_fails = 0
                    if 'on_match' in self.callbacks:
                        self.callbacks['on_match'](matches)
                    break
                    
                time.sleep(0.3)
                
            if not found:
                self._log(f"⚠️ 寻找图片超时: [{template}]")
                self._log(f"   📊 诊断: 模板={_diag_tmpl_size}, 截图={_diag_frame_size}, "
                          f"截图帧数={_diag_frame_count}, 最高匹配={_diag_max_score:.4f}, 阈值={threshold}")
                self._log(f"   📁 模板路径: {os.path.abspath(template_path)}")
                self._log(f"   🔌 设备: {self.device_id}")
                self.consecutive_fails += 1
                if self.model.config.popup_guard and self.consecutive_fails >= self.model.config.guard_trigger_fails:
                    self._run_popup_guard()
                    
        elif action_type == "wait_image":
            template = p.get('template', '')
            if not template:
                return
            threshold = p.get('threshold', 0.9)  # 虽然 UI 没配置，可以放个默认值
            timeout = p.get('timeout', 30.0)
            self._log(f"⏳ 一直等待图片 [{template}]，限 {timeout}s")
            
            start_time = time.time()
            # 模板路径解析优先级：绝对路径 → 项目 Pictures 目录 → templates/
            template_path = template
            if not os.path.exists(template_path):
                template_path = os.path.join(self.model.pictures_dir, template)
            if not os.path.exists(template_path):
                template_path = os.path.join("templates", template)
            
            # 预加载模板（移到循环外，避免重复 I/O）
            template_dir = os.path.dirname(template_path) or "."
            loaded_tmpls = image_engine.load_templates(template_dir)
            target_name = os.path.splitext(os.path.basename(template_path))[0]
            target_tmpl = [tmpl for tmpl in loaded_tmpls if tmpl[0] == target_name]
            
            if not target_tmpl:
                self._log(f"⚠️ 未找到模板文件: [{template}]")
                return
            
            while time.time() - start_time < timeout:
                self._check_interrupt_and_pause()
                img = self._adapter.get_frame()
                if img is None:
                    time.sleep(0.5)
                    continue
                    
                if 'on_screenshot' in self.callbacks:
                    self.callbacks['on_screenshot'](img)
                    
                matches = image_engine.match_all(img, target_tmpl, threshold)
                if matches:
                    self._log(f"✅ 图片 [{template}] 已出现。")
                    if 'on_match' in self.callbacks:
                        self.callbacks['on_match'](matches)
                    return
                time.sleep(0.5)
                
            on_fail = p.get('action_on_fail', 'abort')
            self._log(f"❌ 等待图片超时。配置的失效操作：{on_fail}")
            if on_fail == 'abort':
                raise Exception("等待超时，中止脚本执行")

        elif action_type in ("loop_start", "loop_end"):
            # 循环指令尚未实现，输出警告避免用户困惑
            self._log(f"⚠️ 循环指令 [{action_type}] 尚未实现，已跳过。")

        elif action_type == "multi_match":
            # 多模板匹配：单次截图找出所有能匹配的任务，依次点击并执行子动作
            templates = p.get("templates", [])
            if not templates:
                self._log("⚠️ 多图匹配指令无模板配置，跳过。")
                return
            
            self._log(f"🎯 多图匹配: 尝试匹配 {len(templates)} 种模板")
            
            # 预加载所有模板
            all_loaded = []
            for tpl_info in templates:
                tpl = tpl_info.get("template", "")
                tpl_path = self._resolve_template_path(tpl)
                tpl_dir = os.path.dirname(tpl_path) or "."
                loaded = image_engine.load_templates(tpl_dir)
                target_name = os.path.splitext(os.path.basename(tpl_path))[0]
                target = [t for t in loaded if t[0] == target_name]
                if target:
                    all_loaded.append((tpl_info, target))
            
            # 截图并匹配
            img = self._adapter.get_frame()
            if img is None:
                self._log("⚠️ 截图失败，跳过多图匹配。")
                return
            
            if 'on_screenshot' in self.callbacks:
                self.callbacks['on_screenshot'](img)
            
            hit_targets = []
            for tpl_info, target_tmpl in all_loaded:
                threshold = tpl_info.get("threshold", 0.9)
                matches = image_engine.match_all(img, target_tmpl, threshold)
                for match in matches:
                    hit_targets.append({
                        "tpl_info": tpl_info,
                        "match": match
                    })

            if hit_targets:
                self._log(f"🔍 多图匹配: 共在画面中找到 {len(hit_targets)} 个目标，依次执行")
                for hit in hit_targets:
                    self._check_interrupt_and_pause()
                    
                    tpl_info = hit["tpl_info"]
                    name, cx, cy, score = hit["match"]
                    
                    # 从 meta.json 读取偏移量
                    tpl_fname = os.path.basename(tpl_info.get('template', ''))
                    meta = template_meta.get(self.model.pictures_dir, tpl_fname)
                    ox = meta.get("offset_x", 0)
                    oy = meta.get("offset_y", 0)
                    final_x, final_y = cx + ox, cy + oy
                    
                    self._log(f"✅ 多图命中 [{tpl_fname}] "
                              f"分数={score:.2f}, 当前点击 ({final_x},{final_y})")
                    self._adapter.tap(final_x, final_y)
                    
                    if 'on_match' in self.callbacks:
                        self.callbacks['on_match']([hit["match"]])
                    
                    # 每次命中后执行子动作（自带 0.5s 延迟）
                    for sub_dict in p.get("sub_actions", []):
                        self._check_interrupt_and_pause()
                        time.sleep(0.5)
                        sub_node = ActionNode.from_dict(sub_dict)
                        self._execute_action(sub_node)
            else:
                self._log("🔍 多图匹配: 画面中未检出任何匹配目标")

        elif action_type == "run_script":
            # 执行外部脚本项目：加载引用的脚本并递归执行其所有步骤
            script_project = p.get("script_project", "")
            if not script_project:
                self._log("⚠️ 执行脚本指令未配置脚本项目名，跳过。")
                return

            self._log(f"📜 开始执行脚本: [{script_project}]")

            # 循环引用防护：若该脚本已在当前调用链中，拒绝再次进入，避免无限递归
            if script_project in self._call_stack:
                chain = " → ".join(list(self._call_stack) + [script_project])
                self._log(f"⛔ 检测到脚本循环引用，已阻止: {chain}")
                return

            # 路径安全：拒绝越出 Scripts/ 根目录的脚本名（防目录遍历）
            if not ScriptModel.is_safe_project_name(script_project):
                self._log(f"⛔ 非法脚本项目名（疑似路径遍历），已拒绝: {script_project}")
                return

            project_dir = os.path.join(ScriptModel.SCRIPTS_ROOT, script_project)
            if not os.path.isdir(project_dir):
                self._log(f"❌ 脚本项目不存在: {project_dir}")
                return

            try:
                sub_model = ScriptModel.load_from_project(project_dir)
            except Exception as e:
                self._log(f"❌ 加载脚本失败: {e}")
                return

            if not sub_model.actions:
                self._log(f"⚠️ 脚本 [{script_project}] 没有步骤，跳过。")
                return

            # 创建子引擎，复用当前的设备适配器、暂停/中断控制和回调
            # 调用链追加当前脚本名，供更深层的 run_script 检测循环引用
            sub_engine = ScriptEngine(
                model=sub_model,
                device_id=self.device_id,
                pause_event=self.pause_event,
                interrupt_check=self.interrupt_check,
                callbacks=self.callbacks,
                adapter=self._adapter,
                call_stack=self._call_stack | {script_project},
            )

            # 判断是否为循环脚本。
            # 注意：scan_interval 默认非零（1.0），不能用它判断循环模式，
            # 否则任何被引用的子脚本都会进入无限循环、永不返回父流程。
            # 仅当显式配置了有限的 max_loops（>0）时才以循环模式执行有限轮数。
            cfg = sub_model.config
            if getattr(cfg, 'max_loops', 0) > 0:
                self._log(f"🔄 脚本 [{script_project}] 以循环模式执行（{cfg.max_loops} 轮）")
                sub_engine.run_loop()
            else:
                # 线性执行所有步骤
                for sub_action in sub_model.actions:
                    self._check_interrupt_and_pause()
                    sub_engine._execute_action(sub_action)

            self._log(f"📜 脚本 [{script_project}] 执行完毕")

        else:
            self._log(f"⚠️ 未知指令类型: [{action_type}]，已跳过。")

    # =================== 循环执行模式 ===================

    def _resolve_template_path(self, template: str) -> str:
        """解析模板路径：绝对路径 → 项目 Pictures → templates/"""
        if os.path.exists(template):
            return template
        p2 = os.path.join(self.model.pictures_dir, template)
        if os.path.exists(p2):
            return p2
        p3 = os.path.join("templates", template)
        if os.path.exists(p3):
            return p3
        return template

    def run_loop(self, enabled_templates: list = None):
        """
        循环执行模式：按顺序执行所有步骤，执行完毕后等待间隔，进入下一轮。
        每轮按 actions 列表顺序逐个执行，multi_match 等指令通过 _execute_action 统一调度。

        Args:
            enabled_templates: 启用的模板文件名(basename)列表。为 None 表示不过滤、
                执行全部动作；否则仅执行模板名在集合内的 find_and_tap 动作，
                其余类型动作（sleep/swipe/multi_match 等）不受影响、照常执行。
        """
        cfg = self.model.config
        # 规整为集合便于快速判定；None 表示「不过滤」
        enabled_set = set(enabled_templates) if enabled_templates is not None else None
        self._log(f"🔄 循环模式启动: {self.model.name}")
        self._log(f"   间隔={cfg.scan_interval}s, 最大循环={cfg.max_loops or '无限'}")
        self._log(f"   共 {len(self.model.actions)} 个步骤")
        if enabled_set is not None:
            self._log(f"   启用模板过滤: {len(enabled_set)} 个 find_and_tap 模板已启用")
        
        if not self._pre_flight_checks():
            return
        
        if not self.model.actions:
            self._log("⚠️ 脚本没有任何步骤，循环模式无法启动。")
            return
        
        loop_count = 0
        
        try:
            while True:
                self._check_interrupt_and_pause()
                loop_count += 1
                
                # 检查最大循环限制
                if cfg.max_loops > 0 and loop_count > cfg.max_loops:
                    self._log(f"🏁 已达到最大循环次数 ({cfg.max_loops})，停止。")
                    break
                
                self._log(f"🔄 ── 第 {loop_count} 轮 ──")
                
                # 按顺序执行所有步骤
                for action in self.model.actions:
                    self._check_interrupt_and_pause()
                    # 启用模板过滤：被用户取消勾选的 find_and_tap 动作跳过执行
                    if enabled_set is not None and action.type == "find_and_tap":
                        tpl = os.path.basename(action.params.get("template", ""))
                        if tpl and tpl not in enabled_set:
                            continue
                    self._execute_action(action)
                
                # 等待扫描间隔
                wait_start = time.time()
                while time.time() - wait_start < cfg.scan_interval:
                    self._check_interrupt_and_pause()
                    time.sleep(0.1)
                    
        except KeyboardInterrupt:
            self._log("⏹ 循环模式已终止。")
        except Exception as e:
            self._log(f"🚨 循环模式异常: {e}")
            import traceback
            traceback.print_exc()
        
        self._log(f"🏁 循环模式结束，共执行 {loop_count} 轮。")

