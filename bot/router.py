"""触发判定：这条聊天要不要回、回预设话还是回 DeepSeek。

这里是省 token 的核心，全部是本地字符串运算，不联网。
"""
from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from dataclasses import dataclass

# ASCII 关键词按"整词"匹配，避免 hi 命中 this；中文关键词按子串匹配。
_ASCII_WORD = re.compile(r"^[a-z0-9][a-z0-9 ._+-]*$")


@dataclass
class Decision:
    action: str          # "ignore" | "preset" | "ai"
    text: str = ""       # preset 时要发的内容
    reason: str = ""     # 用于日志排查


def normalize(text: str) -> str:
    """全角转半角、大小写归一、空白折叠。"""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\u200b", "").strip()
    return re.sub(r"\s+", " ", text.lower())


def find_keyword(text: str, keywords: list[str]) -> str:
    for keyword in keywords:
        word = keyword.strip().lower()
        if not word:
            continue
        if _ASCII_WORD.match(word):
            pattern = r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])"
            if re.search(pattern, text):
                return keyword
        elif word in text:
            return keyword
    return ""


class Router:
    """有状态的判定器：记得冷却、频控、当天花费。"""

    def __init__(self, cfg, now: float | None = None) -> None:
        self.cfg = cfg
        self._last_ai: dict[str, float] = {}
        self._last_preset: dict[str, float] = {}
        self._last_seen: dict[str, tuple[str, float]] = {}
        self._reply_times: list[float] = []
        self._day = ""
        self.tokens_used_today = 0
        self._start_day(now if now is not None else time.time())

    # ---------- 状态 ----------

    def _start_day(self, now: float) -> None:
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        if day != self._day:
            self._day = day
            self.tokens_used_today = 0

    def _budget_left(self, now: float) -> int:
        self._start_day(now)
        return self.cfg.limits.daily_token_budget - self.tokens_used_today

    def _rate_ok(self, now: float) -> bool:
        cutoff = now - 60.0
        self._reply_times = [t for t in self._reply_times if t >= cutoff]
        return len(self._reply_times) < self.cfg.limits.global_replies_per_minute

    def record_ai_reply(self, tokens: int, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        # 先处理跨天再记账，否则跨零点那一次会把刚花的 token 记到昨天、随后被清零
        self._start_day(now)
        self._reply_times.append(now)
        self.tokens_used_today += max(0, int(tokens))

    def record_preset_reply(self, player_id: str, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self._last_preset[player_id] = now

    # ---------- 判定 ----------

    def decide(
        self,
        player_id: str,
        player_name: str,
        message: str,
        now: float | None = None,
    ) -> Decision:
        now = now if now is not None else time.time()
        text = normalize(message)
        limits = self.cfg.limits
        trigger = self.cfg.trigger

        if not text:
            return Decision("ignore", reason="empty")

        # 自己发的公告也会触发聊天事件，不拦就会自问自答、无限烧 token
        reply_prefix = getattr(getattr(self.cfg, "reply", None), "prefix", "") or ""
        if reply_prefix and text.startswith(normalize(reply_prefix)):
            return Decision("ignore", reason="self_prefix")

        for prefix in trigger.ignore_prefixes:
            if prefix and text.startswith(prefix.strip().lower()):
                return Decision("ignore", reason=f"prefix:{prefix}")

        if len(text) > trigger.max_chars:
            return Decision("ignore", reason="too_long")

        previous = self._last_seen.get(player_id)
        if previous and previous[0] == text and now - previous[1] < limits.dedupe_window:
            return Decision("ignore", reason="duplicate")
        self._last_seen[player_id] = (text, now)

        forced = False
        command_prefix = trigger.command_prefix.strip().lower()
        if command_prefix and text.startswith(command_prefix):
            forced = True
            text = text[len(command_prefix):].strip()
            if not text:
                return Decision("ignore", reason="empty_command")

        # 1) 预设话：命中就本地发，不花 token
        if self.cfg.preset.enabled and not forced:
            rule = self._match_preset(text)
            if rule is not None:
                last = self._last_preset.get(player_id, 0.0)
                if now - last < self.cfg.preset.cooldown:
                    return Decision("ignore", reason="preset_cooldown")
                return Decision(
                    "preset",
                    text=self._pick(rule.replies, f"{player_id}:{text}"),
                    reason=f"preset:{rule.name}",
                )

        # 2) AI：必须先命中关键词，否则一律不打扰
        if len(text) < trigger.min_chars:
            return Decision("ignore", reason="too_short")
        hit = "prefix" if forced else find_keyword(text, trigger.ai_keywords)
        if not hit:
            return Decision("ignore", reason="no_trigger")

        if self._budget_left(now) <= 0:
            return Decision("ignore", reason="daily_budget_exhausted")
        if not self._rate_ok(now):
            return Decision("ignore", reason="rate_limited")
        last_ai = self._last_ai.get(player_id, 0.0)
        if now - last_ai < limits.per_player_cooldown:
            return Decision("ignore", reason="cooldown")

        self._last_ai[player_id] = now
        return Decision("ai", reason=f"keyword:{hit}")

    # ---------- 内部 ----------

    def _match_preset(self, text: str):
        for rule in self.cfg.preset.rules:
            if find_keyword(text, rule.keywords):
                return rule
        return None

    @staticmethod
    def _pick(options: list[str], seed: str) -> str:
        if not options:
            return ""
        digest = hashlib.sha1(seed.encode("utf-8")).digest()
        return options[digest[0] % len(options)]
