"""한글(비ASCII) 경로에서도 안전한 이미지 입출력.

`cv2.imread`/`cv2.imwrite`는 Windows에서 비ASCII 경로에 대해 예외 없이 조용히
실패합니다(`None` 반환 / `False` 반환). 프로젝트 전체에서 OpenCV의 파일 API를
직접 부르지 말고 이 모듈만 사용하세요.

EXIF 회전도 여기서 한 번에 정규화합니다(섹션 12-6). 읽기 시점에 회전을 적용해
두면 이후 모든 측정·구도 분석·종횡비 판정이 화면에 보이는 방향과 일치합니다.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

__all__ = [
    "imread",
    "imwrite",
    "imencode_bytes",
    "resize_long_edge",
    "read_exif_oriented_size",
]


def _pil_to_bgr(pil: Image.Image) -> np.ndarray:
    """PIL 이미지를 OpenCV BGR ndarray로 변환한다."""
    rgb = np.asarray(pil.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def imread(path: str | Path, apply_exif_orientation: bool = True) -> np.ndarray:
    """이미지를 BGR ndarray로 읽는다. 실패하면 예외를 던진다.

    조용한 `None` 반환을 허용하지 않는 것이 핵심입니다. 한글 경로에서 로딩이
    실패했는데 파이프라인이 계속 굴러가면 원인을 찾기 매우 어렵습니다.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"이미지를 찾을 수 없습니다: {path}")

    if apply_exif_orientation:
        # Pillow는 유니코드 경로를 문제없이 다루고, exif_transpose로 회전을 흡수한다.
        try:
            with Image.open(path) as pil:
                pil = ImageOps.exif_transpose(pil)
                return _pil_to_bgr(pil)
        except OSError:
            pass  # Pillow가 못 여는 포맷이면 OpenCV 디코더로 폴백

    buf = np.fromfile(str(path), dtype=np.uint8)
    # cv2.imdecode는 IMREAD_COLOR에서 EXIF 회전을 **자동 적용**합니다. 회전을
    # 원하지 않을 때 명시적으로 꺼주지 않으면 플래그가 거짓말이 됩니다.
    flags = cv2.IMREAD_COLOR
    if not apply_exif_orientation:
        flags |= cv2.IMREAD_IGNORE_ORIENTATION
    img = cv2.imdecode(buf, flags)
    if img is None:
        raise ValueError(f"이미지를 디코드할 수 없습니다: {path}")
    return img


def imwrite(path: str | Path, img: np.ndarray, params: list[int] | None = None) -> None:
    """BGR ndarray를 파일로 저장한다. 확장자로 인코더를 고른다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(path.suffix or ".png", img, params or [])
    if not ok:
        raise ValueError(f"이미지를 인코드할 수 없습니다: {path}")
    buf.tofile(str(path))


def imencode_bytes(img: np.ndarray, ext: str = ".jpg", quality: int = 90) -> bytes:
    """BGR ndarray를 메모리상의 바이트로 인코드한다(HTTP 응답용)."""
    params: list[int] = []
    if ext.lower() in (".jpg", ".jpeg"):
        params = [cv2.IMWRITE_JPEG_QUALITY, quality]
    ok, buf = cv2.imencode(ext, img, params)
    if not ok:
        raise ValueError("이미지를 인코드할 수 없습니다")
    return bytes(buf)


def resize_long_edge(img: np.ndarray, long_edge: int) -> np.ndarray:
    """긴 변을 지정 픽셀로 맞춘다. 이미 작으면 그대로 둔다(확대하지 않음)."""
    h, w = img.shape[:2]
    cur = max(h, w)
    if cur <= long_edge:
        return img
    scale = long_edge / float(cur)
    return cv2.resize(
        img,
        (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
        interpolation=cv2.INTER_AREA,
    )


def read_exif_oriented_size(path: str | Path) -> tuple[int, int]:
    """디코드 없이 EXIF 회전이 반영된 (width, height)를 얻는다."""
    with Image.open(path) as pil:
        pil = ImageOps.exif_transpose(pil)
        return int(pil.width), int(pil.height)
