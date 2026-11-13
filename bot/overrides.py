"""手工补丁层：抓取数据会被 update-data 覆盖，人工补充不能丢。

约定：`data/overrides/<与数据文件同名>.json`，两种写法都支持：

    {"items": [{"name": "覆海龙", "set": {"spawn": "雪山地带"}}]}

    {"覆海龙": {"set": {"spawn": "雪山地带"}}}

补丁里的 `set` 直接覆盖同名字段，`add` 追加（列表则拼接，字典则合并）。
补丁里出现、但原数据没有的名字，会作为新条目追加。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path


def load_patches(directory: str | Path, filename: str) -> dict[str, dict]:
    """读取某个数据文件对应的补丁；没有就返回空字典。"""
    path = Path(directory) / filename
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    patches: dict[str, dict] = {}
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        for item in raw["items"]:
            if isinstance(item, dict) and item.get("name"):
                patches[str(item["name"])] = item
    elif isinstance(raw, dict):
        for name, patch in raw.items():
            if isinstance(patch, dict):
                patches[str(name)] = {"name": name, **patch}
    return patches


def apply_patch(item: dict, patch: dict) -> dict:
    """把一条补丁应用到一条数据上，返回新对象。"""
    merged = copy.deepcopy(item)
    for key, value in (patch.get("set") or {}).items():
        merged[key] = copy.deepcopy(value)
    for key, value in (patch.get("add") or {}).items():
        current = merged.get(key)
        if isinstance(current, list) and isinstance(value, list):
            merged[key] = current + [v for v in value if v not in current]
        elif isinstance(current, dict) and isinstance(value, dict):
            merged[key] = {**current, **value}
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def merge_items(items: list[dict], patches: dict[str, dict]) -> list[dict]:
    """把补丁合并进数据列表；补丁里独有的名字作为新条目追加。"""
    if not patches:
        return items

    used: set[str] = set()
    merged: list[dict] = []
    for item in items:
        name = str(item.get("name") or "")
        patch = patches.get(name)
        if patch is None:
            merged.append(copy.deepcopy(item))
            continue
        used.add(name)
        new_item = apply_patch(item, patch)
        new_item["name"] = name
        merged.append(new_item)

    for name, patch in patches.items():
        if name in used:
            continue
        new_item = apply_patch({"name": name}, patch)
        new_item["name"] = name
        merged.append(new_item)
    return merged
