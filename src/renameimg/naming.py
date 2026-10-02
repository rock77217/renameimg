"""依日期產生檔名，並處理同名衝突。"""

from __future__ import annotations

import os
import re
from datetime import datetime
from itertools import count
from pathlib import Path


def base_stem(prefix: str, dt: datetime) -> str:
    return f"{prefix}{dt:%Y%m%d_%H%M%S}"


def already_named(stem: str, base: str) -> bool:
    """目前檔名是否已經是 base 或 base_N（重跑時保持不變）。"""
    return stem == base or re.fullmatch(re.escape(base) + r"_\d+", stem) is not None


def _occupied(target: Path, own: list[Path]) -> bool:
    if not os.path.lexists(target):
        return False
    return not any(src.exists() and os.path.samefile(target, src) for src in own)


class NameAllocator:
    """記錄本次執行已分配的路徑，避免兩組檔案搶同一個名字。

    以小寫比對，以適應不分大小寫的檔案系統（macOS、SMB）。
    """

    def __init__(self) -> None:
        self._reserved: set[str] = set()

    def _key(self, path: Path) -> str:
        return str(path).lower()

    def is_free(self, stem: str, directory: Path, members: list[tuple[Path, str]]) -> bool:
        own = [src for src, _ in members]
        for _, suffix in members:
            target = directory / f"{stem}{suffix}"
            if self._key(target) in self._reserved or _occupied(target, own):
                return False
        return True

    def reserve(self, stem: str, directory: Path, members: list[tuple[Path, str]]) -> None:
        for _, suffix in members:
            self._reserved.add(self._key(directory / f"{stem}{suffix}"))

    def allocate(self, base: str, directory: Path, members: list[tuple[Path, str]]) -> str:
        """members 為 (原路徑, 新檔名後綴)；回傳 base 或第一個可用的 base_N。"""
        for n in count():
            stem = base if n == 0 else f"{base}_{n}"
            if self.is_free(stem, directory, members):
                self.reserve(stem, directory, members)
                return stem
        raise AssertionError("unreachable")
