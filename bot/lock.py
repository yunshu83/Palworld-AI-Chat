"""单实例锁：防止双击两次起两个机器人。

两个实例同时跑会导致每条消息回两次，玩家会以为机器人抽风。
用文件锁实现，进程退出（含崩溃）时操作系统自动释放。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


class AlreadyRunning(RuntimeError):
    """已有实例在运行。"""


class SingleInstance:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._handle = None

    def __enter__(self) -> "SingleInstance":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(self.path, "a+")
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._handle.close()
            self._handle = None
            raise AlreadyRunning("已经有一个机器人在运行了，先关掉它。") from exc

        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(str(os.getpid()))
        self._handle.flush()
        return self

    def __exit__(self, *exc_info) -> bool:
        if self._handle is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    self._handle.seek(0)
                    msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            self._handle.close()
            self._handle = None
        return False
