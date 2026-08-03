"""한글 경로 입출력과 EXIF 회전 (섹션 12-1, 12-6)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from conftest import make_image
from PIL import Image

from app.imageio import imread, imwrite, read_exif_oriented_size, resize_long_edge


def test_한글_경로_읽기(tmp_path: Path):
    p = make_image(tmp_path / "한글 폴더" / "사진 １.jpg", 400, 300)
    img = imread(p)
    assert img.shape == (300, 400, 3)


def test_한글_경로_쓰기_후_다시_읽기(tmp_path: Path):
    src = make_image(tmp_path / "입력" / "테스트.jpg", 200, 150)
    dst = tmp_path / "출력 폴더" / "결과 이미지.png"
    imwrite(dst, imread(src))
    assert dst.is_file()
    assert imread(dst).shape == (150, 200, 3)


def test_없는_파일은_조용히_실패하지_않는다(tmp_path: Path):
    # cv2.imread는 None을 돌려주고 지나갑니다. 우리는 반드시 터져야 합니다.
    with pytest.raises(FileNotFoundError):
        imread(tmp_path / "없는 파일.jpg")


def test_깨진_파일은_예외(tmp_path: Path):
    bad = tmp_path / "깨진.jpg"
    bad.write_bytes(b"not an image at all")
    with pytest.raises((ValueError, OSError)):
        imread(bad)


def test_exif_회전이_적용된다(tmp_path: Path):
    """Orientation=6은 시계방향 90도 회전. 세로 사진이 눕지 않아야 합니다."""
    p = tmp_path / "회전.jpg"
    Image.fromarray(np.zeros((100, 300, 3), dtype=np.uint8)).save(p)

    ex = Image.Exif()
    ex[274] = 6  # Orientation
    Image.fromarray(np.zeros((100, 300, 3), dtype=np.uint8)).save(p, exif=ex.tobytes())

    img = imread(p)
    assert img.shape[0] > img.shape[1], "EXIF 회전이 적용되지 않아 사진이 누웠습니다"
    assert read_exif_oriented_size(p) == (100, 300)

    raw = imread(p, apply_exif_orientation=False)
    assert raw.shape[:2] == (100, 300), "회전 미적용 경로가 회전을 적용했습니다"


def test_resize_long_edge는_확대하지_않는다():
    small = np.zeros((50, 80, 3), dtype=np.uint8)
    assert resize_long_edge(small, 1024).shape == (50, 80, 3)
    big = np.zeros((2000, 1000, 3), dtype=np.uint8)
    out = resize_long_edge(big, 1024)
    assert max(out.shape[:2]) == 1024
