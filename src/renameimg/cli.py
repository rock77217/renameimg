"""命令列介面。"""

from __future__ import annotations

import argparse
import csv
import shutil
import signal
import sys
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .pipeline import MODES, Options, Row, run

DEFAULT_TZ = "Asia/Taipei"

MODE_HELP = {
    "run": "改名並壓縮影片（預設流程）",
    "rename": "只改名與調整時間，不壓縮",
    "compress": "只壓縮影片，保留原檔名",
    "retouch": "只把檔案時間設為拍攝日期，不改名",
}


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="renameimg",
        description="依拍攝日期重新命名照片與影片，並將影片壓縮為 HEVC。",
    )
    sub = parser.add_subparsers(dest="mode", required=True)
    for mode in MODES:
        p = sub.add_parser(mode, help=MODE_HELP[mode], description=MODE_HELP[mode])
        p.add_argument("source", type=Path, help="來源資料夾")
        p.add_argument("-t", "--target", type=Path, help="輸出資料夾（保留相對路徑結構）；預設就地處理")
        p.add_argument("-z", "--tz", default=DEFAULT_TZ, help=f"時區，預設 {DEFAULT_TZ}")
        p.add_argument("-n", "--dry-run", action="store_true", help="只列出要做的事，不實際變更")
        p.add_argument("-j", "--jobs", type=int, default=4, help="讀取 metadata 的平行數，預設 4")
        p.add_argument("--tmp-dir", type=Path, help="本機轉檔暫存資料夾，預設為 $TMPDIR 或系統暫存")
        p.add_argument("--report", type=Path, help="CSV 報告路徑，預設為目前資料夾下的 renameimg-report-<時間>.csv")
    return parser.parse_args(argv)


def write_report(path: Path, rows: list[Row]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig 讓 Excel 能正確顯示中文
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[fld.name for fld in fields(Row)])
        writer.writeheader()
        writer.writerows(asdict(r) for r in rows)


def _sigterm_as_interrupt(signum: int, frame: object) -> None:
    # docker stop 送的是 SIGTERM；比照 Ctrl+C 處理，才會寫出報告並停止 ffmpeg
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    signal.signal(signal.SIGTERM, _sigterm_as_interrupt)

    source = args.source.expanduser().resolve()
    if not source.is_dir():
        sys.exit(f"來源資料夾不存在：{args.source}")
    try:
        tz = ZoneInfo(args.tz)
    except ZoneInfoNotFoundError:
        sys.exit(f"無效的時區：{args.tz}")
    tools = ["exiftool"] + (["ffmpeg", "ffprobe"] if args.mode in ("run", "compress") else [])
    missing = [t for t in tools if shutil.which(t) is None]
    if missing:
        sys.exit(f"缺少必要工具：{', '.join(missing)}（macOS 可用 brew install exiftool ffmpeg；Docker 映像已內建）")

    opts = Options(
        mode=args.mode,
        source=source,
        tz=tz,
        target=args.target.expanduser().resolve() if args.target else None,
        dry_run=args.dry_run,
        jobs=max(1, args.jobs),
        tmp_dir=args.tmp_dir,
    )
    report = args.report or Path(f"renameimg-report-{datetime.now():%Y%m%d_%H%M%S}.csv")

    try:
        result = run(opts)
    except KeyboardInterrupt:  # 掃描或規劃階段就被中斷，尚未變更任何檔案
        print("\n已中斷，尚未處理任何檔案。", file=sys.stderr)
        return 130
    write_report(report, result.rows)
    if result.interrupted:
        print(f"\n已中斷，已處理 {len(result.rows)} 筆。下次執行會自動清除殘留的暫存檔。報告：{report}")
        return 130
    print(f"\n完成：{len(result.rows)} 筆，錯誤 {result.errors} 筆。報告：{report}")
    return 1 if result.errors else 0


if __name__ == "__main__":
    sys.exit(main())
