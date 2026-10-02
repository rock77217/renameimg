"""掃描資料夾，依檔案類型分類，並把同名的配對檔（Live Photo、附屬檔）分成一組。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".tif", ".tiff", ".gif", ".webp", ".bmp"}
RAW_EXTS = {".dng", ".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2", ".raf", ".srw", ".pef"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".mts", ".m2ts", ".3gp", ".wmv", ".mpg", ".mpeg", ".webm"}
SIDECAR_EXTS = {".aae", ".xmp"}
# 可以安全補寫拍攝日期的照片格式
META_WRITABLE_EXTS = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".tif", ".tiff", ".webp"}

TMP_PREFIX = ".renameimg-tmp-"
SKIP_DIR_PREFIXES = (".", "@", "#")  # .git、Synology @eaDir、#recycle 等


def kind_of(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in RAW_EXTS:
        return "raw"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in SIDECAR_EXTS:
        return "sidecar"
    return None


@dataclass
class Member:
    path: Path
    kind: str
    # 檔名中組名之後的部分，例如 ".JPG"、".HEIC.xmp"
    suffix: str
    live: bool = False  # Live Photo 的影片部分


@dataclass
class Group:
    directory: Path
    stem: str
    kind: str  # image | video
    members: list[Member] = field(default_factory=list)

    @property
    def primary(self) -> Member:
        return self.members[0]


@dataclass
class ScanResult:
    groups: list[Group] = field(default_factory=list)
    unknown: list[Path] = field(default_factory=list)
    stale_tmp: list[Path] = field(default_factory=list)


def _group_key(name: str) -> str:
    """回傳組名：一般檔取主檔名；IMG_1.HEIC.xmp 這類附屬檔取 IMG_1。"""
    stem, ext = os.path.splitext(name)
    if ext.lower() in SIDECAR_EXTS:
        inner_stem, inner_ext = os.path.splitext(stem)
        if inner_ext and kind_of(Path(stem)) in ("image", "raw", "video"):
            return inner_stem
    return stem


def scan(root: Path) -> ScanResult:
    result = ScanResult()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(SKIP_DIR_PREFIXES))
        directory = Path(dirpath)
        buckets: dict[str, list[tuple[str, str]]] = {}
        for name in sorted(filenames):
            if name.startswith(TMP_PREFIX):
                result.stale_tmp.append(directory / name)
                continue
            if name.startswith("."):
                continue
            key = _group_key(name)
            buckets.setdefault(key.lower(), []).append((key, name))
        for entries in buckets.values():
            _build_groups(directory, entries, result)
    return result


def _build_groups(directory: Path, entries: list[tuple[str, str]], result: ScanResult) -> None:
    images: list[Member] = []
    raws: list[Member] = []
    videos: list[Member] = []
    sidecars: list[Member] = []
    for key, name in entries:
        path = directory / name
        kind = kind_of(path)
        if kind is None:
            result.unknown.append(path)  # 不支援的檔案類型
            continue
        member = Member(path, kind, name[len(key):])
        {"image": images, "raw": raws, "video": videos, "sidecar": sidecars}[kind].append(member)

    stem = entries[0][0]
    if images or raws:
        for v in videos:
            v.live = True
        members = images + raws + videos + sidecars
        result.groups.append(Group(directory, stem, "image", members))
    elif videos:
        # 第一個影片帶著附屬檔，其餘影片各自成組
        result.groups.append(Group(directory, stem, "video", [videos[0], *sidecars]))
        for v in videos[1:]:
            result.groups.append(Group(directory, stem, "video", [v]))
    else:
        result.unknown.extend(m.path for m in sidecars)
