"""Palworld 服务端 DeepSeek 聊天助手（小鱼 / 鲸鱼娘人设）。

用法：
    python run.py                       # 按 config.toml 运行（首次会自动进向导）
    python run.py wizard                # 重新配置（服务器路径 / Key / 模型）
    python run.py data check            # 数据自检
    python run.py --doctor              # 逐项体检
    python run.py --dry-run             # 只验证触发逻辑，不调 DeepSeek
    python run.py --config other.toml
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    print(
        f"需要 Python 3.11 或更新版本（当前 {sys.version.split()[0]}），"
        "用到标准库 tomllib；装个新版 Python 即可，不需要 pip 装别的。",
        file=sys.stderr,
    )
    raise SystemExit(1)

from bot import paths  # noqa: E402
from bot.doctor import run_doctor  # noqa: E402
from bot.service import Bot  # noqa: E402
from bot.settings import load_config  # noqa: E402

DEFAULT_CONFIG = paths.config_file()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="幻兽帕鲁服务端 DeepSeek 聊天助手")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="配置文件路径，默认同目录的 config.toml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="不调用 DeepSeek（不需要 API Key），只在控制台打印将要发出的回复",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="逐项体检：配置、人设、Key、DeepSeek 接口、回复出口、聊天来源",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="只处理当前已有的事件就退出（用于验证，长时间驻留不要加）",
    )
    return parser.parse_args(argv)


def _data_check() -> int:
    from bot.datacheck import check_all, format_report, has_errors

    issues = check_all(paths.data_dir())
    print(format_report(issues))
    return 2 if has_errors(issues) else 0


def _wizard() -> int:
    from bot.wizard import run_wizard

    return run_wizard()


def _models() -> int:
    """列出当前 Key 可用的模型（官方或中转站，按配置的 base_url）。"""
    import os

    from bot.models import list_models, recommend

    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    base_url = "https://api.deepseek.com"
    if DEFAULT_CONFIG.is_file():
        try:
            cfg = load_config(DEFAULT_CONFIG)
            key = key or cfg.deepseek.api_key
            base_url = cfg.deepseek.base_url or base_url
        except Exception:
            pass
    if not key:
        print("没有 API Key：先运行 python run.py wizard", file=sys.stderr)
        return 2
    print(f"接口：{base_url}")
    try:
        models = list_models(key, base_url)
    except RuntimeError as exc:
        print(f"拉取失败：{exc}", file=sys.stderr)
        return 2
    preferred = recommend(models)
    for name in models:
        print(f"  {name}" + ("   ← 推荐" if name == preferred else ""))
    return 0


def _data_update(rest: list[str]) -> int:
    from bot.update_data import update

    apply = "--apply" in rest
    only: list[str] | None = None
    if "--only" in rest:
        index = rest.index("--only")
        if index + 1 < len(rest):
            only = [part.strip() for part in rest[index + 1].split(",") if part.strip()]
    return update(paths.root(), apply=apply, only=only)


def _data_import(rest: list[str]) -> int:
    from bot.csv_import import read_csv, to_patches, write_overrides

    if not rest:
        print("用法：python run.py data import <文件.csv> [--file paldex.json]", file=sys.stderr)
        return 2
    source = rest[0]
    target = "paldex.json"
    if "--file" in rest:
        index = rest.index("--file")
        if index + 1 < len(rest):
            target = rest[index + 1]

    try:
        rows = read_csv(source)
    except (OSError, ValueError) as exc:
        print(f"读取失败：{exc}", file=sys.stderr)
        return 2
    if not rows:
        print("CSV 里没有可导入的行（除了 name 之外至少要有 1 列有值）")
        return 1

    patches = to_patches(rows)
    path = write_overrides(paths.overrides_dir(), target, patches)
    fields = sorted({key for row in rows for key in row if key != "name"})
    print(f"导入 {len(patches)} 条，字段：{'、'.join(fields)}")
    print(f"写入：{path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 GBK，中文日志有时会编码失败；坏字符替换掉，别让程序挂
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list[:1] == ["wizard"]:
        return _wizard()
    if args_list[:2] == ["data", "check"]:
        return _data_check()
    if args_list[:2] == ["data", "update"]:
        return _data_update(args_list[2:])
    if args_list[:2] == ["data", "import"]:
        return _data_import(args_list[2:])
    if args_list[:1] == ["models"]:
        return _models()

    args = parse_args(args_list)

    # 没有配置文件就别抛 traceback，直接引导配置
    if not Path(args.config).is_file():
        print(f"没找到配置文件：{args.config}")
        if Path(args.config).resolve() == DEFAULT_CONFIG.resolve():
            print("进入首次配置向导…\n")
            code = _wizard()
            if code != 0:
                return code
            if not DEFAULT_CONFIG.is_file():
                print("配置仍未生成，退出。", file=sys.stderr)
                return 2
        else:
            print("请检查 --config 路径，或先运行 python run.py wizard", file=sys.stderr)
            return 2

    try:
        cfg = load_config(args.config)
    except SystemExit:
        raise
    except Exception as exc:  # 配置写错时给一句人话，别吐一堆 traceback
        print(f"读取配置失败：{exc}", file=sys.stderr)
        return 2

    if args.doctor:
        return run_doctor(cfg)

    try:
        bot = Bot(cfg, dry_run=args.dry_run)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    from bot.lock import AlreadyRunning, SingleInstance

    try:
        with SingleInstance(paths.lock_file()):
            bot.run(once=args.once)
    except AlreadyRunning as exc:
        print(str(exc), file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
