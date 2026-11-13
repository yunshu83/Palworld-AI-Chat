"""抓取 paldb.cn 的技能库、材料、传奇图纸。

遵守 robots.txt：只读公开页面，不碰 /api/。
抓到的页面缓存在 data/raw_extra/，重复运行不会重复请求。

用法：
    python tools/scrape_extra.py --only skills
    python tools/scrape_extra.py            # 全部
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
RAW_DIR = ROOT / "data" / "raw_extra"
DATA_DIR = ROOT / "data"

HEADERS = {
    "User-Agent": "PalBot/0.1 (personal Palworld server bot; contact: server owner)",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
DELAY = 0.5

H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
META_DESC = re.compile(r'<meta name="description" content="([^"]*)"')
# 幻兽帕鲁毒雾技能详情。暗属性远程技能，威力0，冷却30秒。描述…
SKILL_DESC = re.compile(
    r"幻兽帕鲁(?P<name>.+?)技能详情。(?P<element>.+?)属性(?P<type>远程|近战)技能，"
    r"威力(?P<power>\d+)，冷却(?P<cooldown>\d+)秒。?(?P<desc>.*)",
    re.S,
)
MATERIAL_WEIGHT = re.compile(
    r'<span class="text-gray-400 text-sm">重量</span>'
    r'<span class="text-white font-medium text-sm">([\d,]+)'
)
MATERIAL_STACK = re.compile(
    r'<span class="text-gray-400 text-sm">最大堆叠数</span>'
    r'<span class="text-white font-medium text-sm">([\d,]+)'
)
SCHEMATIC_NAME = re.compile(r'<h3 class="text-2xl font-bold z-10" style="color:[^"]*">([^<]+)</h3>')
QUALITY = re.compile(r'<span class="text-s font-medium">([^<]+)</span>')
LEGENDARY = ("传奇", "传说")


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=40) as response:
        return response.read().decode("utf-8", "replace")


def cached(url: str, name: str) -> str:
    path = RAW_DIR / f"{name}.html"
    if path.is_file() and path.stat().st_size > 500:
        return path.read_text(encoding="utf-8", errors="replace")
    html = fetch(url)
    path.write_text(html, encoding="utf-8")
    time.sleep(DELAY)
    return html


def sitemap_urls() -> list[str]:
    xml = fetch(f"{BASE}/sitemap.xml")
    return re.findall(r"<loc>([^<]+)</loc>", xml)


def parse_skill(html: str, slug: str) -> dict | None:
    meta = META_DESC.search(html)
    name_match = H1.search(html)
    name = (name_match.group(1).strip() if name_match else "") or slug.replace("_", " ")
    item = {"name": name, "element": "", "type": "", "power": None, "cooldown": None, "desc": ""}
    if meta:
        match = SKILL_DESC.search(meta.group(1))
        if match:
            item.update(
                element=match.group("element").strip(),
                type=match.group("type"),
                power=int(match.group("power")),
                cooldown=int(match.group("cooldown")),
                desc=match.group("desc").strip()[:160],
            )
        else:
            item["desc"] = meta.group(1)[:160]
    return item


def clean_material_desc(text: str) -> str:
    """素材页的 meta 里带站点套话，只留真正的描述。"""
    if not text:
        return ""
    if "详情攻略。" in text:
        text = text.split("详情攻略。", 1)[1]
    for stop in ("查看", "是Palworld"):
        index = text.find(stop)
        if index > 0:
            text = text[:index]
    return text.strip()[:160]


def parse_material(html: str, slug: str) -> dict | None:
    name_match = H1.search(html)
    if not name_match:
        return None
    meta = META_DESC.search(html)
    weight = MATERIAL_WEIGHT.search(html)
    stack = MATERIAL_STACK.search(html)
    return {
        "name": name_match.group(1).strip(),
        "desc": clean_material_desc(meta.group(1) if meta else ""),
        "weight": int(weight.group(1).replace(",", "")) if weight else None,
        "stack": int(stack.group(1).replace(",", "")) if stack else None,
    }


def parse_schematics(html: str) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for match in SCHEMATIC_NAME.finditer(html):
        name = match.group(1).strip()
        if not name or name in seen:
            continue
        window = html[match.end(): match.end() + 600]
        quality = QUALITY.search(window)
        if not quality:
            continue
        seen.add(name)
        out.append({"name": name, "quality": quality.group(1).strip()})
    return out


def scrape_skills(urls: list[str]) -> int:
    skills = []
    for index, url in enumerate(urls, 1):
        slug = url.rsplit("/", 1)[-1]
        try:
            skill = parse_skill(cached(url, f"skill_{slug}"), slug)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"技能 {slug} 失败: {exc}", file=sys.stderr)
            continue
        if skill:
            skills.append(skill)
        if index % 50 == 0:
            print(f"技能 {index}/{len(urls)}")
    _write("skills.json", {"source": f"{BASE}/skills/", "skills": skills})
    print(f"技能 {len(skills)} 条")
    return len(skills)


def scrape_materials(urls: list[str]) -> int:
    materials = []
    for index, url in enumerate(urls, 1):
        slug = url.rsplit("/", 1)[-1]
        try:
            material = parse_material(cached(url, f"material_{slug}"), slug)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"材料 {slug} 失败: {exc}", file=sys.stderr)
            continue
        if material:
            materials.append(material)
        if index % 50 == 0:
            print(f"材料 {index}/{len(urls)}")
    _write("materials.json", {"source": f"{BASE}/materials/", "materials": materials})
    print(f"材料 {len(materials)} 条")
    return len(materials)


def scrape_schematics() -> int:
    html = cached(f"{BASE}/schematics", "schematics_list")
    all_items = parse_schematics(html)
    legendary = [item for item in all_items if item["quality"] in LEGENDARY]
    _write(
        "schematics.json",
        {"source": f"{BASE}/schematics", "total": len(all_items), "schematics": legendary},
    )
    print(f"图纸共 {len(all_items)} 条，其中传奇 {len(legendary)} 条")
    return len(legendary)


def _write(name: str, payload: dict) -> None:
    path = DATA_DIR / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["skills", "materials", "schematics"], default="")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    urls = sitemap_urls()
    skill_urls = [u for u in urls if "/skills/" in u]
    material_urls = [u for u in urls if "/materials/" in u]
    print(f"技能 {len(skill_urls)} 个页面，材料 {len(material_urls)} 个页面")

    if args.only in ("", "skills"):
        scrape_skills(skill_urls)
    if args.only in ("", "materials"):
        scrape_materials(material_urls)
    if args.only in ("", "schematics"):
        scrape_schematics()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
