import time
import os
import cv2

from script_model import ScriptModel, ActionNode
from adb_utils import screencap_to_memory, tap
import image_engine
import template_meta

class ScriptEngine:
    """
    通用脚本执行引擎，负责解析 ActionNode 流水线并调用底层接口。
    包揽阻塞状态控制、异常处理及弹窗守卫逻辑 (PopupGuard)。
    """
    def __init__(self, model: ScriptModel, device_id: str, pause_event=None, interrupt_check=None, callbacks=None):
        self.model = model
        self.device_id = device_id
        self.pause_event = pause_event
        self.interrupt_check = interrupt_check
        self.callbacks = callbacks or {}
        
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
        img = screencap_to_memory(self.device_id)
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
            tap(self.device_id, cx, cy)
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
            tap(self.device_id, x, y)

        elif action_type == "swipe":
            x1, y1 = p.get('x1', 0), p.get('y1', 0)
            x2, y2 = p.get('x2', 0), p.get('y2', 0)
            dur = p.get('duration', 300)
            self._log(f"👆 执行: 滑动 ({x1},{y1})→({x2},{y2}) {dur}ms")
            from adb_utils import swipe as adb_swipe
            adb_swipe(self.device_id, x1, y1, x2, y2, dur)
            
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
                return
            
            while time.time() - start_time < timeout:
                self._check_interrupt_and_pause()
                img = screencap_to_memory(self.device_id)
                if img is None:
                    time.sleep(0.5)
                    continue
                    
                if 'on_screenshot' in self.callbacks:
                    self.callbacks['on_screenshot'](img)
                    
                matches = image_engine.match_all(img, target_tmpl, threshold)
                
                if matches:
                    name, cx, cy, score = matches[0]
                    # 应用点击偏移量
                    ox = p.get('offset_x', 0)
                    oy = p.get('offset_y', 0)
                    final_x, final_y = cx + ox, cy + oy
                    self._log(f"👉 找到图片 (匹配度:{score:.2f})，点击 ({final_x}, {final_y})")
                    tap(self.device_id, final_x, final_y)
                    found = True
                    self.consecutive_fails = 0
                    if 'on_match' in self.callbacks:
                        self.callbacks['on_match'](matches)
                    break
                    
                time.sleep(0.3)
                
            if not found:
                self._log(f"⚠️ 寻找图片超时: [{template}]")
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
                img = screencap_to_memory(self.device_id)
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
            # 多模板匹配：截图 → 逐模板搜索 → 点击第一个命中的
            templates = p.get("templates", [])
            if not templates:
                self._log("⚠️ 多图匹配指令无模板配置，跳过。")
                return
            
            self._log(f"🎯 多图匹配: {len(templates)} 个模板")
            
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
            img = screencap_to_memory(self.device_id)
            if img is None:
                self._log("⚠️ 截图失败，跳过多图匹配。")
                return
            
            if 'on_screenshot' in self.callbacks:
                self.callbacks['on_screenshot'](img)
            
            hit_count = 0
            for tpl_info, target_tmpl in all_loaded:
                threshold = tpl_info.get("threshold", 0.9)
                matches = image_engine.match_all(img, target_tmpl, threshold)
                if matches:
                    name, cx, cy, score = matches[0]
                    # 从 meta.json 读取偏移量
                    tpl_fname = os.path.basename(tpl_info.get('template', ''))
                    meta = template_meta.get(self.model.pictures_dir, tpl_fname)
                    ox = meta.get("offset_x", 0)
                    oy = meta.get("offset_y", 0)
                    final_x, final_y = cx + ox, cy + oy
                    self._log(f"✅ 多图匹配命中 [{tpl_info.get('template','')}] "
                              f"分数={score:.2f}, 点击 ({final_x},{final_y})")
                    tap(self.device_id, final_x, final_y)
                    hit_count += 1
                    if 'on_match' in self.callbacks:
                        self.callbacks['on_match'](matches)
                    
                    # 每次命中后执行子动作
                    for sub_dict in p.get("sub_actions", []):
                        self._check_interrupt_and_pause()
                        sub_node = ActionNode.from_dict(sub_dict)
                        self._execute_action(sub_node)
            
            if hit_count == 0:
                self._log("🔍 多图匹配: 无命中")
            else:
                self._log(f"🔍 多图匹配: 共命中 {hit_count} 个模板")

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

    def _build_watch_rules(self, enabled_templates: list = None) -> list:
        """
        从 actions 列表构建 watch_rules。
        每个 find_and_tap 作为一条 rule，其后续的 tap/sleep 直到下一个 find_and_tap 作为子动作。
        enabled_templates: 可选白名单（模板文件名列表），为 None 则全部启用。
        """
        rules = []
        current_rule = None
        
        for action in self.model.actions:
            if action.type == "find_and_tap":
                tpl = action.params.get("template", "")
                tpl_name = os.path.basename(tpl)
                # 白名单过滤
                if enabled_templates is not None and tpl_name not in enabled_templates:
                    current_rule = None
                    continue
                
                tpl_path = self._resolve_template_path(tpl)
                # 从 meta.json 读取偏移量
                meta = template_meta.get(self.model.pictures_dir, tpl_name)
                current_rule = {
                    "template_path": tpl_path,
                    "template_name": tpl_name,
                    "threshold": action.params.get("threshold", 0.9),
                    "offset_x": meta.get("offset_x", 0),
                    "offset_y": meta.get("offset_y", 0),
                    "sub_actions": [],
                    "handled": False,
                }
                rules.append(current_rule)
            
            elif action.type == "multi_match":
                # multi_match 节点：将 templates 数组展开为多条独立的 watch rule
                templates = action.params.get("templates", [])
                for tpl_info in templates:
                    tpl = tpl_info.get("template", "")
                    tpl_name = os.path.basename(tpl)
                    # 白名单过滤
                    if enabled_templates is not None and tpl_name not in enabled_templates:
                        continue
                    
                    tpl_path = self._resolve_template_path(tpl)
                    # 从 meta.json 读取偏移量
                    meta = template_meta.get(self.model.pictures_dir, tpl_name)
                    # 将嵌入的 sub_actions 转为 ActionNode 对象
                    embedded_subs = [
                        ActionNode.from_dict(sd)
                        for sd in action.params.get("sub_actions", [])
                    ]
                    current_rule = {
                        "template_path": tpl_path,
                        "template_name": tpl_name,
                        "threshold": tpl_info.get("threshold", 0.9),
                        "offset_x": meta.get("offset_x", 0),
                        "offset_y": meta.get("offset_y", 0),
                        "sub_actions": embedded_subs,
                        "handled": False,
                        "_from_multi_match": True,
                    }
                    rules.append(current_rule)
            
            elif current_rule is not None and action.type in ("tap", "sleep", "swipe"):
                # 归入当前 rule 的子动作
                current_rule["sub_actions"].append(action)
        
        return rules

    def run_loop(self, enabled_templates: list = None):
        """
        循环执行模式：截图 → 匹配 watch_rules → 执行 → 默认点击 → 循环。
        enabled_templates: 启用的模板文件名列表，None 表示全部。
        """
        cfg = self.model.config
        self._log(f"🔄 循环模式启动: {self.model.name}")
        self._log(f"   间隔={cfg.scan_interval}s, 最大循环={cfg.max_loops or '无限'}")
        
        if not self._pre_flight_checks():
            return
        
        # 构建 watch_rules
        rules = self._build_watch_rules(enabled_templates)
        if not rules:
            self._log("⚠️ 没有可用的找图规则，循环模式无法启动。")
            return
        
        self._log(f"📋 已加载 {len(rules)} 条监视规则:")
        for i, rule in enumerate(rules):
            self._log(f"   {i+1}. [{rule['template_name']}] 阈值={rule['threshold']}")
        
        # 预加载全部模板（性能优化，避免每轮重复 I/O）
        all_templates = []
        template_dirs = set()
        for rule in rules:
            template_dirs.add(os.path.dirname(rule["template_path"]) or ".")
        for td in template_dirs:
            all_templates.extend(image_engine.load_templates(td))
        
        loop_count = 0
        
        try:
            while True:
                self._check_interrupt_and_pause()
                loop_count += 1
                
                # 检查最大循环限制
                if cfg.max_loops > 0 and loop_count > cfg.max_loops:
                    self._log(f"🏁 已达到最大循环次数 ({cfg.max_loops})，停止。")
                    break
                
                # 截图
                img = screencap_to_memory(self.device_id)
                if img is None:
                    time.sleep(cfg.scan_interval)
                    continue
                
                if 'on_screenshot' in self.callbacks:
                    self.callbacks['on_screenshot'](img)
                
                # 遍历所有规则进行匹配
                any_matched = False
                for rule in rules:
                    if rule["handled"]:
                        continue  # 本轮已处理，跳过
                    
                    self._check_interrupt_and_pause()
                    
                    # 查找该规则对应的已加载模板
                    target_name = os.path.splitext(rule["template_name"])[0]
                    target_tmpl = [t for t in all_templates if t[0] == target_name]
                    if not target_tmpl:
                        continue
                    
                    matches = image_engine.match_all(img, target_tmpl, rule["threshold"])
                    if matches:
                        name, cx, cy, score = matches[0]
                        ox, oy = rule["offset_x"], rule["offset_y"]
                        final_x, final_y = cx + ox, cy + oy
                        self._log(f"🔄[{loop_count}] 命中 [{rule['template_name']}] "
                                  f"匹配={score:.2f}, 点击 ({final_x},{final_y})")
                        tap(self.device_id, final_x, final_y)
                        any_matched = True
                        rule["handled"] = True
                        
                        if 'on_match' in self.callbacks:
                            self.callbacks['on_match'](matches)
                        
                        # 执行子动作
                        for sub in rule["sub_actions"]:
                            self._check_interrupt_and_pause()
                            self._execute_action(sub)
                
                if not any_matched:
                    # 全部已处理 或 无匹配 → 默认点击 + 清除标记
                    if cfg.default_tap_x > 0 or cfg.default_tap_y > 0:
                        self._log(f"🔄[{loop_count}] 无匹配，默认点击 "
                                  f"({cfg.default_tap_x},{cfg.default_tap_y})")
                        tap(self.device_id, cfg.default_tap_x, cfg.default_tap_y)
                    else:
                        self._log(f"🔄[{loop_count}] 无匹配，无默认坐标，等待下一轮")
                    # 清除全部已处理标记，重新开始匹配
                    for rule in rules:
                        rule["handled"] = False
                
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
