"""配置加载：config.toml -> dataclass，API Key 可用环境变量覆盖。

只依赖标准库（Python 3.11+ 的 tomllib），不需要 pip 装任何东西。
"""
from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def _merge_local(raw: dict, base: Path) -> dict:
    """把 config.local.json 合并进来（本机实配，含密钥，不进版本库）。

    同名子表做浅合并，其余键直接覆盖。
    """
    local_path = base / "config.local.json"
    if not local_path.is_file():
        return raw
    try:
        local = json.loads(local_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return raw
    if not isinstance(local, dict):
        return raw

    merged = dict(raw)
    for key, value in local.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


@dataclass
class DeepSeekConfig:
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    max_tokens: int = 160
    temperature: float = 1.1
    timeout: float = 25.0
    history_turns: int = 3
    thinking: bool = True


@dataclass
class TriggerConfig:
    ai_keywords: list[str] = field(default_factory=list)
    command_prefix: str = ""
    ignore_prefixes: list[str] = field(default_factory=lambda: ["!", "/", "#"])
    min_chars: int = 4
    max_chars: int = 200


@dataclass
class PresetRule:
    name: str
    keywords: list[str] = field(default_factory=list)
    replies: list[str] = field(default_factory=list)


@dataclass
class PresetConfig:
    enabled: bool = True
    cooldown: float = 45.0
    rules: list[PresetRule] = field(default_factory=list)


@dataclass
class LimitsConfig:
    per_player_cooldown: float = 90.0
    global_replies_per_minute: int = 6
    daily_token_budget: int = 200_000
    dedupe_window: float = 30.0
    max_reply_chars: int = 60


@dataclass
class ReplyConfig:
    transport: str = "palladium"  # palladium | rest | console
    target: str = "announce"      # announce | player
    prefix: str = "【大肥鱼】"
    error_text: str = ""
    unknown_text: str = "这名字我没印象 你说的是哪只"


@dataclass
class ServerConfig:
    mode: str = "stdin"  # stdin | log | palladium | tail
    bridge_url: str = "http://127.0.0.1:8080"
    bridge_token: str = ""
    event_type: str = "player.chat"
    poll_interval: float = 1.0
    request_timeout: float = 10.0
    jsonl_path: str = ""
    log_path: str = ""
    log_marker: str = "[PALBOT]"
    skip_existing: bool = True


@dataclass
class RestConfig:
    url: str = "http://127.0.0.1:8212"
    admin_password: str = ""


@dataclass
class MemoryConfig:
    enabled: bool = True
    file: str = "data/memory.json"
    max_players: int = 50


@dataclass
class ClockConfig:
    enabled: bool = True
    interval_minutes: int = 30
    templates: list[str] = field(default_factory=list)


@dataclass
class Config:
    deepseek: DeepSeekConfig
    trigger: TriggerConfig
    preset: PresetConfig
    limits: LimitsConfig
    reply: ReplyConfig
    server: ServerConfig
    palworld_rest: RestConfig
    memory: "MemoryConfig" = field(default_factory=lambda: MemoryConfig())
    clock: "ClockConfig" = field(default_factory=lambda: ClockConfig())
    persona: str = ""
    facts: str = ""
    paldex_path: str = ""
    path: Path = field(default_factory=Path)


def _table(raw: dict, key: str) -> dict:
    value = raw.get(key)
    return value if isinstance(value, dict) else {}


def _strs(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _num(value, default, cast=float):
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default


def load_config(path: str | os.PathLike) -> Config:
    config_path = Path(path).expanduser().resolve()
    # 记事本保存的 UTF-8 会带 BOM，tomllib 不认，这里先剥掉
    raw_bytes = config_path.read_bytes()
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        raw_bytes = raw_bytes[3:]
    try:
        raw = tomllib.loads(raw_bytes.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise SystemExit(f"config.toml 不是 UTF-8 编码：{exc}") from exc

    raw = _merge_local(raw, config_path.parent)

    ds_raw = _table(raw, "deepseek")
    api_key = str(ds_raw.get("api_key") or "").strip()
    env_name = str(ds_raw.get("api_key_env") or "DEEPSEEK_API_KEY").strip()
    if not api_key and env_name:
        api_key = os.environ.get(env_name, "").strip()

    deepseek = DeepSeekConfig(
        api_key=api_key,
        base_url=str(ds_raw.get("base_url") or "https://api.deepseek.com").rstrip("/"),
        model=str(ds_raw.get("model") or "deepseek-chat"),
        max_tokens=_num(ds_raw.get("max_tokens"), 160, int),
        temperature=_num(ds_raw.get("temperature"), 1.1, float),
        timeout=_num(ds_raw.get("timeout"), 25.0, float),
        history_turns=_num(ds_raw.get("history_turns"), 3, int),
        thinking=bool(ds_raw.get("thinking", True)),
    )

    tr_raw = _table(raw, "trigger")
    trigger = TriggerConfig(
        ai_keywords=_strs(tr_raw.get("ai_keywords")),
        command_prefix=str(tr_raw.get("command_prefix") or ""),
        ignore_prefixes=_strs(tr_raw.get("ignore_prefixes")),
        min_chars=_num(tr_raw.get("min_chars"), 4, int),
        max_chars=_num(tr_raw.get("max_chars"), 200, int),
    )

    ps_raw = _table(raw, "preset")
    rules: list[PresetRule] = []
    for item in ps_raw.get("rules") or []:
        if not isinstance(item, dict):
            continue
        replies = _strs(item.get("replies"))
        keywords = _strs(item.get("keywords"))
        if replies and keywords:
            rules.append(
                PresetRule(
                    name=str(item.get("name") or f"rule{len(rules)}"),
                    keywords=keywords,
                    replies=replies,
                )
            )
    preset = PresetConfig(
        enabled=bool(ps_raw.get("enabled", True)),
        cooldown=_num(ps_raw.get("cooldown"), 45.0, float),
        rules=rules,
    )

    lim_raw = _table(raw, "limits")
    limits = LimitsConfig(
        per_player_cooldown=_num(lim_raw.get("per_player_cooldown"), 90.0, float),
        global_replies_per_minute=_num(lim_raw.get("global_replies_per_minute"), 6, int),
        daily_token_budget=_num(lim_raw.get("daily_token_budget"), 200_000, int),
        dedupe_window=_num(lim_raw.get("dedupe_window"), 30.0, float),
        max_reply_chars=_num(lim_raw.get("max_reply_chars"), 60, int),
    )

    rp_raw = _table(raw, "reply")
    reply = ReplyConfig(
        transport=str(rp_raw.get("transport") or "palladium").strip().lower(),
        target=str(rp_raw.get("target") or "announce").strip().lower(),
        prefix=str(rp_raw.get("prefix") or ""),
        error_text=str(rp_raw.get("error_text") or ""),
        unknown_text=str(
            rp_raw.get("unknown_text", "这名字我没印象 你说的是哪只") or ""
        ),
    )

    mem_raw = _table(raw, "memory")
    memory = MemoryConfig(
        enabled=bool(mem_raw.get("enabled", True)),
        file=str(mem_raw.get("file") or "data/memory.json").strip(),
        max_players=_num(mem_raw.get("max_players"), 50, int),
    )

    clk_raw = _table(raw, "clock")
    clock = ClockConfig(
        enabled=bool(clk_raw.get("enabled", True)),
        interval_minutes=_num(clk_raw.get("interval_minutes"), 30, int),
        templates=_strs(clk_raw.get("templates")),
    )

    sv_raw = _table(raw, "server")
    server = ServerConfig(
        mode=str(sv_raw.get("mode") or "stdin").strip().lower(),
        bridge_url=str(sv_raw.get("bridge_url") or "http://127.0.0.1:8080").rstrip("/"),
        bridge_token=str(sv_raw.get("bridge_token") or "").strip(),
        event_type=str(sv_raw.get("event_type") or "player.chat").strip(),
        poll_interval=_num(sv_raw.get("poll_interval"), 1.0, float),
        request_timeout=_num(sv_raw.get("request_timeout"), 10.0, float),
        jsonl_path=str(sv_raw.get("jsonl_path") or "").strip(),
        log_path=str(sv_raw.get("log_path") or "").strip(),
        log_marker=str(sv_raw.get("log_marker") or "[PALBOT]"),
        skip_existing=bool(sv_raw.get("skip_existing", True)),
    )

    rest_raw = _table(raw, "palworld_rest")
    palworld_rest = RestConfig(
        url=str(rest_raw.get("url") or "http://127.0.0.1:8212").rstrip("/"),
        admin_password=str(rest_raw.get("admin_password") or ""),
    )

    persona_file = str(raw.get("persona_file") or "persona.md").strip()
    persona_path = (config_path.parent / persona_file).resolve()
    try:
        persona = persona_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SystemExit(f"读不到人设文件 {persona_path}: {exc}") from exc
    if not persona:
        raise SystemExit(f"人设文件是空的：{persona_path}")

    facts_file = str(raw.get("facts_file") or "").strip()
    facts = ""
    if facts_file:
        facts_path = (config_path.parent / facts_file).resolve()
        try:
            facts = facts_path.read_text(encoding="utf-8").strip()
        except OSError:
            facts = ""  # 事实文件是可选的，缺了也能跑

    paldex_file = str(raw.get("paldex_file") or "").strip()
    paldex_path = ""
    if paldex_file:
        paldex_path = str((config_path.parent / paldex_file).resolve())

    return Config(
        deepseek=deepseek,
        trigger=trigger,
        preset=preset,
        limits=limits,
        reply=reply,
        server=server,
        palworld_rest=palworld_rest,
        memory=memory,
        clock=clock,
        persona=persona,
        facts=facts,
        paldex_path=paldex_path,
        path=config_path,
    )
