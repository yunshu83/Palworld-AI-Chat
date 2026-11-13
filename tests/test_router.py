"""本地自检：不需要服务器、不需要 API Key。

运行：python tests/test_router.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 沙箱环境下 tempfile 可能回退到当前目录，所以统一登记、跑完删掉
_TEMP_DIRS: list[Path] = []


def tempdir() -> Path:
    path = Path(tempfile.mkdtemp())
    _TEMP_DIRS.append(path)
    return path

from bot.adapters import decode_line, parse_relay_entries, parse_relay_line  # noqa: E402
from bot.deepseek import usage_from  # noqa: E402
from bot.deepseek import _retryable  # noqa: E402
from bot.router import Router, find_keyword, normalize  # noqa: E402
from bot.service import sanitize_reply  # noqa: E402
from bot.settings import LimitsConfig, PresetConfig, PresetRule, TriggerConfig  # noqa: E402


def make_router(**limit_overrides) -> Router:
    limits = LimitsConfig(
        per_player_cooldown=limit_overrides.get("per_player_cooldown", 90.0),
        global_replies_per_minute=limit_overrides.get("global_replies_per_minute", 6),
        daily_token_budget=limit_overrides.get("daily_token_budget", 1000),
        dedupe_window=limit_overrides.get("dedupe_window", 30.0),
        max_reply_chars=limit_overrides.get("max_reply_chars", 120),
    )
    cfg = SimpleNamespace(
        trigger=TriggerConfig(
            ai_keywords=["肥鱼", "deepseek", "hi"],
            command_prefix="",
            ignore_prefixes=["!", "/"],
            min_chars=limit_overrides.get("min_chars", 2),
            max_chars=limit_overrides.get("max_chars", 200),
        ),
        preset=PresetConfig(
            enabled=True,
            cooldown=limit_overrides.get("preset_cooldown", 45.0),
            rules=[
                PresetRule("greeting", ["你好", "hello"], ["咕噜，在的。", "来啦来啦。"]),
                PresetRule("thanks", ["谢谢"], ["不客气。"]),
            ],
        ),
        limits=limits,
    )
    return Router(cfg)


# ---------------- 关键词 ----------------

def test_find_keyword_cjk_substring() -> None:
    assert find_keyword("肥鱼在吗", ["肥鱼"]) == "肥鱼"


def test_find_keyword_ascii_needs_word_boundary() -> None:
    assert find_keyword("this is fine", ["hi"]) == ""
    assert find_keyword("hi there", ["hi"]) == "hi"


def test_normalize_width_and_case() -> None:
    assert normalize("ＨＥＬＬＯ　 世界") == "hello 世界"


# ---------------- 三层判定 ----------------

def test_greeting_uses_preset_not_ai() -> None:
    decision = make_router().decide("p1", "Ada", "你好呀")
    assert decision.action == "preset", decision
    assert decision.text in {"咕噜，在的。", "来啦来啦。"}


def test_no_keyword_is_silent() -> None:
    decision = make_router().decide("p1", "Ada", "今天打了好多帕鲁")
    assert decision.action == "ignore"
    assert decision.reason == "no_trigger"


def test_keyword_calls_ai() -> None:
    decision = make_router().decide("p1", "Ada", "肥鱼这游戏怎么升级快")
    assert decision.action == "ai", decision


def test_ignore_prefix_wins() -> None:
    decision = make_router().decide("p1", "Ada", "!tp 肥鱼")
    assert decision.action == "ignore"
    assert decision.reason.startswith("prefix:")


def test_too_short_and_too_long() -> None:
    router = make_router(min_chars=4, max_chars=20)
    assert router.decide("p1", "Ada", "嗯").reason == "too_short"
    assert router.decide("p2", "Bob", "肥鱼" + "哈" * 40).reason == "too_long"


# ---------------- 限额 ----------------

def test_per_player_cooldown() -> None:
    router = make_router()
    now = 1_000.0
    first = router.decide("p1", "Ada", "肥鱼怎么配种", now)
    assert first.action == "ai"
    second = router.decide("p1", "Ada", "肥鱼怎么造房子", now + 5)
    assert second.reason == "cooldown"
    third = router.decide("p1", "Ada", "肥鱼怎么钓", now + 100)
    assert third.action == "ai"


def test_other_players_not_blocked_by_cooldown() -> None:
    router = make_router()
    now = 1_000.0
    router.decide("p1", "Ada", "肥鱼怎么配种", now)
    other = router.decide("p2", "Bob", "肥鱼怎么造房子", now + 1)
    assert other.action == "ai"


def test_daily_budget_exhausted() -> None:
    router = make_router(daily_token_budget=100)
    router.record_ai_reply(150, now=1_000.0)
    decision = router.decide("p2", "Bob", "肥鱼还在吗", now=2_000.0)
    assert decision.reason == "daily_budget_exhausted"


def test_global_rate_limit() -> None:
    router = make_router(global_replies_per_minute=2)
    now = 1_000.0
    router.record_ai_reply(10, now=now)
    router.record_ai_reply(10, now=now + 1)
    decision = router.decide("p9", "Zoe", "肥鱼出来", now + 2)
    assert decision.reason == "rate_limited"


def test_duplicate_message_ignored() -> None:
    router = make_router()
    now = 1_000.0
    assert router.decide("p1", "Ada", "肥鱼帮帮我", now).action == "ai"
    repeat = router.decide("p1", "Ada", "肥鱼帮帮我", now + 3)
    assert repeat.reason == "duplicate"


# ---------------- 回复清洗 ----------------

def test_sanitize_strips_markdown_and_extra_sentences() -> None:
    raw = "**大肥鱼：** 多放食盆就好。别指望它们自觉。第三句应该被砍掉。"
    assert sanitize_reply(raw, 120) == "多放食盆就好。别指望它们自觉。"


def test_sanitize_caps_length() -> None:
    raw = "啊" * 300
    out = sanitize_reply(raw, 120)
    assert len(out) <= 120
    assert out.endswith("…")


def test_sanitize_empty() -> None:
    assert sanitize_reply("   ", 120) == ""


# ---------------- UE4SS 日志解析 ----------------

def test_decode_line_utf8_from_pipe() -> None:
    text = "小明: 大肥鱼在吗"
    assert decode_line(text.encode("utf-8"), "cp936") == text


def test_decode_line_strips_bom() -> None:
    assert decode_line(b"\xef\xbb\xbfhello", "cp936") == "hello"


# ---------------- 用量换算（缓存 → 计费口径） ----------------

def test_usage_from_payload_counts_billed() -> None:
    usage = usage_from(
        {
            "prompt_tokens": 1047,
            "completion_tokens": 20,
            "total_tokens": 1067,
            "prompt_cache_hit_tokens": 896,
            "prompt_cache_miss_tokens": 151,
        }
    )
    assert (usage.total, usage.cached, usage.billed) == (1067, 896, 171)
    assert "缓存命中 896" in str(usage) and "计费口径 171" in str(usage)


def test_usage_from_payload_without_cache_fields() -> None:
    usage = usage_from({"prompt_tokens": 280, "completion_tokens": 20, "total_tokens": 300})
    assert usage.cached == 0
    assert usage.billed == 300
    assert str(usage) == "300 tokens"


def test_parse_relay_line_cuts_trailing_log() -> None:
    # UE4SS 的 Lua print 不带换行，真实日志长这样（下一行的时间戳粘在内容后面）
    line = (
        "[2026-11-04 17:30:00.1] [Lua] [PALBOT] 小明\t小鱼 这游戏怎么升级快"
        "[2026-11-04 17:30:00.4] [Lua] [NoPalDeposit] hot path/15s"
    )
    event = parse_relay_line(line, "[PALBOT]")
    assert event is not None
    assert event.player_name == "小明"
    assert event.message == "小鱼 这游戏怎么升级快"


def test_parse_relay_entries_handles_two_merged() -> None:
    line = "[Lua] [PALBOT] 甲\t第一句[2026-11-04 17:30:01.0] [Lua] [PALBOT] 乙\t第二句"
    events = parse_relay_entries(line, "[PALBOT]")
    assert [event.message for event in events] == ["第一句", "第二句"]


def test_parse_relay_line() -> None:
    line = "[2026-11-04 11:20:01] [PALBOT] 小明\t大肥鱼在吗"
    event = parse_relay_line(line, "[PALBOT]")
    assert event is not None
    assert event.player_name == "小明"
    assert event.message == "大肥鱼在吗"


def test_parse_relay_line_skips_noise() -> None:
    assert parse_relay_line("some unrelated UE4SS line", "[PALBOT]") is None
    assert parse_relay_line("[PALBOT] ready, 2 hook(s)", "[PALBOT]") is None
    assert parse_relay_line("[PALBOT] 小明\t", "[PALBOT]") is None


# ---------------- 出厂配置本身 ----------------

def shipped_config():
    from bot.settings import load_config

    base = Path(__file__).resolve().parents[1]
    path = base / "config.toml"
    # 新克隆 / 发布包里没有本机 config.toml，退回公开模板
    if not path.is_file():
        path = base / "config.example.toml"
    return load_config(path)


def test_shipped_config_routes_fatfish_to_preset() -> None:
    router = Router(shipped_config())
    decision = router.decide("p1", "Ada", "大肥鱼在吗")
    assert decision.action == "preset", decision.reason
    assert decision.reason == "preset:fatfish"


def test_shipped_config_greeting_is_preset() -> None:
    router = Router(shipped_config())
    decision = router.decide("p1", "Ada", "你好")
    assert decision.action == "preset", decision.reason
    assert decision.reason == "preset:greeting"


def test_shipped_config_keyword_calls_ai() -> None:
    router = Router(shipped_config())
    decision = router.decide("p1", "Ada", "小鱼 这游戏怎么升级快")
    assert decision.action == "ai", decision.reason


def test_shipped_config_plain_chat_ignored() -> None:
    router = Router(shipped_config())
    decision = router.decide("p1", "Ada", "今天打了三个帕鲁")
    assert decision.action == "ignore", decision.reason


def test_shipped_config_loads_facts() -> None:
    cfg = shipped_config()
    assert cfg.facts, "server_facts.md 没被读进来"
    assert "v1.0.5" in cfg.facts
    assert cfg.limits.dedupe_window <= 5.0, "去重窗口过大，会把玩家重发当成重复"
    assert cfg.limits.per_player_cooldown <= 30.0, "冷却过长，玩家会以为机器人坏了"


def test_shipped_config_ignores_own_announce() -> None:
    # 机器人自己的公告会再次触发聊天事件，前缀必须被挡住，否则自问自答
    cfg = shipped_config()
    router = Router(cfg)
    decision = router.decide("p1", "Ada", f"{cfg.reply.prefix}去打怪孵蛋 关键别死")
    assert decision.action == "ignore", decision.reason
    assert decision.reason == "self_prefix"


def test_retryable_only_retries_transient_errors() -> None:
    assert _retryable("网络错误: [Errno 11001] getaddrinfo failed")
    assert _retryable("请求超时")
    assert _retryable("HTTP 502: bad gateway")
    assert _retryable("HTTP 429: rate limited")
    assert not _retryable("HTTP 401: invalid key")
    assert not _retryable("HTTP 400: bad request")


# ---------------- 资料库 ----------------

SAMPLE_DEX = Path(__file__).resolve().parent / "fixtures" / "paldex.sample.json"


def sample_dex() -> "Paldex":
    from bot.paldex import Paldex

    dex = Paldex.load(SAMPLE_DEX)
    assert dex is not None, "样例资料库没读进来"
    return dex


def test_paldex_finds_pal_by_alias() -> None:
    pal = sample_dex().find_pal("甲帕鲁的掉落是什么")
    assert pal is not None and pal.name == "甲"


def test_paldex_detects_work_label() -> None:
    dex = sample_dex()
    assert dex.detect_work("哪个帕鲁发电最高") == "generating_electricity"
    assert dex.detect_work("谁挖矿最强") == "mining"


def test_paldex_rank_uses_data() -> None:
    facts = sample_dex().facts_for("哪个帕鲁发电最高")
    assert facts is not None
    assert "乙4" in facts and "丙2" in facts


def test_paldex_returns_none_without_hit() -> None:
    assert sample_dex().facts_for("今天天气怎么样") is None


def test_paldex_skips_pals_without_data() -> None:
    # 站点对少数新帕鲁只有"未知属性"、没有工作数据：宁可不给，也别让模型拿"未知"去发挥
    assert sample_dex().facts_for("丁帕鲁的属性是什么") is None


def test_paldex_describe_includes_stats_and_drops() -> None:
    facts = sample_dex().facts_for("甲的掉落是什么")
    assert facts is not None
    assert "HP100" in facts
    assert "甲之牙" in facts


def test_paldex_missing_file_is_disabled() -> None:
    from bot.paldex import Paldex

    assert Paldex.load(Path("no-such-paldex.json")) is None


# ---------------- 技能 / 材料 / 图纸 ----------------

def test_lore_answers_skill_by_name() -> None:
    from bot.lore import Lore

    lore = Lore(skills=[{"name": "毒雾", "element": "暗", "type": "远程", "power": 0, "cooldown": 30, "desc": "制造毒雾"}])
    facts = lore.facts_for("毒雾这个技能怎么样")
    assert facts is not None
    assert "冷却30秒" in facts


def test_lore_answers_ranking() -> None:
    from bot.lore import Lore

    lore = Lore(skills=[{"name": "甲技", "power": 100}, {"name": "乙技", "power": 50}])
    facts = lore.facts_for("哪个技能威力最高")
    assert facts is not None and "甲技100" in facts


def test_lore_returns_none_without_hit() -> None:
    from bot.lore import Lore

    assert Lore(skills=[{"name": "毒雾"}]).facts_for("今天天气怎么样") is None


def test_lore_answers_tech_materials() -> None:
    from bot.lore import Lore

    lore = Lore(
        techs=[
            {
                "name": "帕鲁球",
                "level": 2,
                "points": 1,
                "materials": [{"name": "木材", "qty": 5}, {"name": "石头", "qty": 3}],
                "desc": "抓帕鲁用",
            }
        ]
    )
    facts = lore.facts_for("帕鲁球要什么材料")
    assert facts is not None
    assert "木材×5" in facts and "石头×3" in facts


def test_lore_answers_tech_by_name() -> None:
    from bot.lore import Lore

    lore = Lore(techs=[{"name": "帕鲁球", "level": 2, "points": 1, "desc": "用来抓帕鲁的"}])
    facts = lore.facts_for("帕鲁球几级解锁")
    assert facts is not None
    assert "2级解锁" in facts


def test_lore_loads_shipped_data_files() -> None:
    from bot.lore import Lore

    lore = Lore.load(Path(__file__).resolve().parents[1] / "data")
    assert lore is not None, "data/ 下的技能或材料库没生成"
    assert len(lore.skills) > 300
    assert len(lore.materials) > 150
    assert len(lore.schematics) > 50
    assert len(lore.techs) > 400


def test_lore_answers_team_question() -> None:
    from bot.lore import Lore

    lore = Lore(
        teams={
            "rules": ["常规配队：双C + 波鲁杰克斯 + 织夜鹿"],
            "elements": {"火": ["甲", "乙"]},
        }
    )
    facts = lore.facts_for("火系怎么配队")
    assert facts is not None
    assert "火系主C：甲、乙" in facts


def test_lore_answers_pal_build() -> None:
    from bot.lore import Lore

    lore = Lore(
        teams={
            "builds": [
                {
                    "pal": "丙龙",
                    "traits": ["沉着冷静", "不死之身"],
                    "skills": ["甲技能", "乙技能"],
                    "note": "打高难用",
                }
            ]
        }
    )
    facts = lore.facts_for("丙龙怎么配")
    assert facts is not None
    assert "沉着冷静" in facts and "甲技能" in facts


def test_lore_ignores_team_data_for_normal_questions() -> None:
    from bot.lore import Lore

    lore = Lore(teams={"roles": [{"role": "主C", "pals": ["甲"]}]})
    assert lore.facts_for("帕鲁球几级解锁") is None


# ---------------- 当天记忆 ----------------

def test_memory_keeps_within_day_and_resets_across_days() -> None:
    import tempfile

    from bot.memory import Memory

    path = tempdir() / "memory.json"
    state = {"day": "2026-01-01"}

    def clock() -> str:
        return state["day"]

    memory = Memory(path, turns=2, clock=clock)
    memory.remember("p1", "第一句", "回一")
    assert len(memory.history("p1")) == 2

    # 同一天重启：还在
    again = Memory(path, turns=2, clock=clock)
    assert len(again.history("p1")) == 2

    # 跨天：清空
    state["day"] = "2026-01-02"
    assert again.history("p1") == []


def test_memory_caps_turns_per_player() -> None:
    import tempfile

    from bot.memory import Memory

    path = tempdir() / "memory.json"
    memory = Memory(path, turns=1, clock=lambda: "2026-01-01")
    for index in range(5):
        memory.remember("p1", f"问题{index}", f"回答{index}")
    history = memory.history("p1")
    assert len(history) == 2
    assert history[0]["content"] == "问题4"


# ---------------- 报时 ----------------

def _stamp(hour: int, minute: int, second: int = 0) -> float:
    import time as _time

    return _time.mktime((2026, 1, 1, hour, minute, second, 0, 0, -1))


def test_clock_fires_on_boundary() -> None:
    from bot.clock import Clock

    clock = Clock(30, ["{time} {period}"])
    clock._next = _stamp(14, 30)
    assert clock.due(_stamp(14, 30, 1)) == "14:30 半点"
    assert clock.due(_stamp(14, 30, 2)) is None


def test_clock_skips_long_missed_slot() -> None:
    from bot.clock import Clock

    clock = Clock(30, ["{time}"])
    clock._next = _stamp(14, 30)
    assert clock.due(_stamp(15, 40)) is None


def test_clock_aligns_to_half_hour() -> None:
    from bot.clock import Clock

    clock = Clock(30)
    assert clock._next_boundary(_stamp(14, 10)) == _stamp(14, 30)
    assert clock._next_boundary(_stamp(14, 45)) == _stamp(15, 0)


def test_reasoning_model_detection() -> None:
    from bot.deepseek import _is_reasoning_model

    assert _is_reasoning_model("deepseek-v4-pro")
    assert _is_reasoning_model("deepseek-reasoner")
    assert not _is_reasoning_model("deepseek-flash")
    assert not _is_reasoning_model("deepseek-chat")


def test_guard_catches_invented_pal_names() -> None:
    from bot.guard import unknown_names

    names = ["猫蝠怪", "严冬鹿", "雷鸣鸟", "燎火鹿", "阿努比斯"]
    reply = "前排用寒空蝠或霜角鹿，输出用雷鸣鸟顶上"
    suspects = unknown_names(reply, names)
    assert "寒空蝠" in suspects
    assert "霜角鹿" in suspects
    assert "雷鸣鸟" not in suspects


def test_guard_allows_real_names_and_plain_text() -> None:
    from bot.guard import unknown_names

    names = ["雷鸣鸟", "阿努比斯"]
    assert unknown_names("雷鸣鸟配阿努比斯，带个前排就行", names) == []
    assert unknown_names("记不清 图鉴里翻", names) == []


def test_partner_skill_classification() -> None:
    """伙伴技能要分清"给队伍"和"只给自己/刷素材"。"""
    from bot.partner import classify

    assert classify("若它在队伍中，火属性帕鲁的攻击力会提升(15~30)%。（不可叠加）") == "攻击增益"
    assert classify("玩家和帕鲁以水属性攻击克制的属性时伤害提升(25~40)%。（不可叠加）") == "克制增伤"
    assert classify("发动后便能通过疗愈能力，为玩家和队伍内的帕鲁恢复(80~90)%的生命值。") == "治疗"
    assert classify("可骑在它的背上移动。骑乘期间破坏岩石的效率将提升(500~2000)%。") == "骑乘采集"
    assert classify("可骑在它的背上在空中飞行。飞行时移动速度会提升。") == "坐骑"
    assert classify("若它在队伍中，击倒暗属性帕鲁时获得的掉落道具增加(40~80)%。") == "掉落加成"


def test_partner_skill_ride_is_not_support() -> None:
    from bot.partner import SUPPORT_ROLES

    assert "坐骑" not in SUPPORT_ROLES
    assert "掉落加成" not in SUPPORT_ROLES
    assert "治疗" in SUPPORT_ROLES


def test_paldex_team_materials_uses_real_names() -> None:
    dex = sample_dex()
    text = dex.team_materials("火系配队")
    assert text is not None
    assert "主C候选" in text
    assert "只能从上面这些名字里选" in text


def test_paldex_team_materials_only_for_team_questions() -> None:
    assert sample_dex().team_materials("帕鲁球几级解锁") is None


# ---------------- 提问里提到的帕鲁全都要给资料 ----------------

def test_paldex_injects_every_mentioned_pal() -> None:
    dex = sample_dex()
    facts = dex.facts_for("甲帕鲁和乙哪个更值得练")
    assert facts is not None
    assert "甲" in facts
    assert "乙" in facts
    assert facts.count("- ") >= 2


def test_paldex_still_works_with_single_pal() -> None:
    dex = sample_dex()
    facts = dex.facts_for("甲帕鲁的工作适应性")
    assert facts is not None
    assert facts.count("- ") == 1


# ---------------- 属性克制 ----------------

def loaded_elements():
    from bot.elements import Elements

    elements = Elements.load(Path(__file__).resolve().parents[1] / "data" / "elements.json")
    assert elements is not None, "data/elements.json 没读到"
    return elements


def test_elements_chain_and_weakness() -> None:
    elements = loaded_elements()
    assert elements.beats("火") == ["草", "冰"]
    assert elements.beaten_by("雷") == ["地"]
    assert elements.beaten_by("暗") == ["龙"]


def test_elements_multiplier_single_and_dual() -> None:
    elements = loaded_elements()
    assert elements.multiplier("水", ["火"]) == 2.0
    assert elements.multiplier("雷", ["地"]) == 0.5
    assert elements.multiplier("雷", ["草"]) == 1.0
    # 双属性连乘：火打草+冰 = 2×2 = 4
    assert elements.multiplier("火", ["草", "冰"]) == 4.0


def test_elements_facts_answer_questions() -> None:
    elements = loaded_elements()
    text = elements.facts_for("雷系怕什么")
    assert text is not None and "地" in text
    text2 = elements.facts_for("火克什么")
    assert text2 is not None and "草" in text2 and "冰" in text2


def test_team_materials_uses_counter_element() -> None:
    from bot.elements import Elements

    chain = {
        "火": ["草", "冰"],
        "草": ["地"],
        "地": ["雷"],
        "雷": ["水"],
        "水": ["火"],
        "冰": ["龙"],
        "龙": ["暗"],
        "暗": ["无"],
        "无": [],
    }
    text = sample_dex().team_materials("打雷系配队", Elements(chain))
    assert text is not None
    assert "地系" in text


def test_guard_ignores_ordinary_words() -> None:
    """「本身龙」「傻鱼」这类普通词不能被当成编造的帕鲁名。"""
    from bot.guard import unknown_names

    names = ["灵曦龙", "雷鸣鸟"]
    assert unknown_names("灵曦龙本身龙属性，配个前排", names) == []
    assert unknown_names("你个傻鱼", names) == []
    assert unknown_names("灵曦龙不错", names) == []


def test_partner_level_range_uses_first_range_only() -> None:
    """区间 = 1级~5级；只取第一处，别把后面的工作效率数值混进来。"""
    from bot.partner import level_range

    assert level_range("无属性帕鲁的攻击力会提升(15~30)%。（不可叠加）") == (15, 30)
    assert level_range(
        "玩家和帕鲁以草属性攻击克制的属性时伤害提升(25~40)%。"
        "艾小兔在工作时工作效率将会提升(200~400)%。"
    ) == (25, 40)
    assert level_range("发动后，冲浪鸭会乘着浪头冲向敌人。") == (0, 0)


def test_partner_synergy_prefers_level5_value() -> None:
    from bot.partner import max_percent, synergy

    desc = "若它在队伍中，无属性帕鲁的攻击力会提升(15~30)%。（不可叠加）"
    assert max_percent(desc) == 30
    score, reason = synergy(desc, "无", "攻击增益")
    assert score > 1.5
    assert "30%" in reason and "5级" in reason


def test_partner_skill_can_have_multiple_effects() -> None:
    """一条伙伴技能可能同时有队伍增益和据点工作增益，都要解析出来。"""
    from bot.partner import effects

    desc = (
        "若它在队伍中，玩家和帕鲁以草属性攻击克制的属性时伤害提升(25~40)%。（不可叠加）"
        "艾小兔在武器制作台或武器工厂等处工作时，工作效率将会提升(200~400)%。"
    )
    got = effects(desc)
    roles = {item["role"]: item for item in got}
    assert "克制增伤" in roles and "工作加成" in roles
    assert roles["克制增伤"]["lv5"] == 40
    assert roles["工作加成"]["lv5"] == 400


def test_model_recommend_prefers_flash() -> None:
    from bot.models import recommend

    assert recommend(["deepseek-v4-pro", "deepseek-flash"]) == "deepseek-flash"
    assert recommend(["deepseek-v4-pro"]) == "deepseek-v4-pro"


def test_list_models_requires_key() -> None:
    from bot.models import list_models

    try:
        list_models("")
    except RuntimeError as exc:
        assert "API Key" in str(exc)
    else:
        raise AssertionError("空 Key 应该报错")


def test_fields_render_only_on_keyword() -> None:
    from bot.fields import FieldSpec, render

    specs = {"spawn": FieldSpec(key="spawn", label="刷新位置", keywords=["在哪", "抓"])}
    extra = {"spawn": "雪山地带"}
    assert render(extra, "覆海龙在哪抓", specs) == ["刷新位置 雪山地带"]
    assert render(extra, "覆海龙攻击多少", specs) == []
    assert render({"spawn": ""}, "覆海龙在哪抓", specs) == []


def test_housekeeping_removes_old_logs() -> None:
    import os
    import tempfile
    import time

    from bot.housekeeping import cleanup_logs

    base = tempdir()
    old = base / "old.log"
    old.write_text("x", encoding="utf-8")
    stale = time.time() - 30 * 86400
    os.utime(old, (stale, stale))
    fresh = base / "new.log"
    fresh.write_text("x", encoding="utf-8")

    removed = cleanup_logs(base, keep_days=7, keep_files=40)
    assert removed == 1
    assert not old.exists()
    assert fresh.exists()


def test_csv_import_builds_patches() -> None:
    import tempfile

    from bot.csv_import import read_csv, to_patches, write_overrides

    base = tempdir()
    csv_path = base / "pals.csv"
    csv_path.write_text(
        "name,spawn,capture\n覆海龙,雪山地带,约 8%\n雷鸣鸟,,约 5%\n",
        encoding="utf-8-sig",
    )
    rows = read_csv(csv_path)
    assert rows[0] == {"name": "覆海龙", "spawn": "雪山地带", "capture": "约 8%"}
    assert rows[1] == {"name": "雷鸣鸟", "capture": "约 5%"}  # 空值被跳过

    patches = to_patches(rows)
    target = write_overrides(base / "overrides", "paldex.json", patches)
    assert target.is_file()
    assert "覆海龙" in target.read_text(encoding="utf-8")


def test_modinstall_noop_when_already_registered() -> None:
    """已装好且已注册时，install 不该碰任何文件。"""
    import tempfile

    from bot import modinstall

    base = tempdir()
    server = base / "server"
    ue4ss = server / "Pal" / "Binaries" / "Win64" / "ue4ss"
    scripts = ue4ss / "Mods" / "PalChatRelay" / "Scripts"
    scripts.mkdir(parents=True)
    mods_txt = ue4ss / "Mods" / "mods.txt"
    mods_txt.write_text("PalChatRelay : 1\n", encoding="utf-8")

    source = base / "source"
    (source / "Mods" / "PalChatRelay" / "Scripts").mkdir(parents=True)
    lua = "print('hi')\n"
    (scripts / "main.lua").write_text(lua, encoding="utf-8")
    (source / "Mods" / "PalChatRelay" / "Scripts" / "main.lua").write_text(lua, encoding="utf-8")

    before = mods_txt.read_bytes()
    status = modinstall.detect(server, source)
    assert status.mod_current and status.registered and status.ready

    actions = modinstall.install(server, source)
    assert mods_txt.read_bytes() == before
    assert any("已是最新" in action for action in actions)


def test_has_element_dps_accepts_any_matching_pal() -> None:
    """只有主C要同属性；被动位是别的属性不算错。"""
    dex = sample_dex()
    assert dex.has_element_dps("主C用甲", "火")
    assert dex.has_element_dps("甲配乙当辅助", "火")
    assert not dex.has_element_dps("主C用乙", "火")


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc or '断言失败'}")
        else:
            print(f"ok   {test.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    for path in _TEMP_DIRS:
        shutil.rmtree(path, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
