"""整合測試：用 ffmpeg 與 exiftool 產生真實的小樣本檔案跑完整流程。"""

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from renameimg.dates import parse_exif_datetime
from renameimg.pipeline import Options, run
from renameimg.video import MARKER, probe

pytestmark = pytest.mark.skipif(
    not all(shutil.which(t) for t in ("ffmpeg", "ffprobe", "exiftool")),
    reason="需要 ffmpeg、ffprobe、exiftool",
)

TPE = ZoneInfo("Asia/Taipei")
OLD = datetime(2024, 1, 1, tzinfo=TPE).timestamp()  # 比 metadata 晚的檔案時間


def sh(*args: str) -> None:
    subprocess.run(args, check=True, capture_output=True)


def make_jpg(path: Path, exif_date: str | None = None) -> None:
    sh("ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1", str(path))
    if exif_date:
        sh("exiftool", "-overwrite_original", f"-EXIF:DateTimeOriginal={exif_date}", str(path))
    os.utime(path, (OLD, OLD))


def make_video(path: Path, creation_time: str | None = None, seconds: int = 2) -> None:
    args = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=s=320x240:r=60:d={seconds}",
        "-f", "lavfi", "-i", f"sine=d={seconds}",
        "-c:v", "libx264", "-c:a", "aac", "-shortest",
    ]
    if creation_time:
        args += ["-metadata", f"creation_time={creation_time}"]
    sh(*args, str(path))
    os.utime(path, (OLD, OLD))


def exif(path: Path, *tags: str) -> str:
    return subprocess.run(["exiftool", "-s3", *tags, str(path)], capture_output=True, text=True).stdout.strip()


def opts(root: Path, mode: str = "run", **kw) -> Options:
    return Options(mode=mode, source=root, tz=TPE, jobs=2, **kw)


def names(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def test_full_run(tmp_path):
    make_jpg(tmp_path / "IMG_0001.JPG", "2023:10:05 14:22:33")
    make_jpg(tmp_path / "IMG_0002.JPG", "2023:10:05 14:22:33")  # 同一秒 → _1
    make_jpg(tmp_path / "live.HEIC.jpg")  # 無 metadata，只能靠檔案時間
    make_jpg(tmp_path / "IMG_0003.JPG", "2023:10:06 08:00:00")
    make_video(tmp_path / "IMG_0003.MOV")  # Live Photo 配對
    (tmp_path / "IMG_0003.AAE").write_text("aae")
    make_video(tmp_path / "lecture.mov", creation_time="2023-10-07T02:00:00Z")
    (tmp_path / "readme.txt").write_text("x")

    result = run(opts(tmp_path))
    assert result.errors == 0, [r for r in result.rows if r.status == "error"]

    assert names(tmp_path) == [
        "IMG_20231005_142233.jpg",
        "IMG_20231005_142233_1.jpg",
        "IMG_20231006_080000.aae",
        "IMG_20231006_080000.jpg",
        "IMG_20231006_080000.mov",
        "IMG_20240101_000000.jpg",
        "VID_20231007_100000.mp4",
        "readme.txt",
    ]

    # 影片已壓縮成 HEVC、降到 30fps、帶標記；Live Photo 的 MOV 不壓縮
    out = probe(tmp_path / "VID_20231007_100000.mp4")
    assert out.codec == "hevc"
    assert round(out.fps) == 30
    assert out.marked
    assert out.tags["creation_time"].startswith("2023-10-07T02:00:00")
    assert probe(tmp_path / "IMG_20231006_080000.mov").codec == "h264"

    # 缺少日期的照片補寫 EXIF；檔案時間設為拍攝時間
    filled = tmp_path / "IMG_20240101_000000.jpg"
    assert exif(filled, "-EXIF:DateTimeOriginal") == "2024:01:01 00:00:00"
    assert exif(filled, "-EXIF:OffsetTimeOriginal") == "+08:00"
    shot = tmp_path / "IMG_20231005_142233.jpg"
    assert datetime.fromtimestamp(shot.stat().st_mtime, TPE) == datetime(2023, 10, 5, 14, 22, 33, tzinfo=TPE)
    if hasattr(shot.stat(), "st_birthtime"):
        assert datetime.fromtimestamp(shot.stat().st_birthtime, TPE) == datetime(2023, 10, 5, 14, 22, 33, tzinfo=TPE)

    # 原本已有的 EXIF 不被覆蓋
    assert exif(shot, "-EXIF:OffsetTimeOriginal") == ""

    # 重跑不應再有任何變動
    before = names(tmp_path)
    again = run(opts(tmp_path))
    assert again.errors == 0
    assert names(tmp_path) == before
    assert {r.action for r in again.rows if r.action != "skip"} == {"keep"}


def test_dry_run_changes_nothing(tmp_path):
    make_jpg(tmp_path / "a.jpg", "2023:10:05 14:22:33")
    make_video(tmp_path / "b.mov")
    (tmp_path / ".renameimg-tmp-x.mp4").write_bytes(b"")
    before = {p: p.stat().st_mtime for p in tmp_path.iterdir()}

    result = run(opts(tmp_path, dry_run=True))
    assert {r.status for r in result.rows} == {"dry-run"}
    assert {p: p.stat().st_mtime for p in tmp_path.iterdir()} == before


def test_target_dir_keeps_structure(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "2023" / "trip").mkdir(parents=True)
    make_jpg(src / "2023" / "trip" / "a.jpg", "2023:10:05 14:22:33")

    result = run(opts(src, mode="rename", target=dst))
    assert result.errors == 0
    assert names(dst) == ["2023/trip/IMG_20231005_142233.jpg"]
    assert names(src) == []


def test_compress_mode_keeps_name_and_cleans_stale_tmp(tmp_path):
    make_video(tmp_path / "03-迴圈.MOV")
    (tmp_path / ".renameimg-tmp-old.mp4").write_bytes(b"partial")

    result = run(opts(tmp_path, mode="compress"))
    assert result.errors == 0
    assert names(tmp_path) == ["03-迴圈.mp4"]
    assert probe(tmp_path / "03-迴圈.mp4").tags["comment"] == MARKER


def test_failed_verification_keeps_original(tmp_path, monkeypatch):
    from renameimg import video

    make_video(tmp_path / "a.mov")
    monkeypatch.setattr(video, "verify", lambda src, out: ["模擬失敗"])
    result = run(opts(tmp_path, mode="compress"))
    assert result.errors == 1
    assert names(tmp_path) == ["a.mov"]


def test_retouch_only_sets_times(tmp_path):
    make_jpg(tmp_path / "a.jpg", "2023:10:05 14:22:33")
    result = run(opts(tmp_path, mode="retouch"))
    assert result.errors == 0
    p = tmp_path / "a.jpg"
    assert names(tmp_path) == ["a.jpg"]
    assert datetime.fromtimestamp(p.stat().st_mtime, TPE) == datetime(2023, 10, 5, 14, 22, 33, tzinfo=TPE)
    assert parse_exif_datetime(exif(p, "-EXIF:DateTimeOriginal"), TPE) is not None


def test_interrupt_reports_current_file_and_keeps_original(tmp_path, monkeypatch):
    from renameimg import video

    make_video(tmp_path / "a.mov")

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(video, "compress", interrupt)
    result = run(opts(tmp_path, mode="compress"))
    assert result.interrupted
    assert [r.status for r in result.rows] == ["interrupted"]
    assert names(tmp_path) == ["a.mov"]
