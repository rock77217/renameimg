from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from renameimg.dates import (
    Candidate,
    metadata_date,
    parse_exif_datetime,
    parse_filename_date,
    resolve,
)

TPE = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def tpe(*args: int) -> datetime:
    return datetime(*args, tzinfo=TPE)


@pytest.mark.parametrize(
    "name, expected",
    [
        ("IMG_20231005_142233", tpe(2023, 10, 5, 14, 22, 33)),
        ("VID_20231005_142233_1", tpe(2023, 10, 5, 14, 22, 33)),
        ("PXL_20231005_142233123", None),  # 毫秒黏在後面，不符合
        ("Screenshot 2023-10-05 at 14.22.33", tpe(2023, 10, 5, 14, 22, 33)),
        ("2023-10-05_14-22-33", tpe(2023, 10, 5, 14, 22, 33)),
        ("20231005142233", tpe(2023, 10, 5, 14, 22, 33)),
        ("IMG_20231399_142233", None),  # 不合法的月份
        ("19991231_235959", None),  # 年份超出範圍
        ("IMG_1234", None),
        ("03-迴圈與條件", None),
    ],
)
def test_parse_filename_date(name, expected):
    assert parse_filename_date(name, TPE) == expected


def test_parse_exif_datetime_variants():
    utc = timezone.utc
    assert parse_exif_datetime("2023:10:05 14:22:33", TPE) == tpe(2023, 10, 5, 14, 22, 33)
    assert parse_exif_datetime("2023:10:05 14:22:33", TPE, "+09:00") == datetime(
        2023, 10, 5, 14, 22, 33, tzinfo=timezone(timedelta(hours=9))
    )
    assert parse_exif_datetime("2023:10:05 06:22:33Z", TPE) == datetime(2023, 10, 5, 6, 22, 33, tzinfo=utc)
    assert parse_exif_datetime("2023:10:05 14:22:33.123+08:00", utc) == tpe(2023, 10, 5, 14, 22, 33)
    assert parse_exif_datetime("0000:00:00 00:00:00", TPE) is None
    assert parse_exif_datetime(None, TPE) is None
    assert parse_exif_datetime("garbage", TPE) is None


def test_metadata_date_priority_and_utc():
    # QuickTime CreateDate 是 UTC，要轉成台北時間
    tags = {"QuickTime:CreateDate": "2023:10:05 06:22:33"}
    assert metadata_date(tags, TPE) == tpe(2023, 10, 5, 14, 22, 33)
    # EXIF 優先於 QuickTime
    tags["EXIF:DateTimeOriginal"] = "2022:01:01 10:00:00"
    assert metadata_date(tags, TPE) == tpe(2022, 1, 1, 10, 0, 0)
    # 相機未設定時間的預設值要略過，改用下一個
    tags["EXIF:DateTimeOriginal"] = "2000:01:01 00:00:00"
    assert metadata_date(tags, TPE) == tpe(2023, 10, 5, 14, 22, 33)


def test_resolve_picks_earliest():
    res = resolve(
        [
            Candidate("metadata", tpe(2023, 10, 5, 14, 0, 0)),
            Candidate("mtime", tpe(2023, 10, 5, 13, 0, 0)),
            Candidate("filename", tpe(2023, 10, 5, 15, 0, 0)),
        ],
        TPE,
        NOW,
    )
    assert res.value == tpe(2023, 10, 5, 13, 0, 0)
    assert res.source == "mtime"
    assert res.warnings == []


def test_resolve_discards_garbage_and_future():
    res = resolve(
        [
            Candidate("metadata", tpe(2023, 10, 5, 14, 0, 0)),
            Candidate("birthtime", datetime(1970, 1, 1, tzinfo=timezone.utc)),
            Candidate("mtime", tpe(2030, 1, 1, 0, 0, 0)),
        ],
        TPE,
        NOW,
    )
    assert res.value == tpe(2023, 10, 5, 14, 0, 0)
    assert res.source == "metadata"
    assert len(res.warnings) == 2


def test_resolve_warns_when_far_earlier_than_metadata():
    res = resolve(
        [Candidate("metadata", tpe(2023, 10, 5, 14, 0, 0)), Candidate("mtime", tpe(2015, 1, 1, 0, 0, 0))],
        TPE,
        NOW,
    )
    assert res.source == "mtime"
    assert any("早超過一年" in w for w in res.warnings)


def test_resolve_tie_prefers_metadata():
    t = tpe(2023, 10, 5, 14, 0, 0)
    res = resolve([Candidate("mtime", t), Candidate("metadata", t)], TPE, NOW)
    assert res.source == "metadata"


def test_resolve_none_when_all_invalid():
    res = resolve([Candidate("mtime", datetime(1980, 1, 1, tzinfo=timezone.utc))], TPE, NOW)
    assert res.value is None
    assert "沒有可用的日期" in res.warnings


def test_resolve_converts_to_target_tz_and_drops_microseconds():
    res = resolve([Candidate("metadata", datetime(2023, 10, 5, 6, 0, 0, 999, tzinfo=timezone.utc))], TPE, NOW)
    assert res.value == tpe(2023, 10, 5, 14, 0, 0)
    assert res.value.utcoffset() == timedelta(hours=8)
