"""聊天的事件源（读）和回复出口（写）。

支持三种读取方式：
  palladium  轮询 Palladium 桥接 /api/bridge/events?type=player.chat
  tail       直接读 bridge-events.jsonl（同一台机器上最省事，不走 HTTP）
  stdin      手动输入，用来在没服务器的情况下试跑

三种回复方式：
  palladium  POST /api/bridge/call  的 server.announce 或 player.message
  rest       官方 REST API POST /v1/api/announce（只能全服广播）
  console    只打印
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class ChatEvent:
    player_id: str
    player_name: str
    message: str
    at: float = 0.0


def _parse_event(raw: dict, event_type: str) -> ChatEvent | None:
    if not isinstance(raw, dict) or raw.get("type") != event_type:
        return None
    subject = raw.get("subject") or {}
    data = raw.get("data") or {}
    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        return None
    return ChatEvent(
        player_id=str(subject.get("id") or ""),
        player_name=str(subject.get("name") or "玩家"),
        message=message,
        at=float(raw.get("at") or 0.0),
    )


class PalladiumSource:
    """Palladium 桥接的事件轮询。cursor 是事件文件里的字节偏移。"""

    def __init__(self, base_url: str, token: str, event_type: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.event_type = event_type
        self.timeout = timeout
        self.cursor = 0
        self._warned = False

    def poll(self) -> list[ChatEvent]:
        url = (
            f"{self.base_url}/api/bridge/events"
            f"?since={self.cursor}&limit=200&type={self.event_type}"
        )
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except Exception as exc:  # 网络抖动不该让机器人退出
            if not self._warned:
                print(f"[events] 读取失败，会继续重试：{exc}", file=sys.stderr)
                self._warned = True
            return []

        self._warned = False
        if not isinstance(payload, dict):
            return []
        cursor = payload.get("cursor")
        events = payload.get("events") or []
        parsed = [event for event in (_parse_event(item, self.event_type) for item in events) if event]
        if isinstance(cursor, int):
            if cursor < self.cursor:
                # 服务器重启后事件文件被清空，游标回到前面
                print("[events] 检测到事件游标回退（服务器可能重启过）", file=sys.stderr)
            self.cursor = cursor
        return parsed


class JsonlTailSource:
    """直接 tail bridge-events.jsonl，按字节偏移增量读。"""

    def __init__(self, path: str, event_type: str) -> None:
        self.path = path
        self.event_type = event_type
        self.offset = 0
        self._warned = False

    def poll(self) -> list[ChatEvent]:
        if not self.path:
            return []
        try:
            size = os.path.getsize(self.path)
        except OSError as exc:
            if not self._warned:
                print(f"[tail] 打不开 {self.path}：{exc}", file=sys.stderr)
                self._warned = True
            return []

        if size < self.offset:
            self.offset = 0
        if size == self.offset:
            return []

        try:
            with open(self.path, "rb") as handle:
                handle.seek(self.offset)
                chunk = handle.read(size - self.offset)
        except OSError as exc:
            print(f"[tail] 读取失败：{exc}", file=sys.stderr)
            return []

        self.offset += len(chunk)
        events: list[ChatEvent] = []
        for line in chunk.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line.decode("utf-8", "replace"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue  # 半行/坏行直接跳过
            event = _parse_event(raw, self.event_type)
            if event:
                events.append(event)
        return events


_TIMESTAMP = re.compile(r"\[\d{4}-\d{2}-\d{2}")


def _parse_segment(segment: str) -> ChatEvent | None:
    # UE4SS 的 Lua print 不带换行，下一条日志的时间戳会直接粘在内容后面，
    # 所以在这里把「[2026-11-04 ...]」切开。
    cut = _TIMESTAMP.search(segment)
    if cut:
        segment = segment[: cut.start()]
    payload = segment.strip()
    if not payload:
        return None
    name, _, message = payload.partition("\t")
    name = name.strip() or "玩家"
    message = message.strip()
    if not message:
        return None
    return ChatEvent(player_id=name, player_name=name, message=message)


def parse_relay_entries(line: str, marker: str) -> list[ChatEvent]:
    """一行里可能粘了多条 [PALBOT]（print 不换行时会出现），逐条解析。"""
    events: list[ChatEvent] = []
    for segment in line.split(marker)[1:]:
        event = _parse_segment(segment)
        if event:
            events.append(event)
    return events


def parse_relay_line(line: str, marker: str) -> ChatEvent | None:
    """解析 Lua mod 打印的一行：[PALBOT] 玩家名<TAB>内容。"""
    events = parse_relay_entries(line, marker)
    return events[0] if events else None


class MarkerLogSource:
    """tail UE4SS.log，只抓带 [PALBOT] 前缀的聊天行。

    不依赖任何 HTTP，UE4SS 自带 print 就能把聊天送出来，最省事也最不容易崩。
    """

    def __init__(self, path: str, marker: str = "[PALBOT]", skip_existing: bool = True) -> None:
        self.path = path
        self.marker = marker or "[PALBOT]"
        self.offset = 0
        self._buffer = ""
        self._warned = False
        self._skip_existing = skip_existing
        self._initialized = False

    def poll(self) -> list[ChatEvent]:
        if not self.path:
            return []
        try:
            size = os.path.getsize(self.path)
        except OSError as exc:
            if not self._warned:
                print(f"[log] 打不开 {self.path}：{exc}", file=sys.stderr)
                self._warned = True
            return []

        # 第一次运行时直接跳到文件末尾：历史聊天不该被重新回答一遍
        if not self._initialized:
            self._initialized = True
            if self._skip_existing:
                self.offset = size
                return []

        if size < self.offset:  # 服务器重启后日志被重写
            self.offset = 0
            self._buffer = ""
        if size == self.offset:
            return []

        try:
            with open(self.path, "rb") as handle:
                handle.seek(self.offset)
                chunk = handle.read(size - self.offset)
        except OSError as exc:
            print(f"[log] 读取失败：{exc}", file=sys.stderr)
            return []

        self.offset += len(chunk)
        self._buffer += chunk.decode("utf-8", "replace")
        if len(self._buffer) > 65536:  # 没有换行时别把内存撑爆
            self._buffer = self._buffer[-65536:]

        events: list[ChatEvent] = []
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            events.extend(parse_relay_entries(line, self.marker))
        return events


def decode_line(raw: bytes, fallback: str = "utf-8") -> str:
    """把一行字节解成字符串：先按 UTF-8，失败再退回本地编码。

    Windows 的坑：PowerShell 管道喂进来是 UTF-8，但 Python 的 sys.stdin
    默认按控制台代码页（中文是 cp936）解码，中文会变成「灏忔槑」这种乱码。
    """
    if raw.startswith(b"\xef\xbb\xbf"):  # 去掉 BOM
        raw = raw[3:]
    for encoding in ("utf-8", fallback):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


class StdinSource:
    """手动输入：一行 "玩家名: 内容"，空行忽略。"""

    def __init__(self, event_type: str = "player.chat") -> None:
        self.event_type = event_type
        self._fallback = getattr(sys.stdin, "encoding", None) or "utf-8"

    def _readline(self) -> str:
        stream = getattr(sys.stdin, "buffer", None)
        if stream is None or self._is_tty():
            return sys.stdin.readline()

        raw = stream.readline()
        if not raw:
            return ""
        return decode_line(raw, self._fallback)

    @staticmethod
    def _is_tty() -> bool:
        checker = getattr(sys.stdin, "isatty", None)
        try:
            return bool(checker()) if checker else False
        except (OSError, ValueError):
            return False

    def poll(self) -> list[ChatEvent]:
        try:
            line = self._readline()
        except KeyboardInterrupt:
            raise
        if not line:
            raise SystemExit(0)  # Ctrl+Z / 关闭输入
        line = line.strip()
        if not line:
            return []
        for separator in (":", "："):
            if separator in line:
                name, message = line.split(separator, 1)
                break
        else:
            name, message = "控制台", line
        return [
            ChatEvent(
                player_id=f"console:{name.strip()}",
                player_name=name.strip() or "控制台",
                message=message.strip(),
            )
        ]


class PalladiumSink:
    def __init__(self, base_url: str, token: str, timeout: float, private: bool) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.private = private

    def send(self, text: str, player_id: str = "") -> bool:
        if self.private and player_id:
            body = {"type": "player.message", "target": player_id, "data": {"message": text}}
        else:
            body = {"type": "server.announce", "data": {"message": text}}
        return self._post(body)

    def _post(self, body: dict) -> bool:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            self.base_url + "/api/bridge/call",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8", "replace") or "{}")
        except Exception as exc:
            print(f"[reply] 发送失败：{exc}", file=sys.stderr)
            return False
        if not isinstance(payload, dict):
            return True
        if payload.get("ok") is False:
            print(f"[reply] 游戏内执行失败：{payload.get('error')}", file=sys.stderr)
            return False
        return True


class RestSink:
    """官方 REST API 广播。注意：只能全服公告，不能只回给某个人。"""

    def __init__(self, base_url: str, admin_password: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.password = admin_password
        self.timeout = timeout

    def send(self, text: str, player_id: str = "") -> bool:
        token = base64.b64encode(f"admin:{self.password}".encode("utf-8")).decode("ascii")
        request = urllib.request.Request(
            self.base_url + "/v1/api/announce",
            data=json.dumps({"message": text}, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Basic {token}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response.read()
            return True
        except urllib.error.HTTPError as exc:
            print(f"[reply] REST 返回 {exc.code}（检查 AdminPassword 是否和 ini 里一致）", file=sys.stderr)
        except Exception as exc:
            print(f"[reply] REST 发送失败：{exc}", file=sys.stderr)
        return False


class ConsoleSink:
    def send(self, text: str, player_id: str = "") -> bool:
        print(f"[要发到游戏里] {text}")
        return True
