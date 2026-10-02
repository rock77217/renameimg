"""規劃與執行：先為每一組檔案決定日期、新檔名、是否壓縮，再依序執行。"""

from __future__ import annotations

import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from pathlib import Path

from . import exiftool, video
from .dates import Resolution, collect_candidates, resolve
from .media import META_WRITABLE_EXTS, Group, Member, scan
from .naming import NameAllocator, already_named, base_stem

PREFIX = {"image": "IMG_", "video": "VID_"}
MODES = ("run", "rename", "compress", "retouch")


@dataclass
class Options:
    mode: str
    source: Path
    tz: tzinfo
    target: Path | None = None
    dry_run: bool = False
    jobs: int = 4
    tmp_dir: Path | None = None

    @property
    def renames(self) -> bool:
        return self.mode in ("run", "rename")

    @property
    def compresses(self) -> bool:
        return self.mode in ("run", "compress")

    @property
    def moves(self) -> bool:
        return self.mode != "retouch"


@dataclass
class GroupPlan:
    group: Group
    resolution: Resolution
    moves: list[tuple[Member, Path]]
    video: video.VideoInfo | None = None
    compress: bool = False
    compress_reason: str = ""
    error: str | None = None


@dataclass
class Row:
    original: str
    new: str = ""
    kind: str = ""
    action: str = ""
    date: str = ""
    date_source: str = ""
    size_before: int | str = ""
    size_after: int | str = ""
    status: str = ""
    message: str = ""


@dataclass
class RunResult:
    rows: list[Row] = field(default_factory=list)
    errors: int = 0
    interrupted: bool = False


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- 規劃

def plan(opts: Options, groups: list[Group]) -> list[GroupPlan]:
    primaries = [g.primary.path for g in groups]
    tags = exiftool.read_all(primaries, opts.jobs)

    probes: dict[Path, video.VideoInfo | Exception] = {}
    if opts.compresses:
        videos = [g.primary.path for g in groups if g.kind == "video"]

        def safe_probe(p: Path) -> video.VideoInfo | Exception:
            try:
                return video.probe(p)
            except Exception as e:  # noqa: BLE001 - 錯誤記到報告
                return e

        with ThreadPoolExecutor(max(1, opts.jobs)) as ex:
            probes = dict(zip(videos, ex.map(safe_probe, videos)))

    allocator = NameAllocator()
    plans = []
    for g in groups:
        res = resolve(collect_candidates(g.primary.path, tags.get(g.primary.path, {}), opts.tz), opts.tz)
        p = GroupPlan(g, res, [])
        info = probes.get(g.primary.path)
        if isinstance(info, Exception):
            p.error = str(info)
        elif info is not None:
            p.video = info
            p.compress, p.compress_reason = video.decide(info)
        p.moves = _plan_moves(opts, g, res, p.compress, allocator)
        plans.append(p)
    return plans


def _plan_moves(
    opts: Options, g: Group, res: Resolution, compress: bool, allocator: NameAllocator
) -> list[tuple[Member, Path]]:
    if not opts.moves:
        return [(m, m.path) for m in g.members]

    dest_dir = g.directory
    if opts.target is not None:
        dest_dir = opts.target / g.directory.relative_to(opts.source)
    suffixes = [
        (m.path, ".mp4" if (m is g.primary and compress) else m.suffix.lower()) for m in g.members
    ]
    base = g.stem
    if opts.renames and res.value is not None:
        base = base_stem(PREFIX[g.kind], res.value)

    if already_named(g.stem, base) and allocator.is_free(g.stem, dest_dir, suffixes):
        stem = g.stem
        allocator.reserve(stem, dest_dir, suffixes)
    else:
        stem = allocator.allocate(base, dest_dir, suffixes)
    return [(m, dest_dir / f"{stem}{suffix}") for m, (_, suffix) in zip(g.members, suffixes)]


# ---------------------------------------------------------------- 執行

def _exif_time(dt: datetime) -> str:
    offset = dt.strftime("%z")
    return dt.strftime("%Y:%m:%d %H:%M:%S") + f"{offset[:3]}:{offset[3:]}"


def _time_tags(dt: datetime) -> dict[str, str]:
    tags = {"FileModifyDate": _exif_time(dt)}
    if sys.platform == "darwin":
        tags["FileCreateDate"] = _exif_time(dt)
    return tags


def _metadata_tags(opts: Options, p: GroupPlan, m: Member, dst: Path) -> tuple[dict[str, str], tuple[str, ...]]:
    """原檔缺少拍攝日期時要補寫的標籤；已有值的一律不覆蓋。"""
    res = p.resolution
    if opts.mode == "retouch" or res.value is None or res.metadata is not None or m is not p.group.primary:
        return {}, ()
    when = _exif_time(res.value)
    if m.kind == "image" and dst.suffix.lower() in META_WRITABLE_EXTS:
        offset = when[-6:]
        return {"EXIF:DateTimeOriginal": when[:-6], "EXIF:OffsetTimeOriginal": offset}, ()
    if m.kind == "video" and not p.compress and not m.live:
        # 壓縮過的影片由 ffmpeg 寫入 creation_time
        return {"QuickTime:CreateDate": when}, ("-api", "QuickTimeUTC=1")
    return {}, ()


