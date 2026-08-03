#!/usr/bin/env bash
# OpenCV DNN SSD 얼굴 검출 모델을 backend/models/ 로 내려받습니다.
# 없어도 앱은 동작합니다(얼굴 기반 skin_max 상한과 얼굴 POI만 비활성).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/backend/models"
mkdir -p "$DIR"

PROTO_URL="https://raw.githubusercontent.com/opencv/opencv/4.x/samples/dnn/face_detector/deploy.prototxt"
WEIGHTS_URL="https://raw.githubusercontent.com/opencv/opencv_3rdparty/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel"

echo "→ deploy.prototxt"
curl -fsSL "$PROTO_URL" -o "$DIR/deploy.prototxt"
echo "→ res10_300x300_ssd_iter_140000.caffemodel (~10MB)"
curl -fsSL "$WEIGHTS_URL" -o "$DIR/res10_300x300_ssd_iter_140000.caffemodel"

echo "완료: $DIR"
