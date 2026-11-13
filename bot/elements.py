"""属性克制：查表 + 算倍率 + 生成可注入的事实。

克制关系来自 data/elements.json：
  火→草/冰  草→地  地→雷  雷→水  水→火  冰→龙  龙→暗  暗→无
  克制 ×2，被克 ×0.5，其余 ×1；双属性连乘，最高 4 倍。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ELEMENTS = ("火", "冰", "暗", "龙", "地", "雷", "水", "草", "无")


class Elements:
    def __init__(self, chain: dict[str, list[str]], aliases: dict[str, str] | None = None) -> None:
        self.chain = {key: list(value) for key, value in chain.items()}
        self.aliases = dict(aliases or {})

    @classmethod
    def load(cls, path: str | Path) -> "Elements | None":
        file_path = Path(path)
        if not file_path.is_file():
            return None
        try:
            raw = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        chain = raw.get("chain")
        if not isinstance(chain, dict):
            return None
        aliases = raw.get("aliases") if isinstance(raw.get("aliases"), dict) else {}
        return cls({str(k): [str(x) for x in v] for k, v in chain.items()}, aliases)

    # ---------- 基础查询 ----------

    def normalize(self, name: str) -> str:
        return self.aliases.get(name, name)

    def beats(self, element: str) -> list[str]:
        return self.chain.get(self.normalize(element), [])

    def beaten_by(self, element: str) -> list[str]:
        """哪些属性克制它。"""
        target = self.normalize(element)
        return [attacker for attacker, defenders in self.chain.items() if target in defenders]

    def multiplier(self, attacker: str, defenders: list[str]) -> float:
        """攻击方打一个（或双属性）目标的倍率，双属性连乘。"""
        source = self.normalize(attacker)
        result = 1.0
        for defender in defenders:
            target = self.normalize(defender)
            if target in self.beats(source):
                result *= 2.0
            elif source in self.beats(target):
                result *= 0.5
        return result

    # ---------- 问答 ----------

    def _mentioned(self, question: str) -> str:
        for element in ELEMENTS:
            if f"{element}系" in question or f"{element}属性" in question:
                return element
        # 也支持"火克什么""雷怕什么"这种不带"系"的说法
        match = re.search(r"([火冰暗龙地雷水草无土电])(?:系|属性)?(?:克|打|怕|弱)", question)
        if match:
            return self.normalize(match.group(1))
        for alias, target in self.aliases.items():
            if f"{alias}系" in question or f"{alias}属性" in question:
                return target
        return ""

    def facts_for(self, question: str) -> str | None:
        element = self._mentioned(question)
        if not element:
            # 没提具体属性，但问的是倍率/克制规则 → 给通用规则
            if any(word in question for word in ("倍率", "克制", "双属性", "相乘", "相克")):
                return "（属性克制）\n" + "\n".join(f"- {line}" for line in self.general_rules())
            return None

        lines: list[str] = []
        if any(word in question for word in ("克", "打", "怕", "弱", "针对")):
            strong = self.beats(element)
            weak = self.beaten_by(element)
            if strong and ("克" in question or "打" in question):
                lines.append(
                    f"{element}系克制：{'、'.join(x + '系' for x in strong)}（2 倍伤害）"
                )
            if weak:
                lines.append(
                    f"{element}系被克：{'、'.join(x + '系' for x in weak)}（对方打你是 2 倍）"
                )
            if not lines and weak:
                lines.append(f"{element}系被{'、'.join(x + '系' for x in weak)}克制")

        if "倍" in question:
            lines.append("克制 2 倍、被克 0.5 倍、无克制 1 倍；双属性连乘，最高 4 倍")

        if not lines:
            return None
        return "（属性克制）\n" + "\n".join(f"- {line}" for line in lines)

    def general_rules(self) -> list[str]:
        chain = "；".join(
            f"{attacker}克{'、'.join(defenders)}" for attacker, defenders in self.chain.items() if defenders
        )
        return [
            chain,
            "克制伤害 2 倍、被克制 0.5 倍、无克制 1 倍",
            "双属性把两个倍率相乘，最高 4 倍（例如火打草+冰 = 2×2）",
        ]

    def best_attackers(self, target_element: str) -> list[str]:
        """打某个属性该用什么属性。"""
        return self.beaten_by(target_element)