def _move(src: Path, dst: Path) -> None:
    if src == dst:
        return
    if os.path.lexists(dst) and not os.path.samefile(src, dst):
        raise FileExistsError(f"目標已存在：{dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.parent == dst.parent:
        os.rename(src, dst)  # 同資料夾內改名，包含只改大小寫
    else:
        shutil.move(src, dst)


def _describe(opts: Options, p: GroupPlan, index: int, total: int) -> None:
    res = p.resolution
    date = f"{res.value:%Y-%m-%d %H:%M:%S}（{res.source}）" if res.value else "無日期"
    tag = "[DRY] " if opts.dry_run else ""
    log(f"{tag}[{index}/{total}] {p.group.primary.path}  {date}")
    for m, dst in p.moves:
        if dst != m.path:
            note = "（Live Photo）" if m.live else ""
            log(f"    → {dst.name}{note}" if dst.parent == m.path.parent else f"    → {dst}{note}")
    if p.video is not None:
        log(f"    {'壓縮' if p.compress else '不壓縮'}：{p.compress_reason}")
    for w in res.warnings:
        log(f"    ⚠ {w}")


def _rows(p: GroupPlan) -> list[Row]:
    res = p.resolution
    rows = []
    for m, dst in p.moves:
        if m is p.group.primary and p.compress:
            action = "compress"
        elif dst != m.path:
            action = "rename"
        else:
            action = "keep"
        rows.append(
            Row(
                original=str(m.path),
                new=str(dst),
                kind=m.kind + ("(live)" if m.live else ""),
                action=action,
                date=f"{res.value:%Y-%m-%d %H:%M:%S%z}" if res.value else "",
                date_source=res.source or "",
                size_before=m.path.stat().st_size if m.path.exists() else "",
                message="；".join(
                    ([p.compress_reason] if m is p.group.primary and p.compress_reason else []) + res.warnings
                ),
            )
        )
    return rows


def execute(opts: Options, p: GroupPlan, et: exiftool.ExifTool | None) -> list[Row]:
    rows = _rows(p)
    if p.error:
        for r in rows:
            r.status, r.message = "error", p.error
        return rows
    if opts.dry_run:
        for r in rows:
            r.status = "dry-run"
        return rows

    primary = p.group.primary
    try:
        for (m, dst), row in zip(p.moves, rows):
            if m is primary and p.compress:
                assert p.video is not None
                log("    壓縮中 …")
                row.size_after = video.compress(m.path, dst, p.video, p.resolution.value, opts.tmp_dir)
            else:
                _move(m.path, dst)
                row.size_after = row.size_before
        if et is not None and p.resolution.value is not None:
            for (m, dst), row in zip(p.moves, rows):
                tags, extra = _metadata_tags(opts, p, m, dst)
                if tags:
                    row.message = "；".join(filter(None, [row.message, "補寫拍攝日期"]))
                et.write(dst, {**tags, **_time_tags(p.resolution.value)}, extra)
        for r in rows:
            r.status = "ok"
    except Exception as e:  # noqa: BLE001 - 單組失敗不影響其他組
        log(f"    ✗ {e}")
        for r in rows:
            if not r.status:
                r.status = "error"
                r.message = "；".join(filter(None, [r.message, str(e)]))
    return rows


def run(opts: Options) -> RunResult:
    result = RunResult()
    log(f"掃描 {opts.source} …")
    scanned = scan(opts.source)

    for tmp in scanned.stale_tmp:
        if opts.dry_run:
            log(f"[DRY] 將刪除中斷殘留的暫存檔：{tmp}")
        else:
            log(f"刪除中斷殘留的暫存檔：{tmp}")
            tmp.unlink(missing_ok=True)
        result.rows.append(Row(str(tmp), action="delete-stale", status="dry-run" if opts.dry_run else "ok"))
    for path in scanned.unknown:
        result.rows.append(Row(str(path), action="skip", status="skipped", message="不支援的檔案類型"))

    log(f"共 {len(scanned.groups)} 組檔案，讀取日期與影片資訊 …")
    plans = plan(opts, scanned.groups)

    et = None if opts.dry_run else exiftool.ExifTool().__enter__()
    current: GroupPlan | None = None
    try:
        for i, current in enumerate(plans, 1):
            _describe(opts, current, i, len(plans))
            result.rows.extend(execute(opts, current, et))
    except KeyboardInterrupt:
        result.interrupted = True
        if current is not None:
            for r in _rows(current):
                r.status = "interrupted"
                result.rows.append(r)
    finally:
        if et is not None:
            et.__exit__()
    result.errors = sum(1 for r in result.rows if r.status == "error")
    return result
