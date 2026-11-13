"""统一的路径解析：所有运行时文件都相对程序目录。

之前 `config.toml` 里写死了 `E:\\steam\\...`，换台机器就跑不起来。
这里改成"以程序所在目录为根"，打包后解压到哪都能用。
"""
from __future__ import annotations

from pathlib import Path

# bot/ 的上一级 = 程序根目录
ROOT = Path(__file__).resolve().parent.parent


def root() -> Path:
    return ROOT


def data_dir() -> Path:
    return ROOT / "data"


def overrides_dir() -> Path:
    return data_dir() / "overrides"


def logs_dir() -> Path:
    return ROOT / "logs"


def config_file() -> Path:
    return ROOT / "config.toml"


def local_config_file() -> Path:
    """本机实配（含密钥），不进版本库、不进发布包。"""
    return ROOT / "config.local.json"


def example_config_file() -> Path:
    return ROOT / "config.example.toml"


def lock_file() -> Path:
    return ROOT / ".palbot.lock"


def ensure_dirs() -> None:
    for path in (data_dir(), overrides_dir(), logs_dir()):
        path.mkdir(parents=True, exist_ok=True)
