"""--doctor：把每条链路单独体检一遍，告诉你卡在哪一段。

不启动机器人、不消耗 token（DeepSeek 只调 /models，不调聊天接口）。
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

from .settings import Config

OK, WARN, FAIL = "ok", "warn", "fail"
_ICON = {OK: "✓", WARN: "!", FAIL: "✗"}


class Check:
    def __init__(self, name: str, status: str, detail: str = "", fix: str = "") -> None:
        self.name = name
        self.status = status
        self.detail = detail
        self.fix = fix


def mask_key(key: str) -> str:
    if not key:
        return "（空）"
    if len(key) <= 10:
        return key[:2] + "****"
    return f"{key[:6]}****{key[-4:]}"


def _get_json(url: str, headers: dict, timeout: float = 6.0):
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", "replace")
        return response.status, body


def check_config(cfg: Config) -> Check:
    return Check("配置", OK, str(cfg.path))


def check_persona(cfg: Config) -> Check:
    length = len(cfg.persona)
    estimate = int(length * 0.6)  # 中文大约 0.6 token/字，够估量级
    facts = len(getattr(cfg, "facts", "") or "")
    detail = f"{length} 字"
    if facts:
        detail += f" + 事实 {facts} 字"
    detail += f"，约 {estimate + int(facts * 0.6)} tokens/次"
    if length < 200:
        return Check("人设", WARN, detail + "（太短，容易退化成客服腔）", "至少保留说话铁律和雷点")
    if length > 2000:
        return Check(
            "人设",
            WARN,
            detail,
            "人设越长每次越贵；DeepSeek 会自动缓存相同前缀，但首次和改动后仍按原价计",
        )
    return Check("人设", OK, detail)


def check_rules(cfg: Config) -> Check:
    replies = sum(len(rule.replies) for rule in cfg.preset.rules)
    if not cfg.trigger.ai_keywords and not cfg.trigger.command_prefix:
        return Check(
            "触发规则",
            FAIL,
            "既没有 ai_keywords 也没有 command_prefix",
            "至少留一个，否则永远不会调用 DeepSeek",
        )
    detail = (
        f"{len(cfg.trigger.ai_keywords)} 个关键词 / "
        f"{len(cfg.preset.rules)} 条预设（{replies} 句）"
    )
    if not cfg.preset.enabled:
        detail += "，预设已关闭"
    return Check("触发规则", OK, detail)


def check_deepseek_key(cfg: Config) -> Check:
    if not cfg.deepseek.api_key:
        return Check(
            "DeepSeek Key",
            FAIL,
            "没读到",
            "设置环境变量 DEEPSEEK_API_KEY，或填 config.toml 的 [deepseek].api_key",
        )
    return Check("DeepSeek Key", OK, mask_key(cfg.deepseek.api_key))


def check_deepseek_api(cfg: Config) -> Check:
    if not cfg.deepseek.api_key:
        return Check("DeepSeek 接口", WARN, "没有 Key，跳过")
    url = cfg.deepseek.base_url + "/models"
    try:
        status, body = _get_json(url, {"Authorization": f"Bearer {cfg.deepseek.api_key}"})
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return Check("DeepSeek 接口", FAIL, f"HTTP {exc.code}（Key 无效或无权限）", "去 platform.deepseek.com 重新建一个")
        return Check("DeepSeek 接口", FAIL, f"HTTP {exc.code}", "检查 base_url 是否正确")
    except Exception as exc:
        return Check("DeepSeek 接口", FAIL, f"{type(exc).__name__}: {exc}", "检查网络 / 代理")

    models = []
    try:
        models = [item.get("id", "") for item in json.loads(body).get("data", [])]
    except (json.JSONDecodeError, AttributeError):
        pass
    detail = f"可用模型 {', '.join(m for m in models if m) or '（未返回列表）'}"
    if cfg.deepseek.model not in models and models:
        return Check(
            "DeepSeek 接口",
            OK,
            detail + f"（配置的 {cfg.deepseek.model} 不在列表里，但通常是有效别名）",
        )
    return Check("DeepSeek 接口", OK, detail)


def check_reply(cfg: Config) -> Check:
    transport = cfg.reply.transport
    if transport == "console":
        return Check("回复出口", WARN, "console（只打印，不发进游戏）", "接服务器时改成 rest 或 palladium")

    if transport == "rest":
        if not cfg.palworld_rest.admin_password:
            return Check("回复出口", FAIL, "rest 但没填 admin_password", "和 PalWorldSettings.ini 的 AdminPassword 保持一致")
        token = base64.b64encode(f"admin:{cfg.palworld_rest.admin_password}".encode("utf-8")).decode("ascii")
        url = cfg.palworld_rest.url + "/v1/api/info"
        try:
            status, body = _get_json(url, {"Authorization": f"Basic {token}"})
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                return Check("回复出口", FAIL, f"REST 拒绝认证（{url}）", "admin_password 和 ini 里的 AdminPassword 不一致")
            return Check("回复出口", FAIL, f"REST HTTP {exc.code}（{url}）", "确认 RESTAPIEnabled=True 且已重启服务器")
        except Exception as exc:
            return Check("回复出口", FAIL, f"连不上 REST {url}：{exc}", "确认服务器在跑、RESTAPIPort 一致、端口只开本机")
        try:
            info = json.loads(body)
            name = info.get("servername") or info.get("name") or "?"
        except json.JSONDecodeError:
            name = "?"
        return Check("回复出口", OK, f"REST 可用，服务器「{name}」")

    # palladium
    url = cfg.server.bridge_url + "/api/bridge/schema"
    headers = {}
    if cfg.server.bridge_token:
        headers["Authorization"] = f"Bearer {cfg.server.bridge_token}"
    try:
        status, body = _get_json(url, headers)
    except Exception as exc:
        return Check("回复出口", FAIL, f"连不上 Palladium {url}：{exc}", "确认面板在跑、bridge_url / token 正确")
    return Check("回复出口", OK, f"Palladium 桥可用（{len(body)} 字节 schema）")


def check_source(cfg: Config) -> Check:
    mode = cfg.server.mode
    if mode == "stdin":
        return Check("聊天来源", WARN, "stdin（手动输入，没接服务器）", "接服务器时改成 log")
    if mode == "log":
        return _check_log(cfg)
    if mode == "palladium":
        return _check_palladium_events(cfg)
    if mode == "tail":
        if not cfg.server.jsonl_path:
            return Check("聊天来源", FAIL, "tail 但没填 jsonl_path")
        if not os.path.exists(cfg.server.jsonl_path):
            return Check("聊天来源", FAIL, f"找不到 {cfg.server.jsonl_path}")
        return Check("聊天来源", OK, f"{os.path.getsize(cfg.server.jsonl_path)} 字节")
    return Check("聊天来源", FAIL, f"不认识的 mode：{mode}", "可选 stdin / log / palladium / tail")


def _check_log(cfg: Config) -> Check:
    path = cfg.server.log_path
    if not path:
        return Check("聊天来源", FAIL, "log 模式但没填 log_path", "填 UE4SS.log 的完整路径")
    if not os.path.exists(path):
        return Check("聊天来源", FAIL, f"找不到 {path}", "确认 UE4SS 已装好、路径是 …\\Pal\\Binaries\\Win64\\ue4ss\\UE4SS.log")
    size = os.path.getsize(path)
    hits = _tail_marker_hits(path, cfg.server.log_marker)
    if hits == 0:
        return Check(
            "聊天来源",
            WARN,
            f"{size} 字节，但最近没有 {cfg.server.log_marker} 行",
            "进游戏说句话再看；仍然没有，就是 main.lua 的钩子名和你版本对不上",
        )
    return Check("聊天来源", OK, f"{size} 字节，最近 {hits} 条 {cfg.server.log_marker} 记录")


def _tail_marker_hits(path: str, marker: str, window: int = 128 * 1024) -> int:
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - window))
            text = handle.read().decode("utf-8", "replace")
    except OSError:
        return 0
    return text.count(marker)


def _check_palladium_events(cfg: Config) -> Check:
    url = f"{cfg.server.bridge_url}/api/bridge/events?since=0&limit=1"
    headers = {}
    if cfg.server.bridge_token:
        headers["Authorization"] = f"Bearer {cfg.server.bridge_token}"
    try:
        status, body = _get_json(url, headers)
    except Exception as exc:
        return Check("聊天来源", FAIL, f"读不到事件：{exc}", "检查 bridge_url / token")
    return Check("聊天来源", OK, f"事件接口可用（{len(body)} 字节）")


def run_doctor(cfg: Config) -> int:
    checks = [
        check_config(cfg),
        check_persona(cfg),
        check_rules(cfg),
        check_deepseek_key(cfg),
        check_deepseek_api(cfg),
        check_reply(cfg),
        check_source(cfg),
    ]

    print("小鱼 · 链路自检\n")
    for check in checks:
        print(f"  {_ICON[check.status]} {check.name}：{check.detail}")
        if check.fix:
            print(f"      → {check.fix}")

    fails = sum(1 for check in checks if check.status == FAIL)
    warns = sum(1 for check in checks if check.status == WARN)
    print()
    if fails:
        print(f"{fails} 项必须修，{warns} 项提醒。修完再跑一次 --doctor。")
        return 1
    if warns:
        print(f"没有硬错误，{warns} 项提醒（多为还没接服务器）。可以先用 stdin 试跑。")
        return 0
    print("全部通过。可以 python run.py 了。")
    return 0
