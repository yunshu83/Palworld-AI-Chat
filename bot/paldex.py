"""本地帕鲁资料库。

设计原则：数据归数据，语气归语气。
  * 命中资料库 → 把**准确的几行**塞进提示词，模型只负责用小鱼的口吻说出来；
  * 没命中 → 什么都不塞，模型按"不许编数值"的规则糊弄过去。

这样既不会瞎编，又保住人设。数据文件是纯 JSON，可以手工改、也可以脚本生成。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import fields, partner
from .overrides import load_patches, merge_items

# 工作适应性的内部键 → 中文说法（用户问的和显示的都走这张表）
WORK_LABELS = {
    "kindling": "生火",
    "watering": "浇水",
    "planting": "播种",
    "generating_electricity": "发电",
    "handiwork": "手工",
    "gathering": "采集",
    "lumbering": "砍伐",
    "mining": "采掘",
    "medicine_production": "制药",
    "cooling": "冷却",
    "transporting": "搬运",
    "farming": "牧场",
}

_LABEL_TO_KEY = {label: key for key, label in WORK_LABELS.items()}
# 玩家常用的别名 → 内部键
_EXTRA_LABELS = {
    "挖矿": "mining",
    "采矿": "mining",
    "砍树": "lumbering",
    "伐木": "lumbering",
    "运输": "transporting",
    "手工制作": "handiwork",
    "制作": "handiwork",
    "种地": "planting",
    "农活": "farming",
    "发电量": "generating_electricity",
    "火": "kindling",
}


def _load_drops(value) -> list[dict]:
    """兼容两种写法：["骨头"] 或 [{"name": "骨头", "qty": "3–5", "rate": "100%"}]。"""
    out: list[dict] = []
    for item in value or []:
        if isinstance(item, str) and item.strip():
            out.append({"name": item.strip(), "qty": "", "rate": ""})
        elif isinstance(item, dict) and item.get("name"):
            out.append(
                {
                    "name": str(item["name"]),
                    "qty": str(item.get("qty") or ""),
                    "rate": str(item.get("rate") or ""),
                }
            )
    return out


def _load_list(value) -> list[dict]:
    return [dict(item) for item in (value or []) if isinstance(item, dict)]


@dataclass
class Pal:
    name: str
    aliases: list[str] = field(default_factory=list)
    elements: list[str] = field(default_factory=list)
    work: dict[str, int] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=dict)
    movement: dict[str, int] = field(default_factory=dict)
    stats80: dict[str, str] = field(default_factory=dict)
    drops: list[dict] = field(default_factory=list)
    active_skills: list[dict] = field(default_factory=list)
    passive_skills: list[dict] = field(default_factory=list)
    partner_skill: dict = field(default_factory=dict)
    note: str = ""
    # 抓取之外人工补充的字段（在 data/overrides/paldex.json 里写），原样保留
    extra: dict = field(default_factory=dict)


# load() 认识的字段；其余键收进 extra，不再丢弃
_KNOWN_FIELDS = {
    "name",
    "aliases",
    "elements",
    "work",
    "stats",
    "movement",
    "stats80",
    "drops",
    "active_skills",
    "passive_skills",
    "partner_skill",
    "note",
}


class Paldex:
    def __init__(
        self,
        pals: list[Pal],
        version: str = "",
        source: str = "",
        field_specs: dict | None = None,
    ) -> None:
        self.pals = pals
        self.version = version
        self.source = source
        self.field_specs = field_specs or {}
        self._by_alias: dict[str, Pal] = {}
        for pal in pals:
            for alias in [pal.name, *pal.aliases]:
                alias = (alias or "").strip().lower()
                if alias:
                    self._by_alias[alias] = pal

    # ---------- 载入 ----------

    @classmethod
    def load(cls, path: str | Path, overrides: dict[str, dict] | None = None) -> "Paldex | None":
        data_path = Path(path)
        if not data_path.is_file():
            return None
        raw = json.loads(data_path.read_text(encoding="utf-8"))

        items = raw.get("pals") or []
        if overrides is None:
            overrides = load_patches(data_path.parent / "overrides", "paldex.json")
        if overrides:
            items = merge_items(items, overrides)

        pals = []
        for item in items:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            pals.append(
                Pal(
                    name=str(item["name"]),
                    aliases=[str(a) for a in item.get("aliases") or []],
                    elements=[str(e) for e in item.get("elements") or []],
                    work={str(k): int(v) for k, v in (item.get("work") or {}).items()},
                    stats={str(k): int(v) for k, v in (item.get("stats") or {}).items()},
                    movement={str(k): int(v) for k, v in (item.get("movement") or {}).items()},
                    stats80={str(k): str(v) for k, v in (item.get("stats80") or {}).items()},
                    drops=_load_drops(item.get("drops")),
                    active_skills=_load_list(item.get("active_skills")),
                    passive_skills=_load_list(item.get("passive_skills")),
                    partner_skill=dict(item.get("partner_skill") or {}),
                    note=str(item.get("note") or ""),
                    extra={k: v for k, v in item.items() if k not in _KNOWN_FIELDS},
                )
            )
        return cls(
            pals,
            version=str(raw.get("version") or ""),
            source=str(raw.get("source") or ""),
            field_specs=fields.load(data_path.parent / "fields.json"),
        )

    # ---------- 查询 ----------

    def find_pal(self, text: str) -> Pal | None:
        found = self.find_pals(text, limit=1)
        return found[0] if found else None

    def find_pals(self, text: str, limit: int = 3) -> list[Pal]:
        """返回消息里提到的所有帕鲁（按匹配长度降序，去重）。

        一句话里提到两三只时全都给资料，免得模型只认识其中一只、
        剩下几只靠猜。
        """
        lowered = text.lower()
        hits: list[tuple[int, Pal]] = []
        seen: set[int] = set()
        for alias, pal in self._by_alias.items():
            if not alias or alias not in lowered:
                continue
            key = id(pal)
            if key in seen:
                continue
            seen.add(key)
            hits.append((len(alias), pal))
        hits.sort(key=lambda item: -item[0])
        return [pal for _, pal in hits[:limit]]

    def detect_work(self, text: str) -> str | None:
        for label, key in _LABEL_TO_KEY.items():
            if label in text:
                return key
        for label, key in _EXTRA_LABELS.items():
            if label in text:
                return key
        return None

    def work_top(self, key: str, limit: int = 3) -> list[tuple[Pal, int]]:
        ranked = [(pal, pal.work.get(key, 0)) for pal in self.pals]
        ranked = [item for item in ranked if item[1] > 0]
        ranked.sort(key=lambda item: (-item[1], item[0].name))
        return ranked[:limit]

    @staticmethod
    def partner_role(pal: Pal) -> str:
        """伙伴技能分类，统一走 bot/partner.py（那里规则更全）。"""
        return partner.classify(str(pal.partner_skill.get("desc") or ""))

    def team_materials(self, question: str, elements=None) -> str | None:
        """配队问题：先按数据筛出主C/前排/辅助候选，再交给模型组合。

        这一步是"检索优先"的核心——模型看到的只能是真实存在的帕鲁，
        而不是先自由发挥、事后被校验拦下。
        问「打雷系」时，会先按克制表把属性换成"地系"，再去筛人。
        """
        team_intent = any(
            word in question
            for word in ("配队", "阵容", "队伍", "组队", "搭配", "带谁", "前排", "主C", "辅助位", "哪几个帕鲁")
        )
        # "配个队""组一队"这类中间夹字的说法也算
        if "配" in question and "队" in question:
            team_intent = True
        if not team_intent:
            return None

        target = ""
        match = re.search(r"打(?:败|赢)?([火冰暗龙地雷水草无])", question)
        if match:
            target = match.group(1)

        element = ""
        note = ""
        if target and elements is not None:
            attackers = elements.best_attackers(target)
            if attackers:
                element = attackers[0]
                note = f"对手是{target}系，应选{'、'.join(x + '系' for x in attackers)}（克制 2 倍）。"

        if not element:
            for candidate in ("火", "冰", "暗", "龙", "土", "电", "雷", "水", "草", "无"):
                if f"{candidate}系" in question or f"{candidate}属性" in question:
                    element = elements.normalize(candidate) if elements is not None else candidate
                    break

        # 只拿"数据可信"的帕鲁：有数值、且属性不是"未知"
        # （枯星龙那种站点没填完的，200/200/200 是占位数值，推荐出去会坑人）
        pool = [
            pal
            for pal in self.pals
            if pal.stats and any(element and element != "未知" for element in pal.elements)
        ]
        if element:
            filtered = [pal for pal in pool if element in pal.elements]
            if len(filtered) >= 3:
                pool = filtered
        if len(pool) < 3:
            return None

        def label(pal: Pal, key: str, with_hp: bool = False) -> str:
            value = pal.stats.get(key, 0)
            partner = str(pal.partner_skill.get("name") or "").strip()
            suffix = f"〔{partner}〕" if partner and partner not in ("-", "无") else ""
            if with_hp:
                hp = pal.stats.get("hp", 0)
                return f"{pal.name}(防{value} 血{hp}){suffix}"
            return f"{pal.name}({value}){suffix}"

        front = sorted(pool, key=lambda pal: -pal.stats.get("attack", 0))[:3]

        # 机制：同一时间只能召唤一只帕鲁出场，其余留在队伍里靠伙伴技能被动生效。
        # 所以"前排"没有意义——防守靠被动减伤/回血，不靠召唤肉盾。
        # 其余位置唯一的价值就是：它的被动能不能加成"出场的那只主C"。
        main_dps = front[0] if front else None
        ref_element = element or (
            main_dps.elements[0] if main_dps is not None and main_dps.elements else ""
        )

        scored: list[tuple[float, int, Pal, str]] = []
        for pal in self.pals:
            if main_dps is not None and pal is main_dps:
                continue  # 主C自己不用再当自己的增益位
            desc = str(pal.partner_skill.get("desc") or "")
            role = self.partner_role(pal)
            if role not in partner.SUPPORT_ROLES + ("异常增伤",):
                continue
            score, reason = partner.synergy(desc, ref_element, role)
            if score <= 0:
                continue
            scored.append((score, partner.max_percent(desc), pal, reason))
        scored.sort(key=lambda item: (-item[0], -item[1]))

        riders = [pal for pal in self.pals if self.partner_role(pal) == "坐骑"][:2]

        lines = [f"【配队素材·{element}系】" if element else "【配队素材】"]
        if note:
            lines.append(note)
        lines.append(
            "机制：同时只能召唤一只，只有主C出场打；其他位置的帕鲁留在队伍里，"
            "靠伙伴技能被动生效，不需要召唤出来。"
        )
        lines.append("主C候选（按攻击力）：" + "、".join(label(pal, "attack") for pal in front))
        if len(front) > 1:
            lines.append(
                "备用主C（换着上场）：" + "、".join(label(pal, "attack") for pal in front[1:])
            )

        support_names = []
        for score, _pct, pal, reason in scored[:5]:
            skill = str(pal.partner_skill.get("name") or "").strip()
            shown = f"{score:.1f}".rstrip("0").rstrip(".")
            support_names.append(f"{pal.name}〔{skill}·{reason}·{shown}分〕")
        if support_names and main_dps is not None:
            lines.append(
                f"搭配 {main_dps.name} 最赚的被动位（按对它的增益评分）：" + "、".join(support_names)
            )

        if riders:
            rider_names = "、".join(
                f"{pal.name}〔{str(pal.partner_skill.get('name') or '').strip()}〕" for pal in riders
            )
            lines.append(f"坐骑候选（骑乘才生效，占一个位）：{rider_names}")

        lines.append(
            "被动位只看它能不能加成主C，不用管它自己是什么属性（它不出场）。"
            "据点工作类增益（牧场产出/工作效率）不参与配队，别拿它凑位。"
        )
        lines.append("只能从上面这些名字里选，不许自己补充。")
        if element:
            lines.append(f"出场的主C必须是{element}系（其他位置不限属性）。")
        return "\n".join(lines)

    def has_element_dps(self, reply: str, element: str) -> bool:
        """回答里有没有该属性的帕鲁。

        注意：只有出场的主C需要同属性，被动位可以是任意属性
        （它们的伙伴技能在队伍里就生效），所以不能拿"全队同系"去校验。
        """
        if not element:
            return True
        return any(
            pal.name and pal.name in reply and element in pal.elements for pal in self.pals
        )

    def describe(self, pal: Pal, question: str = "") -> str:
        parts = [pal.name]

        known = [e for e in pal.elements if e and e != "未知"]
        if known:
            parts.append("属性 " + "/".join(known))

        if pal.work:
            labels = [
                f"{WORK_LABELS.get(key, key)}{level}"
                for key, level in sorted(pal.work.items(), key=lambda kv: -kv[1])
            ]
            parts.append("工作 " + " ".join(labels))

        if pal.stats:
            bits = []
            for key, label in (("hp", "HP"), ("attack", "攻"), ("defense", "防")):
                if key in pal.stats:
                    bits.append(f"{label}{pal.stats[key]}")
            if bits:
                parts.append(" ".join(bits))

        partner_name = str(pal.partner_skill.get("name") or "").strip()
        if partner_name and partner_name not in ("-", "无"):
            parts.append("伙伴技能 " + partner_name)
            # 一条技能可能有多条效果（队伍增益 + 据点工作），问的是它本身，就都报
            detail = []
            for effect in partner.effects(str(pal.partner_skill.get("desc") or ""))[:3]:
                amount = f"+{effect['lv5']}%" if effect["lv5"] else ""
                detail.append(f"{effect['role']}{amount}")
            if detail:
                parts.append("效果 " + "、".join(detail))

        if pal.drops:
            wants_drops = any(word in question for word in ("掉落", "掉什么", "打死", "打我"))
            limit = 5 if wants_drops else 3
            drops = "、".join(
                f"{item['name']}" + (f"×{item['qty']}" if item["qty"] else "")
                for item in pal.drops[:limit]
            )
            parts.append("掉落 " + drops)

        if "技能" in question:
            if pal.active_skills:
                parts.append("主动技能 " + "、".join(s["name"] for s in pal.active_skills[:6]))
            if pal.passive_skills:
                parts.append("被动 " + "、".join(s["name"] for s in pal.passive_skills[:3]))

        if pal.note:
            parts.append(pal.note)

        # 人工补充的字段（data/overrides），只在问题命中关键词时才显示
        for line in fields.render(pal.extra, question, self.field_specs):
            parts.append(line)
        return "；".join(parts)

    def has_data(self, pal: Pal) -> bool:
        """站点对少数新帕鲁还没填数据（属性写"未知"、没有工作适应性），这种不算可用。"""
        known_elements = [e for e in pal.elements if e and e != "未知"]
        return bool(pal.work or pal.stats or pal.drops or known_elements)

    def facts_for(self, question: str) -> str | None:
        """给问题找几行可用事实；找不到就返回 None（让模型糊弄过去）。"""
        if not self.pals:
            return None

        pals = self.find_pals(question)
        work_key = self.detect_work(question)

        lines: list[str] = []
        for pal in pals:
            if self.has_data(pal):
                lines.append(self.describe(pal, question))
        if work_key is not None and _asks_for_ranking(question):
            top = self.work_top(work_key)
            if top:
                label = WORK_LABELS.get(work_key, work_key)
                lines.append(
                    f"{label}最高：" + "、".join(f"{item[0].name}{item[1]}" for item in top)
                )
        if not lines:
            return None
        header = f"（资料库版本 {self.version}）" if self.version else "（资料库）"
        return header + "\n" + "\n".join(f"- {line}" for line in lines)


def _asks_for_ranking(text: str) -> bool:
    markers = ("最高", "最强", "最厉害", "谁最", "哪个", "排行")
    return any(marker in text for marker in markers)
