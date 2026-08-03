"""테스트 픽스처: 합성 사진 생성.

실제 사진 없이도 규칙 경로를 전부 통과시킬 수 있어야 합니다. 한글 파일명,
세로 사진, 야경 EXIF, 저해상도 등 완료 기준에 나온 조건을 전부 만듭니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import ExifTags, Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_T = {name: tag for tag, name in ExifTags.TAGS.items()}


def make_image(
    path: Path,
    width: int = 1600,
    height: int = 1200,
    brightness: int = 128,
    contrast: float = 1.0,
    saturation: float = 1.0,
    detail: bool = True,
    exif: dict | None = None,
    orientation: int | None = None,
) -> Path:
    """제어된 통계를 갖는 합성 이미지를 저장한다 (RGB, Pillow)."""
    rng = np.random.default_rng(1234)
    # 세로 그라디언트 + 색 블록으로 히스토그램 퍼짐과 채도를 만든다.
    grad = np.linspace(-1.0, 1.0, height, dtype=np.float32)[:, None]
    base = brightness + grad * (60.0 * contrast)
    img = np.repeat(base[:, :, None], 3, axis=2)
    img = np.repeat(img, width, axis=1) if img.shape[1] == 1 else np.broadcast_to(
        img, (height, width, 3)
    ).copy()

    # 채도: 채널을 서로 벌린다.
    img[..., 0] += 30.0 * saturation
    img[..., 2] -= 30.0 * saturation

    if detail:
        # 고주파 디테일 (선명도 통계용) + 오프센터 관심영역
        img += rng.normal(0, 8, img.shape).astype(np.float32)
        cy, cx = int(height * 0.32), int(width * 0.72)
        r = min(width, height) // 8
        ys, xs = np.mgrid[0:height, 0:width]
        blob = ((ys - cy) ** 2 + (xs - cx) ** 2) < r * r
        img[blob] = np.clip(img[blob] + 70.0, 0, 255)

    arr = np.clip(img, 0, 255).astype(np.uint8)
    pil = Image.fromarray(arr, mode="RGB")

    path.parent.mkdir(parents=True, exist_ok=True)
    if exif or orientation is not None:
        ex = Image.Exif()
        for key, value in (exif or {}).items():
            ex[_T[key]] = value
        if orientation is not None:
            ex[_T["Orientation"]] = orientation
        pil.save(path, quality=95, exif=ex.tobytes())
    else:
        pil.save(path, quality=95)
    return path


@pytest.fixture
def photo_dir(tmp_path: Path) -> Path:
    """한글 폴더 안에 여러 성격의 사진을 만든다."""
    d = tmp_path / "사진 모음" / "여행"
    d.mkdir(parents=True)

    make_image(
        d / "밝은_가로.jpg",
        1600, 1200, brightness=150, detail=True,
        exif={"DateTimeOriginal": "2024:05:01 10:00:00", "ISOSpeedRatings": 100,
              "ExposureTime": (1, 500), "FNumber": (28, 10)},
    )
    make_image(
        d / "어두운_야경.jpg",
        1600, 1200, brightness=40, detail=True,
        exif={"DateTimeOriginal": "2024:05:01 22:30:00", "ISOSpeedRatings": 3200,
              "ExposureTime": (1, 8), "FNumber": (18, 10)},
    )
    make_image(
        d / "세로_인물.jpg",
        1200, 1600, brightness=130, detail=True,
        exif={"DateTimeOriginal": "2024:05:01 10:05:00", "ISOSpeedRatings": 200,
              "ExposureTime": (1, 250)},
    )
    make_image(
        d / "저해상도.jpg",
        800, 600, brightness=120, detail=True,
        exif={"DateTimeOriginal": "2024:05:01 14:00:00", "ISOSpeedRatings": 400,
              "ExposureTime": (1, 200)},
    )
    make_image(
        d / "노_exif.jpg", 1920, 1080, brightness=110, detail=True,
    )
    return d


@pytest.fixture(autouse=True)
def isolated_rules(tmp_path: Path, monkeypatch):
    """규칙 파일을 격리한다. 없으면 테스트가 저장소의 grade.yaml을 덮어씁니다."""
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    repo = Path(__file__).resolve().parents[2]
    for kind in ("grade", "motion"):
        src = repo / f"{kind}.yaml"
        if src.is_file():
            (rules_dir / f"{kind}.yaml").write_text(
                src.read_text(encoding="utf-8"), encoding="utf-8"
            )
    monkeypatch.setenv("PVT_RULES_DIR", str(rules_dir))
    return rules_dir


@pytest.fixture
def state(tmp_path: Path, monkeypatch):
    """격리된 work 디렉터리를 가진 AppState."""
    work = tmp_path / "work"
    monkeypatch.setenv("PVT_WORK_DIR", str(work))
    from app.cache import WorkDirs
    from app.state import AppState

    return AppState(WorkDirs(work))
