"""抓取 paldb.cn 的帕鲁工作适应性，生成 data/paldex.json。

遵守站点 robots.txt：
  * 允许 /pals/... 页面——本脚本只读这些页面；
  * 明确禁止 /api/——本脚本不碰任何 API 路由。

抓到的原始 HTML 会缓存到 data/raw/，重复运行不会重复请求。
用法：
    python tools/scrape_paldb.py --limit 3     # 先验证解析
    python tools/scrape_paldb.py               # 全量
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

BASE = "https://paldb.cn"
ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUT_FILE = ROOT / "data" / "paldex.json"

HEADERS = {
    "User-Agent": "PalBot/0.1 (personal Palworld server bot; contact: server owner)",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
DELAY_SECONDS = 0.5

# 站点上的中文叫法 → paldex.json 的内部键
WORK_MAP = {
    "生火": "kindling",
    "点火": "kindling",
    "浇水": "watering",
    "播种": "planting",
    "种植": "planting",
    "发电": "generating_electricity",
    "手工作业": "handiwork",
    "手工": "handiwork",
    "采集": "gathering",
    "伐木": "lumbering",
    "砍伐": "lumbering",
    "采矿": "mining",
    "采掘": "mining",
    "制药": "medicine_production",
    "药剂": "medicine_production",
    "冷却": "cooling",
    "搬运": "transporting",
    "牧场": "farming",
    "农活": "farming",
}

WORK_BLOCK = re.compile(
    r'text-gray-300 text-xs">([^<]+)</div></div>'
    r'<div class="text-blue-400 font-bold text-sm">Lv <!-- -->(\d+)'
)
H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
NUMBER = re.compile(r"#<!-- -->(\d+)")
TITLE = re.compile(r"<title>([^<]*)</title>")
SLUG = re.compile(r'href="(/pals/[^"]+)"')
CJK = re.compile(r"[\u4e00-\u9fff]+")

# 基础属性：<span class="text-gray-400">HP</span><span class="text-white font-bold">120</span>
STAT = re.compile(
    r'<span class="text-gray-400">(HP|攻击|防御|工作速度)</span>'
    r'<span class="text-white font-bold">([\d,]+)'
)
# 移动能力：多一个 text-sm
MOVE = re.compile(
    r'<span class="text-gray-400 text-sm">(行走|奔跑|游泳|耐力)</span>'
    r'<span class="text-white font-bold text-sm">([\d,]+)'
)
# 80 级属性范围：5700<!-- --> - <!-- -->7140
RANGE80 = re.compile(
    r'<span class="text-gray-400 text-sm">(HP|攻击|防御)</span>'
    r'<span class="text-white font-bold text-sm">([\d,]+)<!-- --> - <!-- -->([\d,]+)'
)
# 掉落表：物品名 / 数量 / 概率
DROP = re.compile(
    r'<span class="text-white text-sm">([^<]+)</span></div></td>'
    r'<td[^>]*>([^<]*)</td><td[^>]*>([^<]*)</td>'
)
# 主动技能：<a ... href="/skills/Stone_Blast"> ... <h4 ...>碎石霰弹</h4>
ACTIVE_SKILL = re.compile(r'<a class="[^"]*" href="/skills/([^"]+)">', re.S)
PASSIVE_SKILL = re.compile(
    r'<h4 class="font-bold text-sm" style="color:[^"]*">([^<]+)</h4>.*?'
    r'<p class="text-gray-300 text-s[^"]*"[^>]*>([^<]*)</p>',
    re.S,
)
PARTNER = re.compile(
    r'<h3[^>]*><div class="relative w-10 h-10">.*?alt="([^"]+)".*?</div>([^<]+)</h3>'
    r'.*?<p class="text-gray-300 text-sm mb-4">([^<]*)</p>',
    re.S,
)


def parse_elements(html: str) -> list[str]:
    """属性只出现在 <title> 里，形如「阿努比斯 - 地属性属性 | …」。"""
    match = TITLE.search(html)
    if not match:
        return []
    parts = match.group(1).split(" - ")
    if len(parts) < 2:
        return []
    raw = parts[1].split("|")[0].replace("属性", "").strip()
    elements: list[str] = []
    for chunk in CJK.findall(raw):
        if chunk not in elements:
            elements.append(chunk)
    return elements[:2]


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def cached_html(slug: str) -> str:
    path = RAW_DIR / f"{slug}.html"
    if path.is_file() and path.stat().st_size > 1000:
        return path.read_text(encoding="utf-8", errors="replace")
    html = fetch(f"{BASE}/pals/{slug}")
    path.write_text(html, encoding="utf-8")
    time.sleep(DELAY_SECONDS)
    return html


STAT_KEYS = {"HP": "hp", "攻击": "attack", "防御": "defense", "工作速度": "work_speed"}
MOVE_KEYS = {"行走": "walk", "奔跑": "run", "游泳": "swim", "耐力": "stamina"}


def parse_active_skills(html: str) -> list[dict]:
    skills: list[dict] = []
    seen: set[str] = set()
    anchors = list(ACTIVE_SKILL.finditer(html))
    for index, match in enumerate(anchors):
        # 切到下一个技能卡片为止，避免类型/属性串到别人身上
        end = anchors[index + 1].start() if index + 1 < len(anchors) else match.start() + 2000
        segment = html[match.start(): end]
        name = re.search(r"<h4[^>]*>([^<]+)</h4>", segment)
        if not name:
            continue
        title = name.group(1).strip()
        if not title or title in seen:
            continue
        element = re.search(r">([\u4e00-\u9fff]{1,3}属性)<", segment)
        kind = re.search(r">(远程|近战)<", segment)
        seen.add(title)
        skills.append(
            {
                "name": title,
                "element": element.group(1).replace("属性", "") if element else "",
                "type": kind.group(1) if kind else "",
            }
        )
    return skills


def parse_passive_skills(html: str) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for name, desc in PASSIVE_SKILL.findall(html):
        title = name.strip()
        if not title or title in seen:
            continue
        seen.add(title)
        out.append({"name": title, "desc": desc.strip()[:120]})
    return out


def parse(html: str, slug: str) -> dict | None:
    name_match = H1.search(html)
    name = name_match.group(1).strip() if name_match else ""
    if not name:
        return None

    work: dict[str, int] = {}
    for label, level in WORK_BLOCK.findall(html):
        key = WORK_MAP.get(label.strip())
        if key:
            work[key] = int(level)

    elements = parse_elements(html)

    stats = {STAT_KEYS[label]: int(value.replace(",", "")) for label, value in STAT.findall(html)}
    movement = {
        MOVE_KEYS[label]: int(value.replace(",", "")) for label, value in MOVE.findall(html)
    }
    stats80 = {
        STAT_KEYS[label]: f"{int(low.replace(',', ''))}-{int(high.replace(',', ''))}"
        for label, low, high in RANGE80.findall(html)
    }
    drops: list[dict] = []
    seen_drops: dict[str, dict] = {}
    for item, qty, rate in DROP.findall(html):
        title = item.strip()
        if not title:
            continue
        entry = {"name": title, "qty": qty.strip(), "rate": rate.strip()}
        previous = seen_drops.get(title)
        if previous is None:
            seen_drops[title] = entry
            continue
        # 同一物品会出现两次：普通掉落 + Lv.80 加成掉落。优先保留普通那条
        if previous["rate"].startswith("Lv.80") and not entry["rate"].startswith("Lv.80"):
            seen_drops[title] = entry
    drops = list(seen_drops.values())

    partner: dict = {}
    partner_match = PARTNER.search(html)
    if partner_match:
        partner = {
            "name": partner_match.group(2).strip() or partner_match.group(1).strip(),
            "desc": partner_match.group(3).strip()[:200],
        }

    number = NUMBER.search(html)

    aliases = [slug.replace("_", " ")]
    if number:
        aliases.append(f"No.{number.group(1)}")

    return {
        "name": name,
        "aliases": aliases,
        "elements": elements,
        "work": work,
        "stats": stats,
        "movement": movement,
        "stats80": stats80,
        "drops": drops,
        "active_skills": parse_active_skills(html),
        "passive_skills": parse_passive_skills(html),
        "partner_skill": partner,
        "note": f"No.{number.group(1)}" if number else "",
    }


def list_slugs() -> list[str]:
    html = fetch(f"{BASE}/pals")
    slugs = []
    for match in SLUG.findall(html):
        slug = match.rsplit("/", 1)[-1]
        if slug and slug not in slugs:
            slugs.append(slug)
    return slugs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="只抓前 N 个，用于验证解析")
    parser.add_argument("--refresh", action="store_true", help="忽略缓存重新抓")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if args.refresh:
        for item in RAW_DIR.glob("*.html"):
            item.unlink()

    slugs = list_slugs()
    print(f"发现 {len(slugs)} 个帕鲁页面")
    if args.limit:
        slugs = slugs[: args.limit]

    pals = []
    failed = []
    for index, slug in enumerate(slugs, 1):
        try:
            pal = parse(cached_html(slug), slug)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            failed.append((slug, str(exc)))
            print(f"[{index}/{len(slugs)}] {slug} 失败: {exc}", file=sys.stderr)
            continue
        if pal is None:
            failed.append((slug, "解析不到名字"))
            continue
        pals.append(pal)
        if index % 20 == 0 or index == len(slugs):
            print(f"[{index}/{len(slugs)}] 已解析 {len(pals)} 个")

    data = {
        "version": time.strftime("paldb.cn@%Y-%m-%d"),
        "source": f"{BASE}/pals （页面数据，抓取于 {time.strftime('%Y-%m-%d')}）",
        "pals": pals,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    with_work = sum(1 for pal in pals if pal["work"])
    print(f"\n写入 {OUT_FILE}")
    print(f"帕鲁 {len(pals)} 个，其中有工作适应性数据 {with_work} 个，失败 {len(failed)} 个")
    if failed:
        for slug, reason in failed[:5]:
            print(f"  失败样例 {slug}: {reason}", file=sys.stderr)
    return 0 if pals else 1


if __name__ == "__main__":
    raise SystemExit(main())
