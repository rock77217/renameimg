"""影片分析、壓縮決策、ffmpeg 指令、輸出驗證。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .media import TMP_PREFIX

MARKER = "renameimg:v2"

CRF = 26
PRESET = "slow"
X265_PARAMS = "keyint=300:min-keyint=30:log-level=error"
MAX_SHORT_SIDE = 1080
MAX_FPS = 30
AUDIO_ARGS = ["-c:a", "aac", "-b:a", "96k", "-ac", "1"]
# HEVC 位元率低於此門檻就不重壓（bps）
HEVC_SKIP_BITRATE_HD = 4_000_000
HEVC_SKIP_BITRATE_UHD = 10_000_000
DURATION_TOLERANCE = 1.0
HDR_TRANSFERS = {"arib-std-b67", "smpte2084"}


class CompressError(RuntimeError):
    pass


@dataclass
class VideoInfo:
    codec: str | None = None
    width: int = 0
    height: int = 0
    rotation: int = 0
    fps: float | None = None
    bitrate: int | None = None
    duration: float | None = None
    has_audio: bool = False
    color_primaries: str | None = None
    color_transfer: str | None = None
    color_space: str | None = None
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def display_size(self) -> tuple[int, int]:
        if abs(self.rotation) % 180 == 90:
            return self.height, self.width
        return self.width, self.height

    @property
    def short_side(self) -> int:
        return min(self.display_size)

    @property
    def is_hdr(self) -> bool:
        return self.color_transfer in HDR_TRANSFERS

    @property
    def marked(self) -> bool:
        return MARKER in self.tags.get("comment", "")

    @property
    def has_creation_time(self) -> bool:
        return bool(self.tags.get("creation_time"))


def _rate(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    num, _, den = value.partition("/")
    try:
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return None


def _int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def probe(path: Path) -> VideoInfo:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise CompressError(f"ffprobe 失敗：{proc.stderr.strip()}")
    return parse_probe(json.loads(proc.stdout))


def parse_probe(data: dict) -> VideoInfo:
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    info = VideoInfo(
        tags={k.lower(): v for k, v in fmt.get("tags", {}).items()},
        duration=_float(fmt.get("duration")),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )
    video = next(
        (s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")),
        None,
    )
    if video is None:
        return info
    info.codec = video.get("codec_name")
    info.width = _int(video.get("width")) or 0
    info.height = _int(video.get("height")) or 0
    info.fps = _rate(video.get("avg_frame_rate")) or _rate(video.get("r_frame_rate"))
    info.bitrate = _int(video.get("bit_rate")) or _int(fmt.get("bit_rate"))
    info.color_primaries = video.get("color_primaries")
    info.color_transfer = video.get("color_transfer")
    info.color_space = video.get("color_space")
    rotation = _int(video.get("tags", {}).get("rotate"))
    for side in video.get("side_data_list", []):
        if "rotation" in side:
            rotation = _int(side["rotation"])
    info.rotation = rotation or 0
    return info


def decide(info: VideoInfo) -> tuple[bool, str]:
    """回傳 (是否壓縮, 原因)。"""
    if info.marked:
        return False, "已有 renameimg 標記"
    if info.codec is None:
        return False, "沒有影像串流"
    if info.codec == "hevc":
        if info.bitrate is None:
            return False, "HEVC 但無法判斷位元率"
        limit = HEVC_SKIP_BITRATE_UHD if info.short_side > MAX_SHORT_SIDE else HEVC_SKIP_BITRATE_HD
        if info.bitrate <= limit:
            return False, f"HEVC {info.bitrate / 1e6:.1f} Mbps 未超過門檻"
        return True, f"HEVC {info.bitrate / 1e6:.1f} Mbps 超過門檻"
    return True, f"{info.codec} 轉 HEVC"


def build_command(src: Path, dst: Path, info: VideoInfo, creation_time: datetime | None) -> list[str]:
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-stats", "-i", str(src)]
    cmd += ["-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "0"]

    filters = []
    if info.short_side > MAX_SHORT_SIDE:
        width, height = info.display_size
        filters.append(f"scale=-2:{MAX_SHORT_SIDE}" if width >= height else f"scale={MAX_SHORT_SIDE}:-2")
    if info.fps and info.fps > MAX_FPS + 1:
        filters.append(f"fps={MAX_FPS}")
    if filters:
        cmd += ["-vf", ",".join(filters)]

    cmd += ["-c:v", "libx265", "-preset", PRESET, "-crf", str(CRF), "-x265-params", X265_PARAMS]
    if info.is_hdr:
        cmd += ["-pix_fmt", "yuv420p10le"]
        for flag, value in (
            ("-color_primaries", info.color_primaries),
            ("-color_trc", info.color_transfer),
            ("-colorspace", info.color_space),
        ):
            if value:
                cmd += [flag, value]
    else:
        cmd += ["-pix_fmt", "yuv420p"]
    cmd += ["-tag:v", "hvc1", *AUDIO_ARGS]
    # use_metadata_tags 保留 Apple 的 GPS 等 mdta 標籤
    cmd += ["-movflags", "+faststart+use_metadata_tags", "-metadata", f"comment={MARKER}"]
    if creation_time is not None and not info.has_creation_time:
        utc = creation_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
        cmd += ["-metadata", f"creation_time={utc}"]
    cmd.append(str(dst))
    return cmd


def verify(src: VideoInfo, out: Path) -> list[str]:
    errors = []
    if not out.exists() or out.stat().st_size == 0:
        return ["輸出檔不存在或為 0 byte"]
    try:
        result = probe(out)
    except CompressError as e:
        return [str(e)]
    if result.codec != "hevc":
        errors.append(f"輸出影像編碼為 {result.codec}")
    if src.has_audio and not result.has_audio:
        errors.append("輸出缺少音訊")
    if src.duration is None or result.duration is None:
        errors.append("無法取得影片長度")
    elif abs(src.duration - result.duration) > DURATION_TOLERANCE:
        errors.append(f"長度不符：原檔 {src.duration:.1f}s，輸出 {result.duration:.1f}s")
    return errors


def compress(
    src: Path,
    final: Path,
    info: VideoInfo,
    creation_time: datetime | None,
    tmp_dir: Path | None = None,
) -> int:
    """壓縮 src 並以 final 取代；驗證通過才刪除原檔。回傳輸出大小。

    流程：本機暫存轉檔 → 驗證 → 複製到目的資料夾的暫存檔 → 確認大小 →
    改名為 final → 刪除原檔。任何時刻都至少有一份完整的檔案。
    """
    with tempfile.TemporaryDirectory(prefix="renameimg-", dir=tmp_dir) as td:
        local = Path(td) / "out.mp4"
        proc = subprocess.run(build_command(src, local, info, creation_time))
        if proc.returncode != 0:
            raise CompressError(f"ffmpeg 失敗（exit {proc.returncode}）")
        errors = verify(info, local)
        if errors:
            raise CompressError("驗證失敗：" + "；".join(errors))
        size = local.stat().st_size

        final.parent.mkdir(parents=True, exist_ok=True)
        staging = final.parent / f"{TMP_PREFIX}{final.name}"
        try:
            shutil.copyfile(local, staging)
            if staging.stat().st_size != size:
                raise CompressError("複製回目的地後大小不符")
        except BaseException:
            staging.unlink(missing_ok=True)
            raise

    replaces_src = final.exists() and os.path.samefile(final, src)
    os.replace(staging, final)
    if not replaces_src:
        src.unlink()
    return size
