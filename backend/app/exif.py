"""EXIF 추출. 없는 값은 None으로 두고 규칙 쪽에서 가드를 건너뜁니다."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import ExifTags, Image

__all__ = ["Exif", "read_exif"]

from dataclasses import asdict, dataclass

_TAG_BY_NAME = {name: tag for tag, name in ExifTags.TAGS.items()}


@dataclass(slots=True)
class Exif:
    iso: int | None = None
    exposure_time: float | None = None  # 초
    f_number: float | None = None
    flash: bool | None = None
    datetime_original: datetime | None = None
    focal_length: float | None = None
    orientation: int | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["datetime_original"] = (
            self.datetime_original.isoformat() if self.datetime_original else None
        )
        return d


def _num(value) -> float | None:
    """IFDRational 등 다양한 EXIF 수치 표현을 float로 정규화한다."""
    if value is None:
        return None
    try:
        if isinstance(value, tuple) and len(value) == 2:
            num, den = value
            return float(num) / float(den) if den else None
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _parse_dt(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def read_exif(path: str | Path) -> Exif:
    """EXIF를 읽는다. 태그가 없거나 파일이 EXIF를 지원하지 않으면 빈 Exif."""
    try:
        with Image.open(path) as pil:
            raw = pil.getexif()
            if not raw:
                return Exif()
            merged = dict(raw)
            # 노출·ISO 등 실제 촬영 정보는 Exif IFD 하위에 들어있다.
            try:
                merged.update(dict(raw.get_ifd(ExifTags.IFD.Exif)))
            except (AttributeError, KeyError, ValueError):
                pass
    except (OSError, ValueError):
        return Exif()

    def tag(name: str):
        return merged.get(_TAG_BY_NAME.get(name, -1))

    iso = tag("ISOSpeedRatings") or tag("PhotographicSensitivity")
    if isinstance(iso, (list, tuple)):
        iso = iso[0] if iso else None

    flash_raw = tag("Flash")
    flash = None if flash_raw is None else bool(int(flash_raw) & 0x1)

    return Exif(
        iso=int(iso) if iso is not None else None,
        exposure_time=_num(tag("ExposureTime")),
        f_number=_num(tag("FNumber")),
        flash=flash,
        datetime_original=_parse_dt(tag("DateTimeOriginal") or tag("DateTime")),
        focal_length=_num(tag("FocalLength")),
        orientation=int(tag("Orientation")) if tag("Orientation") is not None else None,
    )
