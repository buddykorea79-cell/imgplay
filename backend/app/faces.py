"""얼굴 검출 (OpenCV DNN SSD).

Haar cascade는 오탐이 많아 쓰지 않습니다. ResNet-10 SSD 얼굴 검출기를 쓰되,
모델 파일이 없으면 **조용히 빈 결과를 돌려주고 파이프라인은 계속 굴러갑니다** —
얼굴 검출은 채도 상한(skin_max)과 2단계 줌 목표점을 위한 보조 신호일 뿐이라
없다고 해서 보정 자체가 불가능해지지는 않습니다.

모델 파일은 `scripts/fetch_face_model.sh`로 받습니다.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from .schemas import FaceBox

__all__ = ["detect_faces", "face_model_available", "MODEL_DIR"]

MODEL_DIR = Path(os.environ.get("PVT_MODEL_DIR", Path(__file__).resolve().parents[1] / "models"))
_PROTO = MODEL_DIR / "deploy.prototxt"
_WEIGHTS = MODEL_DIR / "res10_300x300_ssd_iter_140000.caffemodel"

_INPUT_SIZE = (300, 300)
_MEAN = (104.0, 177.0, 123.0)
_MIN_CONFIDENCE = 0.6


def face_model_available() -> bool:
    return _PROTO.is_file() and _WEIGHTS.is_file()


@lru_cache(maxsize=1)
def _net():
    if not face_model_available():
        return None
    try:
        return cv2.dnn.readNetFromCaffe(str(_PROTO), str(_WEIGHTS))
    except cv2.error:
        return None


def detect_faces(img_bgr: np.ndarray, min_confidence: float = _MIN_CONFIDENCE) -> list[FaceBox]:
    """정규화된(0~1) 얼굴 바운딩박스 목록을 돌려준다.

    좌표를 픽셀이 아니라 비율로 저장하는 이유는 2단계에서 축소된 graded 이미지나
    미리보기 해상도에 그대로 재사용하기 위해서입니다.
    """
    net = _net()
    if net is None:
        return []

    h, w = img_bgr.shape[:2]
    blob = cv2.dnn.blobFromImage(
        cv2.resize(img_bgr, _INPUT_SIZE), 1.0, _INPUT_SIZE, _MEAN, swapRB=False, crop=False
    )
    net.setInput(blob)
    detections = net.forward()

    faces: list[FaceBox] = []
    for i in range(detections.shape[2]):
        conf = float(detections[0, 0, i, 2])
        if conf < min_confidence:
            continue
        x1, y1, x2, y2 = (float(v) for v in detections[0, 0, i, 3:7])
        x1, y1 = max(0.0, x1), max(0.0, y1)
        x2, y2 = min(1.0, x2), min(1.0, y2)
        if x2 <= x1 or y2 <= y1:
            continue
        faces.append(
            FaceBox(x=x1, y=y1, w=x2 - x1, h=y2 - y1, confidence=round(conf, 4))
        )
    _ = (w, h)  # 좌표는 이미 정규화되어 있어 원본 크기는 쓰지 않는다
    return faces
