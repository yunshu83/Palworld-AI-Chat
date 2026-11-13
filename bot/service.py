"""把"读聊天 → 判定 → 调 DeepSeek → 发回复"串起来。"""
from __future__ import annotations

import re
import sys
import time

from .adapters import (
    ChatEvent,
    ConsoleSink,
    JsonlTailSource,
    MarkerLogSource,
    PalladiumSink,
    PalladiumSource,
    RestSink,
    StdinSource,
)
from .clock import Clock
from .deepseek import DeepSeekClient, DeepSeekError
from .elements import Elements
from .guard import unknown_names
from .housekeeping import cleanup_logs
from .lore import Lore
from .memory import Memory
from .paldex import Paldex
from .router import Router
from .settings import Config

_SENTENCE = re.compile(r"(?<=[。！？!?…~])")


def sanitize_reply(text: str, max_chars: int) -> str:
    """把模型输出裁成"游戏聊天里能看"的一两句。"""
    text = (text or "").strip()
    if not text:
        return ""
    text = re.sub(r"```.*?(?:```|$)", "", text, flags=re.S)
    text = re.sub(r"[*_`#>|\[\]]+", "", text)
    text = re.sub(r"^(?:小鱼|大肥鱼|肥鱼)\s*[:：]\s*", "", text)
    text = re.sub(r"^(?:回答|回复)\s*[:：]\s*", "", text)
    text = text.replace("\n", " ").replace("\r", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip(" \"'“”‘’「」")

    parts = [part for part in _SENTENCE.split(text) if part.strip()]
    if parts:
        text = "".join(parts[:2]).strip()

    if len(text) > max_chars:
        cut = max((text.rfind(char) for char in "。！？!?，,"), default=-1)
        if cut >= max_chars // 2:
            text = text[: cut + 1]
        else:
            text = text[: max(0, max_chars - 1)].rstrip() + "…"
    return text.strip()


def create_source(cfg: Config):
    if cfg.server.mode == "log":
        return MarkerLogSource(cfg.server.log_path, cfg.server.log_marker, cfg.server.skip_existing)
    if cfg.server.mode == "palladium":
        return PalladiumSource(
            cfg.server.bridge_url,
            cfg.server.bridge_token,
            cfg.server.event_type,
            cfg.server.request_timeout,
        )
    if cfg.server.mode == "tail":
        return JsonlTailSource(cfg.server.jsonl_path, cfg.server.event_type)
    return StdinSource(cfg.server.event_type)


def create_sink(cfg: Config):
    if cfg.reply.transport == "palladium":
        return PalladiumSink(
            cfg.server.bridge_url,
            cfg.server.bridge_token,
            cfg.server.request_timeout,
            private=cfg.reply.target == "player",
        )
    if cfg.reply.transport == "rest":
        if cfg.reply.target == "player":
            print("[警告] REST 出口只能全服公告，已按 announce 处理。", file=sys.stderr)
        return RestSink(
            cfg.palworld_rest.url,
            cfg.palworld_rest.admin_password,
            cfg.server.request_timeout,
        )
    return ConsoleSink()


class Bot:
    def __init__(self, cfg: Config, dry_run: bool = False) -> None:
        self.cfg = cfg
        self.dry_run = dry_run
        self.router = Router(cfg)
        self.source = create_source(cfg)
        self.sink = create_sink(cfg)
        self.client = None if dry_run else DeepSeekClient(cfg.deepseek)
        self.paldex = Paldex.load(cfg.paldex_path) if cfg.paldex_path else None
        self.lore = Lore.load(cfg.path.parent / "data")
        # 名字校验的白名单：帕鲁名 + 伙伴技能名 + 主动/被动技能名。
        # 只放帕鲁名会把"暴力青草兔"这种技能名截断成"力青草兔"并误判为编造。
        self._known_names = []

        def _add(value) -> None:
            if isinstance(value, dict):
                value = value.get("name")
            if isinstance(value, str) and value.strip():
                self._known_names.append(value.strip())

        if self.paldex:
            for pal in self.paldex.pals:
                _add(pal.name)
                _add(pal.partner_skill.get("name"))
                for item in pal.active_skills or []:
                    _add(item)
                for item in pal.passive_skills or []:
                    _add(item)
        if self.lore is not None:
            for item in self.lore.skills:
                _add(item.get("name"))
        self._known_names = [name for name in self._known_names if name]
        self.elements = Elements.load(cfg.path.parent / "data" / "elements.json")
        self.memory = (
            Memory.load(
                cfg.path.parent / cfg.memory.file,
                cfg.deepseek.history_turns,
                cfg.memory.max_players,
            )
            if cfg.memory.enabled
            else None
        )
        self.clock = (
            Clock(cfg.clock.interval_minutes, cfg.clock.templates, cfg.clock.enabled)
            if cfg.clock.enabled
            else None
        )

    # ---------- 主循环 ----------

    def run(self, once: bool = False) -> None:
        removed = cleanup_logs(self.cfg.path.parent / "logs")
        if removed:
            self._log(f"清理了 {removed} 个旧日志")
        self._banner()
        interval = max(0.2, float(self.cfg.server.poll_interval))
        try:
            while True:
                for event in self.source.poll():
                    self.handle(event)
                self._maybe_clock()
                if once:
                    return
                time.sleep(interval)
        except KeyboardInterrupt:
            self._log("已停止。")

    def _maybe_clock(self) -> None:
        """整点/半点报时：本地模板，不花 token。"""
        if self.clock is None:
            return
        message = self.clock.due()
        if not message:
            return
        if self.sink.send(message, ""):
            self._log(f"报时 {message}")

    def handle(self, event: ChatEvent) -> None:
        decision = self.router.decide(event.player_id, event.player_name, event.message)

        if decision.action == "ignore":
            self._log(f"跳过 {event.player_name}: {event.message!r} → {decision.reason}")
            return

        if decision.action == "preset":
            self.router.record_preset_reply(event.player_id)
            self._log(f"预设 {event.player_name}: {event.message!r} → {decision.reason}")
            self._deliver(decision.text, event.player_id)
            return

        self._log(f"命中 {event.player_name}: {event.message!r} → {decision.reason}")

        if self.dry_run:
            self._deliver(f"[dry-run] 这里会调用 {self.cfg.deepseek.model} 生成回复", event.player_id)
            return

        try:
            content, usage = self.client.chat(self._build_messages(event))
        except DeepSeekError as exc:
            self._log(f"DeepSeek 失败：{exc}")
            if self.cfg.reply.error_text:
                self._deliver(self.cfg.reply.error_text, event.player_id)
            return

        text = sanitize_reply(content, self.cfg.limits.max_reply_chars)
        if not text:
            self._log("模型返回空内容，跳过。")
            return

        suspects = unknown_names(text, self._known_names)
        if suspects:
            self._log(f"拦下编造的帕鲁名：{'、'.join(suspects)}")
            text = self.cfg.reply.unknown_text
            if not text:
                return

        # 配队回答里应当至少出现该属性的主C（其他位置不限属性，只记提醒）
        team = self.paldex.team_materials(event.message, self.elements) if self.paldex else None
        if team:
            import re as _re

            match = _re.search(r"【配队素材·(\S+?)系】", team)
            if match and self.paldex is not None:
                element = match.group(1)
                if not self.paldex.has_element_dps(text, element):
                    self._log(f"提醒：回答里没出现{element}系帕鲁，可能没按克制选主C")

        self.router.record_ai_reply(usage.billed)
        self._remember(event, text)
        self._log(f"回复 {event.player_name}: {text}  ({usage})")
        self._deliver(text, event.player_id)

    # ---------- 内部 ----------

    def _build_messages(self, event: ChatEvent) -> list[dict]:
        # system 必须对所有玩家完全一致，才能命中 DeepSeek 的上下文前缀缓存。
        # 所以玩家名不要拼进 system——那会让每个人的前缀都不同，每次都全价重算。
        system = self.cfg.persona
        if self.cfg.facts:
            system += "\n\n【已知事实 · 必须遵守】\n" + self.cfg.facts
        system += (
            "\n\n---\n现在在游戏里聊天。只回一到两句：简单问题简短点（十几二十字），"
            "复杂点的问题可以说清楚，最多到一百字。"
            "别为凑字数注水，也别硬砍成半句。不要换行、不要列表。"
        )
        messages = [{"role": "system", "content": system}]
        if self.memory is not None:
            messages.extend(self.memory.history(event.player_id))

        # 资料库条目放进 user 消息而不是 system：system 必须逐字节稳定才能命中缓存
        content = f"{event.player_name}：{event.message}"
        blocks: list[str] = []
        if self.paldex is not None:
            found = self.paldex.facts_for(event.message)
            if found:
                blocks.append(found)
            team = self.paldex.team_materials(event.message, self.elements)
            if team:
                blocks.append(team)
        if self.elements is not None:
            found = self.elements.facts_for(event.message)
            if found:
                blocks.append(found)
        if self.lore is not None:
            found = self.lore.facts_for(event.message)
            if found:
                blocks.append(found)
        if blocks:
            # 合成一块：分两块时模型会只顾第一块，漏掉配队/词条
            content += "\n\n【资料库（准确数据，名字和数字都要用上）】\n" + "\n".join(blocks)
        messages.append({"role": "user", "content": content})
        return messages

    def _remember(self, event: ChatEvent, reply: str) -> None:
        if self.memory is not None:
            self.memory.remember(event.player_id, event.message, reply)

    def _deliver(self, text: str, player_id: str) -> None:
        message = f"{self.cfg.reply.prefix}{text}" if self.cfg.reply.prefix else text
        message = message.strip()
        if not message:
            return
        if len(message) > 200:
            message = message[:199] + "…"
        ok = self.sink.send(message, player_id)
        if not ok:
            self._log("发送失败（回复内容仍记录在上一条日志里）")

    def _banner(self) -> None:
        cfg = self.cfg
        self._log("小鱼（鲸鱼娘）DeepSeek 助手已启动")
        self._log(f"  读取方式 : {cfg.server.mode}  ({cfg.server.event_type})")
        self._log(f"  回复方式 : {cfg.reply.transport} → {cfg.reply.target}")
        self._log(f"  模型     : {cfg.deepseek.model}")
        self._log(f"  AI 关键词: {', '.join(cfg.trigger.ai_keywords) or '（空，只能靠指令前缀触发）'}")
        self._log(f"  预设规则 : {len(cfg.preset.rules)} 条")
        if self.lore is not None:
            self._log(
                f"  技能/材料: {len(self.lore.skills)} 技能 / "
                f"{len(self.lore.materials)} 材料 / {len(self.lore.schematics)} 传奇图纸 / "
                f"{len(self.lore.techs)} 科技"
            )
        if self.paldex is not None:
            self._log(f"  资料库   : {len(self.paldex.pals)} 条（{self.paldex.version or '未标版本'}）")
        else:
            self._log("  资料库   : 未启用（缺 data/paldex.json）")
        if self.memory is not None:
            self._log(
                f"  记忆     : {self.memory.day} / {self.memory.player_count} 人（跨天自动清空）"
            )
        else:
            self._log("  记忆     : 未启用")
        if self.clock is not None:
            next_at = time.strftime("%H:%M", time.localtime(self.clock.next_at()))
            self._log(f"  报时     : 每 {self.cfg.clock.interval_minutes} 分钟，下次 {next_at}")
        else:
            self._log("  报时     : 未启用")
        self._log(
            f"  限额     : 每人 {cfg.limits.per_player_cooldown:.0f}s / "
            f"全服 {cfg.limits.global_replies_per_minute} 次每分钟 / "
            f"每日 {cfg.limits.daily_token_budget} tokens（按缓存未命中计）"
        )
        if self.dry_run:
            self._log("  模式     : dry-run（不调用 DeepSeek，不需要 API Key）")
        if cfg.server.mode == "stdin":
            self._log('  输入格式 : 玩家名: 说的话   （Ctrl+C 退出）')

    @staticmethod
    def _log(message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        print(f"[{stamp}] {message}", flush=True)
