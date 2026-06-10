import json
import os
import shutil
import uuid
from typing import List, Dict, Any

class ActionNode:
    """脚本动作节点，代表脚本流水线中的一个特定步骤。"""
    
    def __init__(self, action_type: str, params: Dict[str, Any] = None, action_id: str = None, comment: str = ""):
        # 使用 UUID 以便在 UI 列表中进行拖拽、删除、参数编辑等操作时的精确定位
        self.id = action_id or str(uuid.uuid4())
        self.type = action_type  # 例如: 'tap', 'sleep', 'find_and_tap', 'wait_image'
        self.params = params or {}
        self.comment = comment  # 可选的用户备注，方便阅读和管理复杂脚本
        
    def to_dict(self) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "type": self.type,
            "params": self.params
        }
        if self.comment:  # 仅在有备注时输出，保持 JSON 简洁
            d["comment"] = self.comment
        return d
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ActionNode':
        if not isinstance(data, dict):
            raise ValueError(f"动作节点数据格式错误，应为对象而非 {type(data).__name__}")
        params = data.get("params", {})
        if not isinstance(params, dict):
            params = {}
        node = cls(
            action_type=str(data.get("type", "unknown")),
            params=params,
            action_id=data.get("id"),
            comment=data.get("comment", "")
        )
        return node

