"""DeepSeek 调用（OpenAI 兼容接口），只用标准库 urllib。"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .settings import DeepSeekConfig


class DeepSeekError(RuntimeError):
    pass


@dataclass
class Usage:
    """一次调用的用量。

    total 是接口给的 total_tokens（含缓存命中的部分）；
    billed 是"按钱算"的口径：缓存未命中 + 输出。预算按 billed 扣，
    否则光是稳定的人设前缀就会把预算吃掉，实际却没花那么多钱。
    """

    total: int = 0
    cached: int = 0
    billed: int = 0

    def __str__(self) -> str:
        if self.cached:
            return f"{self.total} tokens（缓存命中 {self.cached}，计费口径 {self.billed}）"
        return f"{self.total} tokens"


def usage_from(payload_usage: dict) -> Usage:
    """把接口返回的 usage 字段换算成可读、可记账的用量。"""
    data = payload_usage if isinstance(payload_usage, dict) else {}
    prompt_tokens = int(data.get("prompt_tokens") or 0)
    completion_tokens = int(data.get("completion_tokens") or 0)
    total = int(data.get("total_tokens") or (prompt_tokens + completion_tokens))
    cached = int(data.get("prompt_cache_hit_tokens") or 0)
    missed = int(data.get("prompt_cache_miss_tokens") or max(0, prompt_tokens - cached))
    billed = missed + completion_tokens if (cached or missed) else total
    return Usage(total=total, cached=cached, billed=billed)


def _is_reasoning_model(model: str) -> bool:
    name = (model or "").lower()
    return "pro" in name or "reasoner" in name


def _retryable(message: str) -> bool:
    """只有"可能自己好"的错误才值得重试，Key 错了重试多少次都没用。"""
    if "网络错误" in message or "超时" in message:
        return True
    if message.startswith("HTTP 5"):
        return True
    return "HTTP 429" in message


class DeepSeekClient:
    def __init__(self, cfg: DeepSeekConfig) -> None:
        self.cfg = cfg
        if not cfg.api_key:
            raise DeepSeekError(
                "没有 DeepSeek API Key：请设置环境变量 DEEPSEEK_API_KEY，"
                "或把 config.toml 里的 [deepseek].api_key 填上。"
            )

    def chat(self, messages: list[dict]) -> tuple[str, Usage]:
        """返回 (回复文本, 用量)。网络抖动/5xx 自动重试一次。"""
        last_error: DeepSeekError | None = None
        for attempt in (1, 2):
            try:
                return self._request(messages)
            except DeepSeekError as exc:
                last_error = exc
                if attempt == 2 or not _retryable(str(exc)):
                    raise
                time.sleep(1.5)
        raise last_error or DeepSeekError("未知错误")

    def _request(self, messages: list[dict]) -> tuple[str, Usage]:
        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "max_tokens": self.cfg.max_tokens,
            "temperature": self.cfg.temperature,
            "stream": False,
        }
        # 这些模型都会"先想一想"：思考会吃掉 max_tokens，正文直接空掉。
        # 实测 deepseek-flash 现在也带推理了，所以不再按名字判断，统一按开关来。
        # 游戏里要的是短回复，默认关掉思考。
        if not self.cfg.thinking:
            payload["thinking"] = {"type": "disabled"}
        request = urllib.request.Request(
            url=self.cfg.base_url + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {self.cfg.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.cfg.timeout) as response:
                body = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise DeepSeekError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise DeepSeekError(f"网络错误: {exc.reason}") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise DeepSeekError("请求超时") from exc

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise DeepSeekError(f"返回不是 JSON: {body[:200]}") from exc

        choices = data.get("choices") or []
        if not choices:
            raise DeepSeekError(f"返回里没有 choices: {body[:200]}")
        content = (choices[0].get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
        return content.strip(), usage_from(usage)
