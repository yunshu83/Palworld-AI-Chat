"""整点 / 半点报时。

刻意不用模型：报时是固定内容，让模型现编既慢又费 token，
而且可能把时间说错。这里用模板 + 时间占位符，0 成本。
"""
from __future__ import annotations

import time


class Clock:
    def __init__(
        self,
        interval_minutes: int = 30,
        templates: list[str] | None = None,
        enabled: bool = True,
    ) -> None:
        self.interval = max(1, int(interval_minutes))
        self.enabled = enabled
        self.templates = [
            t for t in (templates or []) if isinstance(t, str) and "{" in t
        ] or ["【报时】{time} {period}"]
        self._next = self._next_boundary(time.time())

    # ---------- 时间点计算 ----------

    def _next_boundary(self, now: float) -> float:
        """返回严格大于 now 的下一个整点/半点。"""
        local = time.localtime(now)
        base = time.mktime(
            (local.tm_year, local.tm_mon, local.tm_mday, local.tm_hour, 0, 0, 0, 0, -1)
        )
        target_minute = ((local.tm_min // self.interval) + 1) * self.interval
        candidate = base + target_minute * 60
        while candidate <= now:
            candidate += self.interval * 60
        return candidate

    @staticmethod
    def _period(slot: float) -> str:
        minute = time.localtime(slot).tm_min
        if minute == 0:
            return "整点"
        if minute == 30:
            return "半点"
        return "报时"

    # ---------- 对外接口 ----------

    def due(self, now: float | None = None) -> str | None:
        """到点了就返回要播的文本，否则返回 None。错过太久不补发。"""
        if not self.enabled:
            return None
        now = now if now is not None else time.time()
        if now < self._next:
            return None

        slot = self._next
        self._next += self.interval * 60
        while self._next <= now:
            self._next += self.interval * 60

        # 睡过了/卡了很久就不补，免得一次刷出好几条过时的时间
        if now - slot > 120:
            return None
        return self.render(slot)

    def render(self, slot: float) -> str:
        clock = time.strftime("%H:%M", time.localtime(slot))
        period = self._period(slot)
        # 按「第几个报时点」轮换，而不是按分钟数——间隔 30 分钟时后者会一直取到同一条
        index = int(slot // (self.interval * 60)) % len(self.templates)
        template = self.templates[index]
        return template.replace("{time}", clock).replace("{period}", period).strip()

    def next_at(self) -> float:
        return self._next
