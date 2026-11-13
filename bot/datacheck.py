"""数据自检：结构、必填、重复、别名冲突、引用完整性。

`python run.py data check` 会跑这里，分三级：
  error   → 核心数据坏了，拒绝启动（例如 paldex 解析失败）
  warning → 能跑，但结果可能不准（例如某只帕鲁属性是"未知"）
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

ELEMENTS = {"火", "冰", "暗", "龙", "地", "雷", "水", "草", "无"}


@dataclass
class Issue:
    level: str  # error | warning
    file: str
    message: str

    def __str__(self) -> str:
        tag = "错误" if self.level == "error" else "警告"
        return f"[{tag}] {self.file}: {self.message}"


def _read(path: Path) -> tuple[object | None, Issue | None]:
    if not path.is_file():
        return None, Issue("error", path.name, "文件不存在")
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, Issue("error", path.name, f"解析失败：{exc}")


def _list_of_dicts(raw: object, key: str) -> list[dict] | None:
    if not isinstance(raw, dict):
        return None
    items = raw.get(key)
    if not isinstance(items, list):
        return None
    return [item for item in items if isinstance(item, dict)]


def check_paldex(data_dir: Path) -> tuple[list[Issue], set[str]]:
    issues: list[Issue] = []
    raw, error = _read(data_dir / "paldex.json")
    if error:
        return [error], set()

    pals = _list_of_dicts(raw, "pals")
    if not pals:
        return [Issue("error", "paldex.json", "pals 不是非空列表")], set()

    names: set[str] = set()
    aliases: dict[str, str] = {}
    for pal in pals:
        name = str(pal.get("name") or "").strip()
        if not name:
            issues.append(Issue("error", "paldex.json", "有条目缺少 name"))
            continue
        if name in names:
            issues.append(Issue("error", "paldex.json", f"帕鲁重名：{name}"))
        names.add(name)

        for alias in [name, *(pal.get("aliases") or [])]:
            alias = str(alias or "").strip().lower()
            if not alias:
                continue
            # "no.157" 这类编号别名会被本体和亚种共用，不算冲突
            if re.fullmatch(r"no\.\d+", alias):
                continue
            owner = aliases.get(alias)
            if owner is not None and owner != name:
                issues.append(
                    Issue("warning", "paldex.json", f"别名冲突：「{alias}」同时指向 {owner} 和 {name}")
                )
            aliases.setdefault(alias, name)

        stats = pal.get("stats") or {}
        for key, value in stats.items():
            if not isinstance(value, int):
                issues.append(
                    Issue("warning", "paldex.json", f"{name} 的 {key} 不是整数：{value!r}")
                )

        elements = [str(e) for e in (pal.get("elements") or [])]
        if not elements or all(e in ("", "未知") for e in elements):
            issues.append(Issue("warning", "paldex.json", f"{name} 属性未知（站点没填完）"))

    if len(pals) < 250:
        issues.append(Issue("warning", "paldex.json", f"帕鲁数量偏少：{len(pals)}（预期 290+）"))
    return issues, names


def check_named_list(
    data_dir: Path, filename: str, key: str, aggregate: bool = False
) -> tuple[list[Issue], set[str]]:
    issues: list[Issue] = []
    raw, error = _read(data_dir / filename)
    if error:
        return [error], set()
    items = _list_of_dicts(raw, key)
    if not items:
        return [Issue("warning", filename, f"{key} 不是非空列表")], set()

    names: set[str] = set()
    duplicates: list[str] = []
    for item in items:
        name = str(item.get("name") or "").strip()
        if not name:
            issues.append(Issue("warning", filename, "有条目缺少 name"))
            continue
        if name in names:
            duplicates.append(name)
        names.add(name)
    if duplicates:
        if aggregate:
            issues.append(
                Issue(
                    "warning",
                    filename,
                    f"有 {len(duplicates)} 个重名（多为跨分类重复，查询时取第一条）："
                    + "、".join(duplicates[:5]),
                )
            )
        else:
            for name in duplicates:
                issues.append(Issue("warning", filename, f"重名：{name}"))
    return issues, names


def check_tech_refs(data_dir: Path, known: set[str]) -> list[Issue]:
    """科技里的材料名，至少要能在材料/物品里找到。"""
    issues: list[Issue] = []
    raw, error = _read(data_dir / "tech.json")
    if error:
        return [error]
    techs = _list_of_dicts(raw, "techs") or []
    missing: dict[str, int] = {}
    for tech in techs:
        for material in tech.get("materials") or []:
            if not isinstance(material, dict):
                continue
            name = str(material.get("name") or "").strip()
            if name and name not in known:
                missing[name] = missing.get(name, 0) + 1
    for name, count in sorted(missing.items(), key=lambda kv: -kv[1])[:8]:
        issues.append(
            Issue("warning", "tech.json", f"材料「{name}」在材料库里找不到（被 {count} 个科技引用）")
        )
    return issues


def check_teams(data_dir: Path, known: set[str]) -> list[Issue]:
    issues: list[Issue] = []
    raw, error = _read(data_dir / "teams.json")
    if error:
        return [error]
    if not isinstance(raw, dict):
        return [Issue("warning", "teams.json", "顶层不是对象")]

    for build in raw.get("builds") or []:
        if not isinstance(build, dict):
            continue
        name = str(build.get("pal") or "").strip()
        if name and name not in known:
            issues.append(Issue("warning", "teams.json", f"配队里的帕鲁不存在：{name}"))

    for element in (raw.get("elements") or {}):
        if element not in ELEMENTS:
            issues.append(Issue("warning", "teams.json", f"未知属性分类：{element}"))
    return issues


def check_partner_skills(data_dir: Path, known: set[str]) -> list[Issue]:
    issues: list[Issue] = []
    raw, error = _read(data_dir / "partner_skills.json")
    if error:
        return [error]
    for row in (raw.get("pals") or []) if isinstance(raw, dict) else []:
        if isinstance(row, dict) and row.get("name") not in known:
            issues.append(Issue("warning", "partner_skills.json", f"不认识的帕鲁：{row.get('name')}"))
    return issues


def check_elements(data_dir: Path) -> list[Issue]:
    issues: list[Issue] = []
    raw, error = _read(data_dir / "elements.json")
    if error:
        return [error]
    chain = raw.get("chain") if isinstance(raw, dict) else None
    if not isinstance(chain, dict):
        return [Issue("error", "elements.json", "缺少 chain")]
    for attacker, defenders in chain.items():
        if attacker not in ELEMENTS:
            issues.append(Issue("warning", "elements.json", f"未知属性：{attacker}"))
        for defender in defenders or []:
            if defender not in ELEMENTS:
                issues.append(Issue("warning", "elements.json", f"未知属性：{defender}"))
    return issues


def check_all(data_dir: str | Path) -> list[Issue]:
    base = Path(data_dir)
    issues: list[Issue] = []

    pal_issues, pal_names = check_paldex(base)
    issues.extend(pal_issues)

    skill_issues, skill_names = check_named_list(base, "skills.json", "skills", aggregate=True)
    issues.extend(skill_issues)
    material_issues, material_names = check_named_list(
        base, "materials.json", "materials", aggregate=True
    )
    issues.extend(material_issues)
    item_issues, item_names = check_named_list(base, "items.json", "items", aggregate=True)
    issues.extend(item_issues)
    issues.extend(check_named_list(base, "schematics.json", "schematics", aggregate=True)[0])

    issues.extend(check_tech_refs(base, material_names | item_names))
    issues.extend(check_teams(base, pal_names))
    issues.extend(check_partner_skills(base, pal_names))
    issues.extend(check_elements(base))
    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(issue.level == "error" for issue in issues)


def format_report(issues: list[Issue]) -> str:
    if not issues:
        return "数据检查通过，没有发现问题。"
    errors = [item for item in issues if item.level == "error"]
    warnings = [item for item in issues if item.level == "warning"]
    lines = [f"共 {len(errors)} 个错误、{len(warnings)} 个警告："]
    lines.extend(str(item) for item in errors[:20])
    lines.extend(str(item) for item in warnings[:20])
    if len(warnings) > 20:
        lines.append(f"…还有 {len(warnings) - 20} 条警告")
    return "\n".join(lines)
