"""数据更新：游戏更新后，把资料库重新抓一遍。

流程固定五步，失败就不动数据：
  1. 备份   data/*.json → data/backup/<时间戳>/
  2. 抓取   依次调用 tools/scrape_*.py
  3. 校验   bot.datacheck，有 error 就回滚
  4. 报告   新增/删除/数量变化，写到 data/UPDATE-<时间戳>.md
  5. 落盘   默认 dry-run（结束后回滚），加 --apply 才保留

注意：teams.json / elements.json / fields.json 是人工维护的，不在抓取范围，
报告里会提醒你确认。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = [
    ("paldex", "tools/scrape_paldb.py", "paldex.json", "pals"),
    ("skills", "tools/scrape_extra.py", "paldex.json", "pals"),
    ("tech", "tools/scrape_tech.py", "tech.json", "techs"),
    ("items", "tools/scrape_items.py", "paldex.json", "pals"),
]
RUNTIME_FILES = (
    "paldex.json",
    "skills.json",
    "materials.json",
    "schematics.json",
    "tech.json",
    "items.json",
)


def _names(path: Path, key: str) -> list[str]:
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get(key) if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    return [str(item.get("name")) for item in items if isinstance(item, dict) and item.get("name")]


def _snapshot(data_dir: Path) -> dict[str, list[str]]:
    return {
        "paldex": _names(data_dir / "paldex.json", "pals"),
        "skills": _names(data_dir / "skills.json", "skills"),
        "materials": _names(data_dir / "materials.json", "materials"),
        "tech": _names(data_dir / "tech.json", "techs"),
        "items": _names(data_dir / "items.json", "items"),
    }


def _backup(data_dir: Path, target: Path) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for name in RUNTIME_FILES:
        source = data_dir / name
        if source.is_file():
            shutil.copy2(source, target / name)
            saved.append(target / name)
    return saved


def _restore(data_dir: Path, backup_dir: Path) -> None:
    for path in backup_dir.glob("*.json"):
        shutil.copy2(path, data_dir / path.name)


def _run_scripts(root: Path, names: list[str] | None) -> list[str]:
    logs: list[str] = []
    for key, rel, _, _ in SCRIPTS:
        if names and key not in names:
            continue
        script = root / rel
        if not script.is_file():
            logs.append(f"跳过 {rel}（文件不存在）")
            continue
        started = time.time()
        try:
            result = subprocess.run(
                [sys.executable, str(script)],
                cwd=str(root),
                capture_output=True,
                text=True,
                errors="ignore",
                timeout=3600,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logs.append(f"{rel} 执行失败：{exc}")
            continue
        spent = time.time() - started
        status = "完成" if result.returncode == 0 else f"退出码 {result.returncode}"
        logs.append(f"{rel} {status}，用时 {spent:.0f}s")
        if result.returncode != 0:
            tail = (result.stderr or "").strip().splitlines()[-3:]
            logs.extend(f"  {line}" for line in tail)
    return logs


def _diff_report(before: dict[str, list[str]], after: dict[str, list[str]]) -> str:
    lines: list[str] = []
    for key in ("paldex", "skills", "materials", "tech", "items"):
        old_list = before.get(key, [])
        new_list = after.get(key, [])
        old = set(old_list)
        new = set(new_list)
        added = sorted(new - old)
        removed = sorted(old - new)
        lines.append(f"## {key}")
        lines.append(f"- 数量：{len(old_list)} → {len(new_list)}（去重后 {len(old)} → {len(new)}）")
        if added:
            lines.append(f"- 新增 {len(added)}：" + "、".join(added[:20]) + ("…" if len(added) > 20 else ""))
        if removed:
            lines.append(f"- 删除 {len(removed)}：" + "、".join(removed[:20]) + ("…" if len(removed) > 20 else ""))
        if not added and not removed:
            lines.append("- 无变化")
        lines.append("")
    return "\n".join(lines)


def update(root: str | Path, apply: bool = False, only: list[str] | None = None) -> int:
    base = Path(root)
    data_dir = base / "data"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = data_dir / "backup" / stamp

    before = _snapshot(data_dir)
    saved = _backup(data_dir, backup_dir)
    print(f"已备份 {len(saved)} 个文件到 {backup_dir}")

    output = _run_scripts(base, only)
    for line in output:
        print("  " + line)

    from .datacheck import check_all, format_report, has_errors

    issues = check_all(data_dir)
    if has_errors(issues):
        print("\n校验发现错误，已回滚：")
        print(format_report(issues))
        _restore(data_dir, backup_dir)
        return 2

    after = _snapshot(data_dir)
    report = _diff_report(before, after)
    report_path = data_dir / f"UPDATE-{stamp}.md"
    report_path.write_text(
        f"# 数据更新报告 {stamp}\n\n{report}\n"
        "> teams.json / elements.json / fields.json 是人工维护的，请确认是否需要跟着改。\n",
        encoding="utf-8",
    )

    print("\n" + report)
    print(f"报告已写入：{report_path}")

    if not apply:
        _restore(data_dir, backup_dir)
        shutil.rmtree(backup_dir, ignore_errors=True)
        print("\n（dry-run）已回滚。确认没问题后加 --apply 再跑一次。")
        return 0

    print("\n已保留新数据。")
    return 0
