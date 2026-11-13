"""字段定义：让"抓取之外补的字段"知道怎么显示、什么时候显示。

为什么需要：
  paldex 只抓了官方页面上有的字段。你想补「刷新位置」「捕获率」这类信息时，
  程序得知道这个字段叫什么、玩家问到相关问题时才把它塞进提示词——
  否则补了也不会被用上，或者每条消息都带上、白烧 token。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FieldSpec:
    key: str
    label: str
    keywords: list[str] = field(default_factory=list)


def load(path: str | Path) -> dict[str, FieldSpec]:
    file_path = Path(path)
    if not file_path.is_file():
        return {}
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    fields = raw.get("fields") if isinstance(raw, dict) else None
    if not isinstance(fields, dict):
        return {}

    specs: dict[str, FieldSpec] = {}
    for key, value in fields.items():
        if not isinstance(value, dict):
            continue
        specs[str(key)] = FieldSpec(
            key=str(key),
            label=str(value.get("label") or key),
            keywords=[str(word) for word in (value.get("keywords") or [])],
        )
    return specs


def _format(value) -> str:
    if isinstance(value, list):
        return "、".join(str(item) for item in value)
    if isinstance(value, dict):
        return "，".join(f"{key}={val}" for key, val in value.items())
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def render(extra: dict, question: str, specs: dict[str, FieldSpec], limit: int = 3) -> list[str]:
    """挑出与问题相关、且确实有值的补充字段。"""
    if not extra or not specs:
        return []

    lines: list[str] = []
    for key, spec in specs.items():
        if key not in extra:
            continue
        value = extra[key]
        if value in (None, "", [], {}):
            continue
        if spec.keywords and not any(word in question for word in spec.keywords):
            continue
        lines.append(f"{spec.label} {_format(value)}")
        if len(lines) >= limit:
            break
    return lines
