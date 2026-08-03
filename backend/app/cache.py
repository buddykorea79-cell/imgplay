"""파일시스템 캐시. DB는 쓰지 않습니다 — SHA-256 해시가 키입니다.

파일명은 중복되고 바뀝니다(섹션 12-8). "IMG_0001.jpg"는 폴더마다 있고, 같은
사진이 이름만 다르게 두 번 올라올 수도 있습니다. 내용 해시만이 안정적인 키입니다.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

__all__ = ["WorkDirs", "sha256_file", "sha256_str", "JsonCache", "params_key"]

_CHUNK = 1 << 20


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def sha256_str(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def params_key(*parts: Any) -> str:
    """파라미터 묶음을 안정적인 해시로. dict 키 순서에 의존하지 않도록 정렬합니다."""
    blob = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return sha256_str(blob)[:16]


class WorkDirs:
    """`work/` 하위 디렉터리 묶음."""

    def __init__(self, root: str | Path | None = None) -> None:
        env = os.environ.get("PVT_WORK_DIR")
        base = Path(root or env or Path(__file__).resolve().parents[2] / "work")
        self.root = base
        self.uploads = base / "uploads"
        self.graded = base / "graded"
        self.clips = base / "clips"
        self.out = base / "out"
        self.cache = base.parent / ".cache"
        for d in (self.uploads, self.graded, self.clips, self.out, self.cache):
            d.mkdir(parents=True, exist_ok=True)

    def clear_stage2(self) -> None:
        """1단계로 되돌아갈 때: graded/와 clips/를 무효화합니다.

        통계 캐시는 **유지합니다** — 원본이 바뀌지 않았으므로 다시 측정할 이유가
        없습니다(섹션 4).
        """
        for d in (self.graded, self.clips, self.out):
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True, exist_ok=True)


class JsonCache:
    """해시 키 → JSON 문서. 측정 결과처럼 재계산이 비싼 값을 담습니다."""

    def __init__(self, directory: Path, namespace: str) -> None:
        self.dir = directory / namespace
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def get(self, key: str) -> dict | None:
        p = self._path(key)
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # 깨진 캐시 항목은 캐시 미스로 취급한다. 다시 계산하면 그만이다.
            return None

    def set(self, key: str, value: dict) -> None:
        tmp = self._path(key).with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path(key))  # 원자적 교체: 부분 기록된 파일이 남지 않는다
