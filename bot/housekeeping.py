"""日常清理：日志文件别无限堆积。

机器人每次启动都会生成 bot-*.log；PowerShell 启动器还会写 launcher-*.log。
跑久了 logs/ 里会有几百个文件，所以启动时清一次。
"""
from __future__ import annotations

import time
from pathlib import Path


def cleanup_logs(directory: str | Path, keep_days: int = 7, keep_files: int = 40) -> int:
    """删除过期和超量的日志，返回删除数量。"""
    base = Path(directory)
    if not base.is_dir():
        return 0

    files = [path for path in base.glob("*.log") if path.is_file()]
    if not files:
        return 0

    cutoff = time.time() - keep_days * 86400
    removed = 0
    remaining: list[Path] = []
    for path in files:
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
                continue
        except OSError:
            continue
        remaining.append(path)

    if len(remaining) > keep_files:
        remaining.sort(key=lambda path: path.stat().st_mtime)
        for path in remaining[: len(remaining) - keep_files]:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass

    return removed
