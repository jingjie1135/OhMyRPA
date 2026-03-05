"""
模板元数据管理器：读写 Pictures/meta.json，存储每个模板的偏移量等元数据。

meta.json 结构示例：
{
    "进入副本@540x960.png": {
        "offset_x": 10,
        "offset_y": 50,
        "description": ""
    }
}
"""

import os
import json
import threading

# 文件级锁，防止多线程同时读写
_lock = threading.Lock()

# 内存缓存：{meta_path: {filename: {...}}}
_cache = {}


def _meta_path(pictures_dir: str) -> str:
    """获取 meta.json 的完整路径"""
    return os.path.join(pictures_dir, "meta.json")


def load(pictures_dir: str) -> dict:
    """
    加载 meta.json，优先返回缓存。
    若文件不存在则返回空字典。
    """
    path = _meta_path(pictures_dir)
    with _lock:
        # 缓存命中
        if path in _cache:
            return _cache[path]
        # 从磁盘读取
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError):
                data = {}
        else:
            data = {}
        _cache[path] = data
        return data


def save(pictures_dir: str):
    """将当前缓存数据写入 meta.json"""
    path = _meta_path(pictures_dir)
    with _lock:
        data = _cache.get(path, {})
        os.makedirs(pictures_dir, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def get(pictures_dir: str, template_filename: str) -> dict:
    """
    获取单个模板的元数据。
    template_filename 应为文件名（如 "进入副本@540x960.png"）。
    返回 {"offset_x": 0, "offset_y": 0, "description": ""} 等。
    """
    all_meta = load(pictures_dir)
    return all_meta.get(template_filename, {})


def set_meta(pictures_dir: str, template_filename: str,
             offset_x: int = None, offset_y: int = None,
             description: str = None, **kwargs):
    """
    设置模板元数据并自动持久化。
    仅更新传入的非 None 字段，不覆盖现有其他字段。
    """
    all_meta = load(pictures_dir)
    entry = all_meta.get(template_filename, {})
    
    if offset_x is not None:
        entry["offset_x"] = offset_x
    if offset_y is not None:
        entry["offset_y"] = offset_y
    if description is not None:
        entry["description"] = description
    # 支持扩展字段
    for k, v in kwargs.items():
        if v is not None:
            entry[k] = v
    
    all_meta[template_filename] = entry
    _cache[_meta_path(pictures_dir)] = all_meta
    save(pictures_dir)


def remove(pictures_dir: str, template_filename: str):
    """删除某个模板的元数据"""
    all_meta = load(pictures_dir)
    if template_filename in all_meta:
        del all_meta[template_filename]
        _cache[_meta_path(pictures_dir)] = all_meta
        save(pictures_dir)


def invalidate_cache(pictures_dir: str = None):
    """清除缓存（目录改变或手动编辑 meta.json 后调用）"""
    with _lock:
        if pictures_dir:
            path = _meta_path(pictures_dir)
            _cache.pop(path, None)
        else:
            _cache.clear()
