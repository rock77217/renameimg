"""拍攝日期判斷：從 metadata、檔案時間、檔名中取最早的合理值。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path

# 早於此時間的值視為相機未設定時間之類的垃圾值
MIN_VALID = datetime(2000, 1, 1, tzinfo=timezone.utc)
# 允許比現在晚一點點（時鐘誤差）
FUTURE_TOLERANCE = timedelta(days=1)
# 選中的日期比 metadata 早超過此值時發出警告
METADATA_GAP_WARN = timedelta(days=365)

# 同一時間時的偏好順序（數字小者優先）
SOURCE_PRIORITY = {"metadata": 0, "filename": 1, "birthtime": 2, "mtime": 3}


@dataclass(frozen=True)
class Candidate:
    source: str  # metadata | filename | birthtime | mtime
    value: datetime  # 一律為 aware datetime


@dataclass
class Resolution:
    value: datetime | None  # 已轉換到目標時區
    source: str | None
    metadata: datetime | None = None
    warnings: list[str] = field(default_factory=list)


def resolve(candidates: list[Candidate], tz: tzinfo, now: datetime | None = None) -> Resolution:
    """從候選日期中挑出最早的合理值。"""
    now = now or datetime.now(timezone.utc)
    warnings: list[str] = []
    valid: list[Candidate] = []
    for c in candidates:
        if c.value <= MIN_VALID or c.value > now + FUTURE_TOLERANCE:
            warnings.append(f"丟棄異常日期 {c.source}={_fmt(c.value.astimezone(tz))}")
        else:
            valid.append(c)

    metadata = next((c.value for c in valid if c.source == "metadata"), None)
    if not valid:
        warnings.append("沒有可用的日期")
        return Resolution(None, None, metadata, warnings)

    chosen = min(valid, key=lambda c: (c.value, SOURCE_PRIORITY.get(c.source, 99)))
    if metadata is not None and metadata - chosen.value > METADATA_GAP_WARN:
        warnings.append(
            f"採用的 {chosen.source} 比 metadata 早超過一年"
            f"（metadata={_fmt(metadata.astimezone(tz))}），請人工確認"
        )
    value = chosen.value.astimezone(tz).replace(microsecond=0)
    return Resolution(value, chosen.source, metadata, warnings)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- 檔名日期

_FILENAME_RE = re.compile(
    r"(?<!\d)(\d{4})[-_.]?(\d{2})[-_.]?(\d{2})"
    r"(?:[ _T-]|\s+at\s+)?"
    r"(\d{2})[-_.:]?(\d{2})[-_.:]?(\d{2})(?!\d)"
)


def parse_filename_date(name: str, tz: tzinfo) -> datetime | None:
    """解析檔名中的日期時間，例如 IMG_20231005_142233、2023-10-05 at 14.22.33。"""
    for m in _FILENAME_RE.finditer(name):
        year = int(m.group(1))
        if not 2000 <= year <= 2100:
            continue
        try:
            dt = datetime(*(int(g) for g in m.groups()))
        except ValueError:
            continue
        return dt.replace(tzinfo=tz)
    return None


# ---------------------------------------------------------------- metadata 日期

_EXIF_RE = re.compile(
    r"^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_offset(value: str | None) -> tzinfo | None:
    if not value:
        return None
    value = value.strip()
    if value == "Z":
        return timezone.utc
    m = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", value)
    if not m:
        return None
    sign = -1 if m.group(1) == "-" else 1
    return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))


def parse_exif_datetime(value: object, default_tz: tzinfo, offset: str | None = None) -> datetime | None:
    """解析 exiftool 輸出的日期字串；字串內的時區優先，其次 offset，最後 default_tz。"""
    if not isinstance(value, str):
        return None
    m = _EXIF_RE.match(value.strip())
    if not m:
        return None
    try:
        dt = datetime(*(int(g) for g in m.groups()[:6]))
    except ValueError:  # 0000:00:00 00:00:00 之類
        return None
    tz = parse_offset(m.group(7)) or parse_offset(offset) or default_tz
    return dt.replace(tzinfo=tz)


def metadata_date(tags: dict, tz: tzinfo) -> datetime | None:
    """依優先順序從 exiftool 標籤（-G 格式）取出拍攝時間。"""
    lookups = [
        # 照片：EXIF 是當地時間，搭配 OffsetTimeOriginal
        ("EXIF:DateTimeOriginal", tags.get("EXIF:OffsetTimeOriginal"), tz),
        # Apple 影片：Keys:CreationDate 通常帶時區
        ("QuickTime:CreationDate", None, tz),
        # 一般影片：QuickTime CreateDate 依規範為 UTC
        ("QuickTime:CreateDate", None, timezone.utc),
        ("EXIF:CreateDate", tags.get("EXIF:OffsetTimeDigitized"), tz),
        ("XMP:DateTimeOriginal", None, tz),
        ("XMP:DateCreated", None, tz),
    ]
    for key, offset, default_tz in lookups:
        dt = parse_exif_datetime(tags.get(key), default_tz, offset)
        if dt is not None and dt > MIN_VALID:
            return dt
    return None


# ---------------------------------------------------------------- 彙整

def file_candidates(path: Path) -> list[Candidate]:
    st = path.stat()
    result = []
    birth = getattr(st, "st_birthtime", None)
    if birth:
        result.append(Candidate("birthtime", datetime.fromtimestamp(birth, timezone.utc)))
    result.append(Candidate("mtime", datetime.fromtimestamp(st.st_mtime, timezone.utc)))
    return result


def collect_candidates(path: Path, tags: dict, tz: tzinfo) -> list[Candidate]:
    candidates = []
    meta = metadata_date(tags, tz)
    if meta is not None:
        candidates.append(Candidate("metadata", meta))
    from_name = parse_filename_date(path.stem, tz)
    if from_name is not None:
        candidates.append(Candidate("filename", from_name))
    candidates.extend(file_candidates(path))
    return candidates
