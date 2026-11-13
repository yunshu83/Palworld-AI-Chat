"""把聊天钩子装进服务器的 UE4SS。

需要装三样东西（缺一不可）：
  1. UE4SS 本体         —— 第三方，我们只检测不打包
  2. PalChatRelay       —— 我们的 Lua，随包分发
  3. mods.txt 注册一行  —— `PalChatRelay : 1`

所有写操作都先备份，因为这是在改别人的游戏目录。
"""
from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path

MOD_NAME = "PalChatRelay"
MOD_FILE = Path("Scripts") / "main.lua"


@dataclass
class Status:
    server_root: Path
    ue4ss_installed: bool
    log_exists: bool
    mod_installed: bool
    mod_current: bool
    registered: bool

    @property
    def ready(self) -> bool:
        return self.ue4ss_installed and self.mod_current and self.registered


def detect(server_root: str | Path, source_dir: str | Path) -> Status:
    root = Path(server_root)
    ue4ss = root / "Pal" / "Binaries" / "Win64" / "ue4ss"
    mod_dir = ue4ss / "Mods" / MOD_NAME
    source = Path(source_dir) / "Mods" / MOD_NAME

    mod_installed = (mod_dir / MOD_FILE).is_file()
    source_file = source / MOD_FILE
    mod_current = (
        mod_installed and source_file.is_file() and (mod_dir / MOD_FILE).read_bytes() == source_file.read_bytes()
    )
    registered = False
    mods_txt = ue4ss / "Mods" / "mods.txt"
    if mods_txt.is_file():
        try:
            for line in mods_txt.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip().startswith(f"{MOD_NAME} :"):
                    registered = line.split(":", 1)[1].strip() == "1"
                    break
        except OSError:
            pass

    return Status(
        server_root=root,
        ue4ss_installed=(ue4ss / "UE4SS.dll").is_file() or ue4ss.is_dir(),
        log_exists=(ue4ss / "UE4SS.log").is_file(),
        mod_installed=mod_installed,
        mod_current=bool(mod_current),
        registered=registered,
    )


def _backup(path: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.bak-{stamp}")
    shutil.copy2(path, target)
    return target


def install(server_root: str | Path, source_dir: str | Path) -> list[str]:
    """安装/更新 PalChatRelay 并注册；返回做了哪些事。"""
    root = Path(server_root)
    ue4ss = root / "Pal" / "Binaries" / "Win64" / "ue4ss"
    actions: list[str] = []

    if not ue4ss.is_dir():
        raise RuntimeError(f"没找到 UE4SS 目录：{ue4ss}\n请先安装 UE4SS 再运行向导。")

    source_mod = Path(source_dir) / "Mods" / MOD_NAME
    if not (source_mod / MOD_FILE).is_file():
        raise RuntimeError(f"随包的 mod 文件缺失：{source_mod / MOD_FILE}")

    mod_dir = ue4ss / "Mods" / MOD_NAME
    target = mod_dir / MOD_FILE
    try:
        mod_dir.mkdir(parents=True, exist_ok=True)
        if target.is_file() and target.read_bytes() == (source_mod / MOD_FILE).read_bytes():
            actions.append("PalChatRelay 已是最新，跳过写入")
        else:
            if target.is_file():
                backup = _backup(target)
                actions.append(f"备份旧版 mod：{backup.name}")
            shutil.copy2(source_mod / MOD_FILE, target)
            actions.append(f"写入 {target}")
    except OSError as exc:
        raise RuntimeError(
            f"无法写入 {target}（{exc}）。\n"
            "服务器可能正占着这个目录，或者当前账户没有写权限：\n"
            "  1. 先关掉帕鲁服务器再跑一次\n"
            "  2. 仍然失败就右键 setup.bat → 以管理员身份运行"
        ) from exc

    mods_txt = ue4ss / "Mods" / "mods.txt"
    if mods_txt.is_file():
        content = mods_txt.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()
        found = False
        changed = False
        for index, line in enumerate(lines):
            if line.strip().startswith(f"{MOD_NAME} :"):
                found = True
                if line.split(":", 1)[1].strip() != "1":
                    lines[index] = f"{MOD_NAME} : 1"
                    changed = True
                    actions.append("mods.txt 里把 PalChatRelay 改为启用")
                else:
                    actions.append("mods.txt 已启用 PalChatRelay，跳过")
                break
        if not found:
            lines.append(f"{MOD_NAME} : 1")
            changed = True
            actions.append("mods.txt 里新增 PalChatRelay : 1")
        # 只有真的需要改才动文件：避免"没变化也去备份+重写"引发的权限报错
        if changed:
            try:
                backup = _backup(mods_txt)
                mods_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
                actions.append(f"备份原 mods.txt：{backup.name}")
            except OSError as exc:
                raise RuntimeError(
                    f"无法写入 {mods_txt}（{exc}）。\n"
                    "服务器可能正占着这个文件，或者当前账户没有写权限：\n"
                    "  1. 先关掉帕鲁服务器再跑一次\n"
                    "  2. 仍然失败就右键 setup.bat → 以管理员身份运行"
                ) from exc
    else:
        try:
            mods_txt.parent.mkdir(parents=True, exist_ok=True)
            mods_txt.write_text(f"{MOD_NAME} : 1\n", encoding="utf-8")
            actions.append("新建 mods.txt 并启用 PalChatRelay")
        except OSError as exc:
            raise RuntimeError(
                f"无法创建 {mods_txt}（{exc}）。请右键 setup.bat → 以管理员身份运行。"
            ) from exc

    return actions
