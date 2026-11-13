"""从 CSV 批量补数据：用 Excel 编辑，一行一只帕鲁。

格式：第一列表头必须是 `name`，其余列名对应字段 key。
空单元格会被跳过（不会把已有数据清空）。

    name,spawn,capture
    覆海龙,雪山地带,约 8%

导出的结果写进 data/overrides/<数据文件>.json，永不覆盖抓取数据。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

NAME_COLUMN = "name"


def read_csv(path: str | Path) -> list[dict]:
    """读 CSV，返回 [{name, field: value, ...}]；空值跳过。"""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"找不到 CSV：{file_path}")

    # Excel 导出的 UTF-8 CSV 常带 BOM
    with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV 没有表头")
        if NAME_COLUMN not in [name.strip() for name in reader.fieldnames]:
            raise ValueError(f"CSV 第一列必须是 {NAME_COLUMN}")

        rows: list[dict] = []
        for raw in reader:
            name = str(raw.get(NAME_COLUMN) or "").strip()
            if not name:
                continue
            row: dict = {"name": name}
            for key, value in raw.items():
                if key is None or key.strip() == NAME_COLUMN:
                    continue
                text = str(value or "").strip()
                if text:
                    row[key.strip()] = text
            if len(row) > 1:
                rows.append(row)
    return rows


def to_patches(rows: list[dict]) -> dict[str, dict]:
    """转成 overrides 的补丁格式（全部走 set）。"""
    patches: dict[str, dict] = {}
    for row in rows:
        name = row["name"]
        fields = {key: value for key, value in row.items() if key != "name"}
        if not fields:
            continue
        patches[name] = {"name": name, "set": fields}
    return patches


def write_overrides(directory: str | Path, data_file: str, patches: dict[str, dict]) -> Path:
    """把补丁合并进 data/overrides/<data_file>，同名条目以新值为准。"""
    base = Path(directory)
    base.mkdir(parents=True, exist_ok=True)
    target = base / data_file

    existing: dict[str, dict] = {}
    if target.is_file():
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        for item in (raw.get("items") or []) if isinstance(raw, dict) else []:
            if isinstance(item, dict) and item.get("name"):
                existing[str(item["name"])] = item

    for name, patch in patches.items():
        old = existing.get(name, {"name": name})
        merged = {**old, **patch}
        merged["set"] = {**(old.get("set") or {}), **(patch.get("set") or {})}
        existing[name] = merged

    payload = {
        "note": "由 CSV 导入生成；更新抓取数据不会覆盖这里",
        "items": list(existing.values()),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