class ScriptConfig:
    """脚本全局配置，含顺序执行和循环执行两种模式所需参数。"""
    
    def __init__(self, popup_guard: bool = True, guard_dir: str = "popups",
                 guard_trigger_fails: int = 3, resolution: str = "",
                 check_resolution: bool = True,
                 # 循环执行专用参数
                 scan_interval: float = 1.0,
                 max_loops: int = 0):
        self.popup_guard = popup_guard         # 是否开启全局弹窗守卫
        self.guard_dir = guard_dir             # 弹窗关闭按钮图库目录
        self.guard_trigger_fails = guard_trigger_fails  # 主线找图连续失败几次后触发守卫扫描
        self.resolution = resolution           # 脚本适配的分辨率，如 "540x960"
        self.check_resolution = check_resolution  # 启动时是否检测分辨率一致性
        # 循环模式参数
        self.scan_interval = scan_interval     # 每轮截图间隔（秒）
        self.max_loops = max_loops             # 最大循环次数（0=无限）
        
    def to_dict(self) -> Dict[str, Any]:
        return {
            "popup_guard": self.popup_guard,
            "guard_dir": self.guard_dir,
            "guard_trigger_fails": self.guard_trigger_fails,
            "resolution": self.resolution,
            "check_resolution": self.check_resolution,
            "scan_interval": self.scan_interval,
            "max_loops": self.max_loops
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ScriptConfig':
        if not isinstance(data, dict):
            data = {}

        def _num(key, default, cast):
            try:
                return cast(data.get(key, default))
            except (TypeError, ValueError):
                return default

        # guard_dir 边界校验：只允许单层目录名，拒绝路径分隔符与 ".."（防目录遍历）
        raw = data.get("guard_dir", "popups") or "popups"
        guard_dir = os.path.basename(str(raw).strip().strip("/\\")) or "popups"
        if guard_dir == "..":
            guard_dir = "popups"

        return cls(
            popup_guard=bool(data.get("popup_guard", True)),
            guard_dir=guard_dir,
            guard_trigger_fails=_num("guard_trigger_fails", 3, int),
            resolution=data.get("resolution", ""),
            check_resolution=bool(data.get("check_resolution", True)),
            scan_interval=_num("scan_interval", 1.0, float),
            max_loops=_num("max_loops", 0, int)
        )

class ScriptModel:
    """完整的脚本模型，支持解析、序列化、修改以及持久化到 JSON 文件。"""
    
    # 脚本项目的标准目录结构常量
    SCRIPTS_ROOT = "Scripts"         # 所有脚本项目的根目录
    SCRIPT_FILENAME = "script.json"  # 每个项目中的脚本文件名
    TEMP_DIR_NAME = "Temp"           # 录制临时截图子目录
    PICTURES_DIR_NAME = "Pictures"   # 模板图片子目录
    
    def __init__(self, name: str = "新预设脚本", version: str = "1.0"):
        self.name = name
        self.version = version
        self.config = ScriptConfig()
        self.actions: List[ActionNode] = []
        self.project_dir = None  # 项目文件夹绝对路径，如 Scripts/主线任务/
        
    @property
    def temp_dir(self) -> str:
        """录制临时截图目录"""
        if self.project_dir:
            return os.path.join(self.project_dir, self.TEMP_DIR_NAME)
        return "Temp"
    
    @property
    def pictures_dir(self) -> str:
        """模板图片目录"""
        if self.project_dir:
            return os.path.join(self.project_dir, self.PICTURES_DIR_NAME)
        return "Pictures"
    
    @property
    def filepath(self) -> str:
        """脚本 JSON 文件的完整路径"""
        if self.project_dir:
            return os.path.join(self.project_dir, self.SCRIPT_FILENAME)
        return None
        
    def add_action(self, action: ActionNode):
        self.actions.append(action)
        
    def remove_action(self, action_id: str):
        self.actions = [a for a in self.actions if a.id != action_id]
        
    def move_action(self, from_index: int, to_index: int):
        """支持 UI 层的拖拽排序。"""
        if 0 <= from_index < len(self.actions) and 0 <= to_index < len(self.actions):
            action = self.actions.pop(from_index)
            self.actions.insert(to_index, action)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "script_name": self.name,
            "version": self.version,
            "config": self.config.to_dict(),
            "actions": [a.to_dict() for a in self.actions]
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ScriptModel':
        if not isinstance(data, dict):
            raise ValueError("脚本数据格式错误：根对象应为 JSON 对象")
        model = cls(
            name=data.get("script_name", "未知脚本"),
            version=data.get("version", "1.0")
        )
        if isinstance(data.get("config"), dict):
            model.config = ScriptConfig.from_dict(data["config"])
        actions_data = data.get("actions", [])
        if isinstance(actions_data, list):
            model.actions = [ActionNode.from_dict(a) for a in actions_data if isinstance(a, dict)]
        return model
        
    def internalize_image(self, external_path: str) -> str:
        """
        将外部图片复制到项目 Pictures/ 目录，返回文件名（相对路径）。
        如果文件已在项目内则直接返回文件名，不重复复制。
        
        Args:
            external_path: 外部图片的绝对路径
        Returns:
            str: 复制后的文件名（如 "进入副本@540x960.png"）
        """
        if not self.project_dir:
            raise ValueError("未设置项目目录，无法内化图片")
        
        # 标准化路径以便比较
        abs_path = os.path.abspath(external_path)
        pics_abs = os.path.abspath(self.pictures_dir)
        
        # 已在项目 Pictures/ 下 → 直接返回文件名
        if abs_path.startswith(pics_abs + os.sep):
            return os.path.basename(abs_path)
        
        # 仅文件名（无目录） → 可能已经是相对路径引用，检查文件是否存在
        filename = os.path.basename(abs_path)
        dest = os.path.join(self.pictures_dir, filename)
        
        if not os.path.exists(abs_path):
            # 源文件不存在，返回原文件名（可能已经内化）
            return filename
        
        # 复制到项目 Pictures/ 目录（同名跳过，除非内容不同）
        os.makedirs(self.pictures_dir, exist_ok=True)
        if not os.path.exists(dest):
            shutil.copy2(abs_path, dest)
            # 新文件入库，清除该目录的模板缓存，确保后续加载能命中新文件
            try:
                import image_engine
                image_engine.clear_cache(self.pictures_dir)
            except Exception:
                import logging
                logging.getLogger(__name__).debug("内化图片后清理模板缓存失败", exc_info=True)
        
        return filename
    
    def _internalize_template_value(self, template: str) -> str:
        """对单个模板路径执行内化，返回内化后的文件名；非外部绝对路径原样返回。"""
        if not template or not os.path.isabs(template):
            return template
        pics_abs = os.path.abspath(self.pictures_dir)
        abs_template = os.path.abspath(template)
        # 已在项目内的绝对路径也需简化为文件名；项目外的绝对路径需复制进来
        if abs_template.startswith(pics_abs + os.sep) or not abs_template.startswith(os.path.abspath(self.project_dir)):
            return self.internalize_image(template)
        return template

    def _internalize_params(self, action_type, params):
        """内化单个动作 params 中引用的所有模板（含 multi_match 的 templates 与嵌套 sub_actions）。"""
        if not isinstance(params, dict):
            return
        if action_type in ("find_and_tap", "wait_image"):
            params["template"] = self._internalize_template_value(params.get("template", ""))
        elif action_type == "multi_match":
            for tpl_info in params.get("templates", []):
                if isinstance(tpl_info, dict):
                    tpl_info["template"] = self._internalize_template_value(tpl_info.get("template", ""))
            for sub in params.get("sub_actions", []):
                if isinstance(sub, dict):
                    self._internalize_params(sub.get("type"), sub.get("params", {}))

    def internalize_all_images(self):
        """
        遍历所有 actions，将动作引用的外部绝对路径图片自动内化为项目内相对路径
        （仅文件名）。覆盖 find_and_tap / wait_image 的 template，以及 multi_match
        的 templates 列表与嵌套 sub_actions。
        """
        if not self.project_dir:
            return

        for action in self.actions:
            self._internalize_params(action.type, action.params)

    def save(self):
        """保存到当前项目目录，自动创建所需子目录结构并内化外部图片引用。"""
        if not self.project_dir:
            raise ValueError("未设置项目目录，请先设置 project_dir")
        # 确保项目目录及子目录存在
        os.makedirs(self.project_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)
        os.makedirs(self.pictures_dir, exist_ok=True)
        # 保存前自动内化外部图片路径
        self.internalize_all_images()
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=4)
            
    @classmethod
    def load_from_project(cls, project_dir: str) -> 'ScriptModel':
        """从项目目录加载脚本模型。"""
        script_path = os.path.join(project_dir, cls.SCRIPT_FILENAME)
        if not os.path.exists(script_path):
            model = cls()
            model.project_dir = project_dir
            return model
            
        with open(script_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            model = cls.from_dict(data)
            model.project_dir = project_dir
            return model
    
    @classmethod
    def is_safe_project_name(cls, name: str) -> bool:
        """校验脚本项目名不会越出 Scripts/ 根目录（防目录遍历）。"""
        if not name:
            return False
        scripts_root = os.path.abspath(cls.SCRIPTS_ROOT)
        target = os.path.abspath(os.path.join(scripts_root, name))
        try:
            return os.path.commonpath([scripts_root, target]) == scripts_root and target != scripts_root
        except ValueError:
            # 不同盘符（如传入绝对路径 C:\...）→ commonpath 抛错 → 判为不安全
            return False

    @classmethod
    def list_projects(cls) -> List[str]:
        """扫描 Scripts/ 目录下的所有脚本项目名称（已缓存友好）。"""
        root = cls.SCRIPTS_ROOT
        if not os.path.exists(root):
            return []
        projects = []
        for entry in sorted(os.listdir(root)):
            project_path = os.path.join(root, entry)
            script_file = os.path.join(project_path, cls.SCRIPT_FILENAME)
            if os.path.isdir(project_path) and os.path.exists(script_file):
                projects.append(entry)
        return projects
    
    @classmethod
    def import_project(cls, source_dir: str, target_name: str = None) -> 'ScriptModel':
        """
        导入脚本项目：整体复制到 Scripts/ 目录，并内化所有外部图片引用。
        
        Args:
            source_dir: 源项目目录的绝对路径
            target_name: 目标项目名称，默认使用源目录名
        Returns:
            ScriptModel: 导入后的脚本模型
        """
        if target_name is None:
            target_name = os.path.basename(source_dir.rstrip(os.sep))

        # 路径安全：只取末段名并校验，拒绝越出 Scripts/ 的目录遍历
        target_name = os.path.basename(target_name.rstrip("/\\")) or target_name
        if not cls.is_safe_project_name(target_name):
            raise ValueError(f"非法的导入项目名（疑似路径遍历）: {target_name}")

        target_dir = os.path.join(cls.SCRIPTS_ROOT, target_name)
        
        # 防止覆盖已有项目：自动追加编号
        if os.path.exists(target_dir):
            n = 1
            while os.path.exists(f"{target_dir}_{n}"):
                n += 1
            target_dir = f"{target_dir}_{n}"
            target_name = os.path.basename(target_dir)
        
        # 整体复制项目目录（symlinks=True：保留符号链接本体而非解引用，
        # 防止恶意链接指向项目外文件被复制进来）
        shutil.copytree(source_dir, target_dir, symlinks=True)
        
        # 加载并内化所有外部图片引用
        model = cls.load_from_project(target_dir)
        model.internalize_all_images()
        model.save()
        
        return model
