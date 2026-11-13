"""技能 / 材料 / 图纸 的本地资料库。

和 paldex 一样的原则：命中就喂准确事实，没命中就什么都不给。
数据来自 tools/scrape_extra.py 生成的 data/*.json。
"""
from __future__ import annotations

import json
from pathlib import Path


def _read(path: Path, key: str) -> list[dict]:
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get(key)
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and item.get("name")]


def _read_dict(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


class Lore:
    def __init__(
        self,
        skills: list[dict] | None = None,
        materials: list[dict] | None = None,
        schematics: list[dict] | None = None,
        techs: list[dict] | None = None,
        teams: dict | None = None,
    ) -> None:
        self.skills = skills or []
        self.materials = materials or []
        self.schematics = schematics or []
        self.techs = techs or []
        self.teams = teams or {}

    @property
    def empty(self) -> bool:
        return not (self.skills or self.materials or self.schematics or self.techs or self.teams)

    @classmethod
    def load(cls, directory: str | Path) -> "Lore | None":
        base = Path(directory)
        lore = cls(
            skills=_read(base / "skills.json", "skills"),
            materials=_read(base / "materials.json", "materials"),
            schematics=_read(base / "schematics.json", "schematics"),
            techs=_read(base / "tech.json", "techs"),
            teams=_read_dict(base / "teams.json"),
        )
        return None if lore.empty else lore

    # ---------- 查询 ----------

    @staticmethod
    def _find(items: list[dict], text: str) -> dict | None:
        lowered = text.lower()
        best: tuple[int, dict] | None = None
        for item in items:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            # 技能名普遍两三个字，太短的名字容易误命中，要求至少两个字
            if len(name) < 2:
                continue
            if name in lowered and (best is None or len(name) > best[0]):
                best = (len(name), item)
        return best[1] if best else None

    @staticmethod
    def _render_skill(skill: dict) -> str:
        bits = [f"技能 {skill['name']}"]
        element = str(skill.get("element") or "").strip()
        kind = str(skill.get("type") or "").strip()
        if element or kind:
            bits.append(f"{element}属性{kind}")
        if skill.get("power") is not None:
            bits.append(f"威力{skill['power']}")
        if skill.get("cooldown") is not None:
            bits.append(f"冷却{skill['cooldown']}秒")
        desc = " ".join(str(skill.get("desc") or "").split())
        head = "，".join(bits)
        return f"{head}。{desc}" if desc else head

    @staticmethod
    def _render_material(material: dict) -> str:
        head = f"材料 {material['name']}"
        extras = []
        if material.get("weight") is not None:
            extras.append(f"重量{material['weight']}")
        if material.get("stack") is not None:
            extras.append(f"堆叠{material['stack']}")
        if extras:
            head += "（" + "，".join(extras) + "）"
        desc = " ".join(str(material.get("desc") or "").split())
        return f"{head}。{desc}" if desc else head

    @staticmethod
    def _render_schematic(schematic: dict) -> str:
        quality = str(schematic.get("quality") or "").strip()
        return f"图纸 {schematic['name']}（{quality}品质）"

    @staticmethod
    def _render_tech(tech: dict) -> str:
        head = f"科技 {tech['name']}"
        bits = []
        if tech.get("level"):
            bits.append(f"{tech['level']}级解锁")
        if tech.get("points"):
            bits.append(f"科技点{tech['points']}")
        if bits:
            head += "：" + "，".join(bits)
        materials = [m for m in (tech.get("materials") or []) if isinstance(m, dict) and m.get("name")]
        if materials:
            head += "；材料 " + "、".join(
                f"{m['name']}×{m['qty']}" if m.get("qty") else str(m["name"]) for m in materials[:6]
            )
        desc = " ".join(str(tech.get("desc") or "").split())
        return f"{head}。{desc}" if desc else head

    def top_skills(self, limit: int = 3) -> list[dict]:
        ranked = [skill for skill in self.skills if isinstance(skill.get("power"), int)]
        ranked.sort(key=lambda item: -int(item["power"]))
        return ranked[:limit]

    def team_lines(self, question: str) -> list[str]:
        """配队类问题：命中某只帕鲁就给它的词条+技能；问属性就给该系主C；否则给总则。"""
        if not self.teams:
            return []
        team_triggers = ("配队", "阵容", "队伍", "组队", "带谁", "带什么")
        build_triggers = ("配队", "词条", "怎么养", "怎么配", "配装", "带什么", "技能")
        if not any(word in question for word in team_triggers + build_triggers):
            return []

        lines: list[str] = []

        build = self._find_build(question)
        if build is not None and any(word in question for word in build_triggers):
            traits = "、".join(str(t) for t in (build.get("traits") or []))
            skills = "、".join(str(s) for s in (build.get("skills") or []))
            line = f"配队/词条参考：{build['pal']} — 词条 {traits}；技能 {skills}"
            note = str(build.get("note") or "").strip()
            if note:
                line += "。" + note
            lines.append(line)
            return lines

        elements = self.teams.get("elements") or {}
        for element in ("火", "冰", "暗", "龙", "土", "电", "水", "草", "无"):
            if f"{element}系" in question and element in elements:
                lines.append(f"{element}系主C：{'、'.join(elements[element])}")
                return lines

        if any(word in question for word in team_triggers):
            rules = self.teams.get("rules") or []
            if rules:
                lines.append(str(rules[0]))
            if len(rules) > 2:
                lines.append(str(rules[2]))
            summary = "；".join(
                f"{name} {'/'.join(picks[:2])}" for name, picks in list(elements.items())[:4]
            )
            if summary:
                lines.append("可选主C：" + summary)
        return lines

    def _find_build(self, text: str) -> dict | None:
        best: tuple[int, dict] | None = None
        for build in self.teams.get("builds") or []:
            name = str(build.get("pal") or "").strip()
            if len(name) < 2:
                continue
            if name in text and (best is None or len(name) > best[0]):
                best = (len(name), build)
        return best[1] if best else None

    def facts_for(self, question: str) -> str | None:
        lines: list[str] = []

        skill = self._find(self.skills, question)
        if skill is not None:
            lines.append(self._render_skill(skill))

        material = self._find(self.materials, question)
        if material is not None:
            lines.append(self._render_material(material))

        schematic = self._find(self.schematics, question)
        if schematic is not None:
            lines.append(self._render_schematic(schematic))

        tech = self._find(self.techs, question)
        if tech is not None:
            lines.append(self._render_tech(tech))

        lines.extend(self.team_lines(question))

        if "技能" in question and any(word in question for word in ("最高", "最强", "威力")):
            top = self.top_skills(3)
            if top:
                lines.append(
                    "威力最高：" + "、".join(f"{item['name']}{item['power']}" for item in top)
                )

        if not lines:
            return None
        return "（技能/材料库）\n" + "\n".join(f"- {line}" for line in lines)
