"""exiftool 的常駐程序包裝（-stay_open），避免每個檔案都重新啟動 perl。"""

from __future__ import annotations

import json
import queue
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

READ_TAGS = [
    "-EXIF:DateTimeOriginal",
    "-EXIF:OffsetTimeOriginal",
    "-EXIF:CreateDate",
    "-EXIF:OffsetTimeDigitized",
    "-QuickTime:CreationDate",
    "-QuickTime:CreateDate",
    "-XMP:DateTimeOriginal",
    "-XMP:DateCreated",
]
READ_CHUNK = 50


class ExifToolError(RuntimeError):
    pass


class ExifTool:
    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None
        self._counter = 0
        self._lock = threading.Lock()

    def __enter__(self) -> "ExifTool":
        self._proc = subprocess.Popen(
            ["exiftool", "-stay_open", "True", "-@", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )
        return self

    def __exit__(self, *exc: object) -> None:
        if self._proc is None:
            return
        try:
            assert self._proc.stdin is not None
            self._proc.stdin.write("-stay_open\nFalse\n")
            self._proc.stdin.flush()
            self._proc.wait(timeout=10)
        except Exception:
            self._proc.kill()
        self._proc = None

    def execute(self, *args: str) -> str:
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise ExifToolError("exiftool 尚未啟動")
        for arg in args:
            if "\n" in arg:
                raise ExifToolError(f"參數含有換行字元：{arg!r}")
        with self._lock:
            self._counter += 1
            marker = f"{{ready{self._counter}}}"
            payload = ["-charset", "filename=utf8", *args, f"-execute{self._counter}"]
            self._proc.stdin.write("\n".join(payload) + "\n")
            self._proc.stdin.flush()
            lines = []
            for line in self._proc.stdout:
                if line.rstrip("\n") == marker:
                    return "".join(lines)
                lines.append(line)
        raise ExifToolError("exiftool 意外結束")

    def read(self, paths: list[Path]) -> dict[Path, dict]:
        if not paths:
            return {}
        out = self.execute("-j", "-G", *READ_TAGS, *(str(p) for p in paths))
        result: dict[Path, dict] = {p: {} for p in paths}
        if out.strip():
            by_name = {str(p): p for p in paths}
            for entry in json.loads(out):
                path = by_name.get(entry.get("SourceFile", ""))
                if path is not None:
                    result[path] = entry
        return result

    def write(self, path: Path, tags: dict[str, str], extra: tuple[str, ...] = ()) -> None:
        args = ["-overwrite_original", "-m", *extra, *(f"-{k}={v}" for k, v in tags.items()), str(path)]
        out = self.execute(*args)
        if "1 image files updated" not in out and "1 image files unchanged" not in out:
            raise ExifToolError(f"exiftool 寫入失敗：{path}（{out.strip()}）")


def read_all(paths: list[Path], jobs: int) -> dict[Path, dict]:
    """平行讀取多個檔案的日期標籤。"""
    chunks = [paths[i : i + READ_CHUNK] for i in range(0, len(paths), READ_CHUNK)]
    if not chunks:
        return {}
    workers = max(1, min(jobs, len(chunks)))
    tools = [ExifTool().__enter__() for _ in range(workers)]
    pool: queue.Queue[ExifTool] = queue.Queue()
    for t in tools:
        pool.put(t)

    def run(chunk: list[Path]) -> dict[Path, dict]:
        tool = pool.get()
        try:
            return tool.read(chunk)
        finally:
            pool.put(tool)

    result: dict[Path, dict] = {}
    try:
        with ThreadPoolExecutor(workers) as ex:
            for part in ex.map(run, chunks):
                result.update(part)
    finally:
        for t in tools:
            t.__exit__()
    return result
