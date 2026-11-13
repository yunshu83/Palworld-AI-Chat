"""从 palworlddb.com 抓科技树（等级 / 科技点 / 描述）。

说明：
  * 只读公开页面 /zh-Hans/technology-tree，不碰任何 API；
  * 该站 robots 的 content signals 是 search=yes, ai-train=no, use=reference，
    ai-input 未声明。这里只做"查资料"用途，不做训练。
  * 页面里没有逐条材料清单（材料写在各自的物品页），所以这里只收等级/科技点/描述。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://palworlddb.com"
PAGE = f"{BASE}/zh-Hans/technology-tree"
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw_extra" / "tech_tree.html"
OUT = ROOT / "data" / "tech.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PalBot/0.1"}

LEVEL = re.compile(r'aria-label="等级(\d+)"')
CARD = re.compile(
    r'<div title="(?P<desc>[^"]*)" class="card-hover[^"]*">\s*'
    r'<span aria-label="科技点数: (?P<points>\d+)"[^>]*>[^<]*</span>\s*'
    r'<img[^>]*alt="(?P<name>[^"]*)"'
)


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=40) as response:
        return response.read().decode("utf-8", "replace")


def parse(html: str) -> list[dict]:
    levels = [(match.start(), int(match.group(1))) for match in LEVEL.finditer(html)]
    techs: list[dict] = []
    seen: set[tuple[str, int]] = set()

    for match in CARD.finditer(html):
        name = match.group("name").strip()
        if not name:
            continue
        level = 0
        for position, value in levels:
            if position < match.start():
                level = value
            else:
                break
        key = (name, level)
        if key in seen:
            continue
        seen.add(key)
        techs.append(
            {
                "name": name,
                "level": level,
                "points": int(match.group("points")),
                "desc": " ".join(match.group("desc").split())[:120],
            }
        )
    return techs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    RAW.parent.mkdir(parents=True, exist_ok=True)
    if RAW.is_file() and not args.refresh and RAW.stat().st_size > 10000:
        html = RAW.read_text(encoding="utf-8", errors="replace")
    else:
        html = fetch(PAGE)
        RAW.write_text(html, encoding="utf-8")
        time.sleep(0.5)

    techs = parse(html)
    if not techs:
        print("一条科技都没解析出来，页面结构可能变了", file=sys.stderr)
        return 1

    payload = {
        "source": PAGE,
        "count": len(techs),
        "techs": techs,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    levels = sorted({item["level"] for item in techs})
    print(f"科技 {len(techs)} 条，覆盖等级 {levels[0]}~{levels[-1]}")
    print(f"写入 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
