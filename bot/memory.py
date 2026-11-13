"""当天对话记忆：跨重启保留，跨天自动清空。

设计上刻意做得简单——只存"今天谁跟小鱼说过什么"，
不存长期画像，也不做摘要，避免把 token 花在回忆上。
"""
from __future__ import annotations

import json
import time
from pathlib import Path


def today() -> str:
    return time.strftime("%Y-%m-%d")


class Memory:
    def __init__(
        self,
        path: str | Path,
        turns: int = 3,
        max_players: int = 50,
        clock=None,
    ) -> None:
        self.path = Path(path)
        self.turns = max(0, int(turns))
        self.max_players = max(1, int(max_players))
        self._clock = clock or today
        self._day = ""
        self._players: dict[str, list[dict]] = {}
        # 构造即读取：直接 new 一个也不会把磁盘上的记忆冲掉
        self._read()

    # ---------- 载入 / 保存 ----------

    @classmethod
    def load(cls, path: str | Path, turns: int = 3, max_players: int = 50, clock=None) -> "Memory":
        memory = cls(path, turns, max_players, clock)
        memory.ensure_day()
        return memory

    def _read(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        self._day = str(raw.get("date") or "")
        players = raw.get("players")
        if not isinstance(players, dict):
            return
        keep = self.turns * 2
        if keep <= 0:
            return
        for player_id, messages in players.items():
            if not isinstance(messages, list):
                continue
            cleaned = [
                message
                for message in messages
                if isinstance(message, dict) and message.get("role") in ("user", "assistant")
            ]
            if cleaned:
                self._players[str(player_id)] = cleaned[-keep:]

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"date": self._day, "players": self._players}
            self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass  # 记忆丢了不该影响回话

    # ---------- 按天重置 ----------

    def ensure_day(self, day: str | None = None) -> bool:
        """日期变了就清空。返回是否发生了重置。"""
        current = day or self._clock()
        if current == self._day:
            return False
        self._day = current
        self._players.clear()
        self.save()
        return True

    # ---------- 读写对话 ----------

    def history(self, player_id: str) -> list[dict]:
        self.ensure_day()
        return list(self._players.get(player_id, []))

    def remember(self, player_id: str, user_text: str, reply: str) -> None:
        if self.turns <= 0:
            return
        self.ensure_day()
        messages = self._players.setdefault(player_id, [])
        messages.append({"role": "user", "content": user_text})
        messages.append({"role": "assistant", "content": reply})
        del messages[: max(0, len(messages) - self.turns * 2)]

        if len(self._players) > self.max_players:
            overflow = len(self._players) - self.max_players
            for key in list(self._players)[:overflow]:
                self._players.pop(key, None)

        self.save()

    @property
    def day(self) -> str:
        return self._day

    @property
    def player_count(self) -> int:
        return len(self._players)
