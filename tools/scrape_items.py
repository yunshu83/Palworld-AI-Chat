"""抓物品页的制作材料，并把材料清单合并进 data/tech.json。

来源：palworlddb.com 的 /zh-Hans/item/<slug> 页面（公开页面，遵守 robots：
search=yes, ai-train=no, use=reference；不碰任何 API）。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import http.client
import json
import re
import sys
import threading
import time
from pathlib import Path

BASE = "https://palworlddb.com"
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw_extra"
ITEMS_OUT = ROOT / "data" / "items.json"
TECH_FILE = ROOT / "data" / "tech.json"
LIST_FILE = RAW / "items_list.html"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PalBot/0.1"}
DELAY = 0.4

H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
ITEM_LINK = re.compile(r'href="(/zh-Hans/item/[^"#]+)"')
MAT_SECTION = re.compile(r">材料</h2>(.*?)</ul>", re.S)
LI = re.compile(r"<li>(.*?)</li>", re.S)
ALT = re.compile(r'alt="([^"]+)"')
QTY = re.compile(r"×<!-- -->(\d+)")


_LOCAL = threading.local()


def _connection() -> http.client.HTTPSConnection:
    """每个线程复用自己的一条连接：这个站 TLS 握手很慢，复用后快得多。"""
    conn = getattr(_LOCAL, "conn", None)
    if conn is None:
        conn = http.client.HTTPSConnection("palworlddb.com", timeout=25)
        _LOCAL.conn = conn
    return conn


def get(url: str, tries: int = 3) -> str:
    path = url.replace(BASE, "") or "/"
    last: Exception | None = None
    for attempt in range(tries):
        try:
            connection = _connection()
            connection.request("GET", path, headers={**HEADERS, "Connection": "keep-alive"})
            response = connection.getresponse()
            body = response.read().decode("utf-8", "replace")
            if response.status == 404:
                raise LookupError("404")
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
            return body
        except LookupError:
            raise
        except Exception as exc:
            last = exc
            try:
                _LOCAL.conn.close()
            except Exception:
                pass
            _LOCAL.conn = None
            time.sleep(1 + attempt)
    raise last or RuntimeError("unknown")


def cached(url: str, name: str) -> str:
    path = RAW / f"{name}.html"
    if path.is_file() and path.stat().st_size > 1000:
        return path.read_text(encoding="utf-8", errors="replace")
    html = get(url)
    path.write_text(html, encoding="utf-8")
    time.sleep(DELAY)
    return html


def parse_item(html: str) -> dict | None:
    name_match = H1.search(html)
    if not name_match:
        return None
    name = re.sub(r"<[^>]+>", "", name_match.group(1)).strip()
    if not name:
        return None

    materials: list[dict] = []
    section = MAT_SECTION.search(html)
    if section:
        for block in LI.findall(section.group(1)):
            alt = ALT.search(block)
            qty = QTY.search(block)
            if not alt:
                continue
            materials.append({"name": alt.group(1).strip(), "qty": int(qty.group(1)) if qty else 0})
    return {"name": name, "materials": materials}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--workers", type=int, default=3, help="并发线程数，这个站握手慢，3 左右合适")
    args = parser.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    if LIST_FILE.is_file() and not args.refresh and LIST_FILE.stat().st_size > 10000:
        listing = LIST_FILE.read_text(encoding="utf-8", errors="replace")
    else:
        listing = get(f"{BASE}/zh-Hans/items")
        LIST_FILE.write_text(listing, encoding="utf-8")

    paths = sorted(set(ITEM_LINK.findall(listing)))
    print(f"物品页 {len(paths)} 个，并发 {args.workers}", flush=True)

    items: list[dict] = []

    def work(path: str):
        slug = path.rsplit("/", 1)[-1]
        try:
            html = cached(BASE + path, f"item_{slug}")
        except Exception as exc:
            return slug, None, f"{type(exc).__name__}: {exc}"
        return slug, parse_item(html), None

    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for slug, item, error in pool.map(work, paths):
            done += 1
            if error:
                print(f"{slug} 抓取失败: {error}", file=sys.stderr, flush=True)
            elif item:
                items.append(item)
            if done % 10 == 0:
                print(f"{done}/{len(paths)}", flush=True)

    ITEMS_OUT.write_text(
        json.dumps({"source": f"{BASE}/zh-Hans/item/", "items": items}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    with_materials = sum(1 for item in items if item["materials"])
    print(f"物品 {len(items)} 条，其中有配方 {with_materials} 条")

    if TECH_FILE.is_file():
        tech = json.loads(TECH_FILE.read_text(encoding="utf-8"))
        recipes = {item["name"]: item["materials"] for item in items if item["materials"]}
        matched = 0
        for entry in tech.get("techs") or []:
            materials = recipes.get(entry["name"])
            if materials:
                entry["materials"] = materials
                matched += 1
        TECH_FILE.write_text(json.dumps(tech, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"科技 {len(tech.get('techs') or [])} 条，其中 {matched} 条对上了材料清单")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
