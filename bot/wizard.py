"""首次配置向导：问几个问题，把能自动做的都做掉。

设计原则：
  * 能探测的不问（服务器路径、UE4SS 是否装好）
  * 必须问的一次问清（API Key、Admin 密码、模型）
  * 写盘前先备份，写盘后立刻体检
"""
from __future__ import annotations

import json
import random
import re
import shutil
import string
import subprocess
import sys
from pathlib import Path

from . import modinstall, paths, steam
from .models import list_models, recommend

UE4SS_URL = "https://github.com/UE4SS-RE/RE-UE4SS/releases"
OFFICIAL_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"


def _ask(prompt: str, default: str = "") -> str:
    suffix = f"（默认 {default}）" if default else ""
    try:
        answer = input(f"{prompt}{suffix}：").strip()
    except EOFError:
        return default
    return answer or default


def _pick_server() -> Path | None:
    found = steam.find_servers()
    if found:
        print("\n找到这些服务器：")
        for index, path in enumerate(found, 1):
            print(f"  {index}. {path}")
        choice = _ask("选择编号，或直接粘贴路径", "1")
        if choice.isdigit() and 1 <= int(choice) <= len(found):
            return found[int(choice) - 1]
        candidate = Path(choice.strip('"').strip("'"))
        return candidate if steam.looks_like_server(candidate) else None

    print("\n没自动找到 PalServer。")
    manual = _ask("请粘贴 PalServer 目录（含 Pal\\Binaries\\Win64 那一层）")
    if not manual:
        return None
    candidate = Path(manual.strip('"').strip("'"))
    return candidate if steam.looks_like_server(candidate) else None


def _generate_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


