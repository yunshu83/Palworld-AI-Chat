"""拉取账号可用的模型列表，供向导让用户选择。

DeepSeek 的 /models 接口返回 OpenAI 兼容结构：{"data": [{"id": "..."}]}。
不同账号开放的模型可能不同，所以不能写死。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

DEFAULT_BASE = "https://api.deepseek.com"


def list_models(
    api_key: str, base_url: str = DEFAULT_BASE, timeout: float = 15.0
) -> list[str]:
    """返回可用模型 id 列表；失败抛 RuntimeError。"""
    key = (api_key or "").strip()
    if not key:
        raise RuntimeError("没有 API Key")

    request = urllib.request.Request(
        url=(base_url or DEFAULT_BASE).rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:160]
        except OSError:
            pass
        raise RuntimeError(f"HTTP {exc.code} {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"网络错误：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("返回的不是合法 JSON") from exc

    models = []
    for item in payload.get("data") or []:
        if isinstance(item, dict) and item.get("id"):
            models.append(str(item["id"]))
    if not models:
        raise RuntimeError("/models 返回为空")
    return models


def recommend(models: list[str]) -> str:
    """优先挑便宜的那档（名字带 flash），否则退回第一个。"""
    for model in models:
        if "flash" in model.lower():
            return model
    return models[0]
