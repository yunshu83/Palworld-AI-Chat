"""找 PalServer 装在哪。

自用场景下路径固定，但换机器/换盘符就会变，所以先探测再让用户确认：
  1. 注册表里的 Steam 安装位置
  2. 每个库目录下的 steamapps\\common\\PalServer
  3. 几个常见盘符的默认路径
"""
from __future__ import annotations

import os
from pathlib import Path

SERVER_FOLDER = "PalServer"
RELATIVE_UE4SS = Path("Pal/Binaries/Win64/ue4ss")


def _steam_roots() -> list[Path]:
    roots: list[Path] = []
    try:
        import winreg

        for hive, key in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
        ):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    value, _ = winreg.QueryValueEx(handle, "InstallPath")
                    if value:
                        roots.append(Path(value))
            except OSError:
                continue
    except ImportError:
        pass

    defaults = [
        Path(r"C:\Program Files (x86)\Steam"),
        Path(r"C:\Program Files\Steam"),
        Path(r"D:\Steam"),
        Path(r"E:\Steam"),
    ]
    roots.extend(path for path in defaults if path.is_dir())
    return roots


def _libraries() -> list[Path]:
    """Steam 库目录（含默认库与 libraryfolders.vdf 里登记的）。"""
    import re

    libraries: list[Path] = []
    for root in _steam_roots():
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if not vdf.is_file():
            continue
        try:
            text = vdf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in re.finditer(r'"path"\s+"([^"]+)"', text):
            libraries.append(Path(match.group(1).replace("\\\\", "\\")))
    # 兜底：常见盘符直接扫
    for letter in "CDEFGH":
        candidate = Path(f"{letter}:\\steamapps\\common")
        if candidate.is_dir():
            libraries.append(candidate.parent)
    seen: set[str] = set()
    unique: list[Path] = []
    for path in libraries:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def find_servers() -> list[Path]:
    """返回所有找到的 PalServer 目录。"""
    found: list[Path] = []
    seen: set[str] = set()
    for library in _libraries():
        candidate = library / "steamapps" / "common" / SERVER_FOLDER
        if candidate.is_dir():
            key = str(candidate).lower()
            if key not in seen:
                seen.add(key)
                found.append(candidate)
    for letter in "CDEFGH":
        candidate = Path(f"{letter}:\\steamapps\\common\\{SERVER_FOLDER}")
        if candidate.is_dir():
            key = str(candidate).lower()
            if key not in seen:
                seen.add(key)
                found.append(candidate)
    return found


def ue4ss_dir(server_root: str | Path) -> Path:
    return Path(server_root) / RELATIVE_UE4SS


def log_path(server_root: str | Path) -> Path:
    return ue4ss_dir(server_root) / "UE4SS.log"


def looks_like_server(path: str | Path) -> bool:
    root = Path(path)
    return (root / "Pal" / "Binaries" / "Win64").is_dir()


def guess_rest_url(port: int = 8212) -> str:
    return f"http://127.0.0.1:{port}"