def _server_running() -> bool:
    """服务器是否在跑。

    不能按单个进程名过滤：实际进程可能是 PalServer-Win64-Shipping.exe
    或 PalServer-Win64-Shipping-Cmd.exe，按名字精确匹配会漏判。
    """
    try:
        output = subprocess.run(
            ["tasklist"],
            capture_output=True,
            text=True,
            errors="ignore",
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "PalServer" in output


def _ini_path(server_root: Path) -> Path:
    return server_root / "Pal" / "Saved" / "Config" / "WindowsServer" / "PalWorldSettings.ini"


def _read_admin_password(server_root: Path) -> str:
    """从 ini 里读出当前 AdminPassword（读不到返回空串）。"""
    ini = _ini_path(server_root)
    if not ini.is_file():
        return ""
    try:
        text = ini.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    match = re.search(r'AdminPassword="([^"]*)"', text)
    return match.group(1) if match else ""


def _write_admin_password(server_root: Path, password: str) -> tuple[bool, str]:
    """把 AdminPassword 写进 ini。返回 (是否成功, 说明)。

    备份是"尽力而为"：某些机器上有文件保护软件会拦着新建 .bak，
    但 ini 本身能写，所以备份失败不应该阻止写入。
    """
    ini = _ini_path(server_root)
    if not ini.is_file():
        return False, f"没找到 {ini}，请手动填写 AdminPassword"
    if _server_running():
        return False, (
            "检测到服务器正在运行，已跳过写入（ini 被占用）。\n"
            f"  请关服后把 AdminPassword 改成：{password}\n"
            "  或者先关服再重跑向导选「2 自动生成」。"
        )

    text = ini.read_text(encoding="utf-8", errors="ignore")
    if not re.search(r'AdminPassword="[^"]*"', text):
        return False, "ini 里没找到 AdminPassword 字段，请手动填写：" + password

    backup_note = ""
    try:
        backup = ini.with_name(ini.name + ".bak")
        shutil.copy2(ini, backup)
        backup_note = f"（备份：{backup.name}）"
    except OSError:
        backup_note = "（备份创建失败，已跳过）"

    try:
        text = re.sub(r'AdminPassword="[^"]*"', f'AdminPassword="{password}"', text, count=1)
        ini.write_text(text, encoding="utf-8")
    except OSError as exc:
        return False, (
            f"写入失败（{exc}）。\n"
            f"  已生成的密码：{password}\n"
            "  可能是安全软件拦了对这个目录的写入。\n"
            "  建议改用「1 手动输入」，或手动把 ini 里的 AdminPassword 改成上面的密码。"
        )
    return True, f"已写入 AdminPassword{backup_note}"


def _write_local_config(data: dict) -> Path:
    target = paths.local_config_file()
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _ask_base_url(existing: str = "") -> str:
    """选官方接口还是中转站，返回 base_url（不含尾部斜杠）。"""
    print("\n接口地址：")
    print(f"  1. 官方  {OFFICIAL_BASE}")
    print("  2. 中转站（自己填 URL，通常形如 https://xxx.com/v1）")
    if existing and existing.rstrip("/") != OFFICIAL_BASE:
        print(f"     （上次用的是 {existing}）")

    default = "1" if (not existing or existing.rstrip("/") == OFFICIAL_BASE) else "2"
    choice = _ask("选择", default)
    if choice != "2":
        return OFFICIAL_BASE

    raw = _ask("中转站地址", "" if existing == OFFICIAL_BASE else existing)
    url = raw.strip().strip('"').strip("'").rstrip("/")
    if not url:
        print("  没填地址，改用官方接口。")
        return OFFICIAL_BASE
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
        print(f"  已补全协议：{url}")
    return url


def _choose_model(api_key: str, base_url: str = None) -> str:
    """先拉账号可用的模型，再让用户选。"""
    try:
        models = list_models(api_key, base_url or OFFICIAL_BASE)
    except RuntimeError as exc:
        print(f"\n（拉取模型列表失败：{exc}）")
        print("  中转站不一定支持 /models，可以直接手输模型名。")
        return _ask("请手动输入模型名", DEFAULT_MODEL)

    preferred = recommend(models)
    print("\n这个 Key 可用的模型：")
    for index, name in enumerate(models, 1):
        tags = []
        if name == preferred:
            tags.append("推荐：便宜、够用")
        if "pro" in name.lower():
            tags.append("更强、更贵")
        suffix = f"   ← {' / '.join(tags)}" if tags else ""
        print(f"  {index}. {name}{suffix}")

    default_index = str(models.index(preferred) + 1)
    choice = _ask("选择编号，或直接输入模型名", default_index)
    if choice.isdigit():
        index = int(choice)
        if 1 <= index <= len(models):
            return models[index - 1]
    return choice or preferred


def _load_existing() -> dict:
    """读已有的 config.local.json，重跑时用它做默认值。"""
    path = paths.local_config_file()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _mask(key: str) -> str:
    if len(key) <= 10:
        return "****"
    return f"{key[:6]}****{key[-4:]}"


def run_wizard() -> int:
    print("=" * 52)
    print("  幻兽帕鲁 DeepSeek 助手 · 首次配置")
    print("=" * 52)

    server = _pick_server()
    if server is None:
        print("\n✗ 没找到有效的 PalServer 目录（需要包含 Pal\\Binaries\\Win64）。")
        return 2
    print(f"✓ 服务器目录：{server}")

    status = modinstall.detect(server, paths.root() / "ue4ss")
    if not status.ue4ss_installed or not status.log_exists:
        print("\n✗ 这个服务器还没装 UE4SS（读不到聊天日志）。")
        print(f"  下载地址：{UE4SS_URL}")
        print("  装好后把 UE4SS 解压到：", steam.ue4ss_dir(server))
        print("  然后再运行一次向导。")
        return 3

    if _server_running():
        print("\n⚠ 服务器正在运行。装 mod 会改它的目录，建议先关服；")
        print("  如果接下来报“无法写入”，关掉服务器再跑一次即可。")

    try:
        actions = modinstall.install(server, paths.root() / "ue4ss")
    except RuntimeError as exc:
        print(f"\n✗ 安装聊天钩子失败：{exc}")
        return 5
    if actions:
        print("\n✓ 聊天钩子已安装：")
        for action in actions:
            print("   -", action)
        print("  （需要重启服务器才会生效）")
    else:
        print("\n✓ 聊天钩子已是最新，无需改动")

    existing = _load_existing()
    saved_base = str((existing.get("deepseek") or {}).get("base_url") or OFFICIAL_BASE)
    base_url = _ask_base_url(saved_base)

    saved_key = str((existing.get("deepseek") or {}).get("api_key") or "")
    api_key = _ask(
        f"\nDeepSeek API Key（sk- 开头，回车沿用 {_mask(saved_key)}）" if saved_key else "\nDeepSeek API Key（sk- 开头）",
        saved_key,
    )
    if not api_key:
        print("✗ 没有 API Key 就没法调用模型。")
        return 4

    print("\nAdmin 密码（REST 发公告用）：")
    print("  1. 手动输入现有密码")
    saved_admin = str((existing.get("palworld_rest") or {}).get("admin_password") or "")
    if saved_admin:
        print(f"     （回车沿用上次：{_mask(saved_admin)}）")
    print("  2. 自动生成并写入服务器配置（需要先关服）")
    choice = _ask("选择", "1")
    admin_note = ""
    if choice == "2":
        password = _generate_password()
        ok, note = _write_admin_password(server, password)
        print("  " + note)
        if not ok:
            existing_pwd = _read_admin_password(server)
            if existing_pwd:
                password = existing_pwd
                print(f"  已改用 ini 里现有的密码（{_mask(existing_pwd)}），保证配置和服务器一致。")
    else:
        password = _ask("请输入 PalWorldSettings.ini 里的 AdminPassword", saved_admin)

    model = _choose_model(api_key, base_url)

    config = {
        "deepseek": {"api_key": api_key, "model": model, "base_url": base_url},
        "server": {"mode": "log", "log_path": str(steam.log_path(server))},
        "palworld_rest": {"url": steam.guess_rest_url(), "admin_password": password},
    }
    target = _write_local_config(config)
    print(f"\n✓ 配置已写入：{target}")
    print("  （明文保存，已加入 .gitignore，不会被提交）")

    if not paths.config_file().is_file() and paths.example_config_file().is_file():
        shutil.copy2(paths.example_config_file(), paths.config_file())
        print(f"✓ 已从模板生成 {paths.config_file().name}")

    print("\n下一步：")
    print("  1. 重启帕鲁服务器（让 mod 生效）")
    print("  2. 运行 python run.py --doctor 体检")
    print("  3. 运行 python run.py 启动机器人")
    return 0


if __name__ == "__main__":
    sys.exit(run_wizard())
